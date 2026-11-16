import io
import re
import urllib.parse
import pytz
import urllib
import datetime
import collections
import zipfile

import lxml.html
from openstates.exceptions import EmptyScrape
from openstates.scrape import Scraper, Bill, VoteEvent

from classify_motion import classify_motion
from . import utils
from . import actions


tz = pytz.timezone("America/New_York")

# OPEN-574: the Bill History export is rebuilt about once a day (the 2026-11-15 copy was
# built at 7:30 PM Eastern) and run-scrape.sh writes its watermark when a run ends, so a
# change made between the export and the run, or during the run, only shows in a later
# export with a time earlier than the next start=. Looking back two days covers both.
EXPORT_LOOKBACK = datetime.timedelta(days=2)
# Changes made after the export are left to the next run, whose lookback reaches back past
# this export only while the export is under a day old; an older one (the site stopped
# rebuilding it) means a full walk instead.
EXPORT_MAX_AGE = datetime.timedelta(days=1)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


# FYI: as of 2025 this should be run with --http-resilience
class PABillScraper(Scraper):
    session_year: str = ""
    verify = False

    def scrape(self, chamber=None, session=None, start=None):
        chambers = [chamber] if chamber is not None else ["upper", "lower"]

        # Session Year code needed to fix committee vote URLs
        # until new PA site fixes them
        for i in self.jurisdiction.legislative_sessions:
            if i["identifier"] == session:
                self.session_year = i.get("extras", {}).get("session_year", "2023")

        match = re.search(r"[S#](\d+)", session)
        special = int(match.group(1)) if match else 0

        # OPEN-574: the runners append start=<watermark> on every run after the first. With
        # it, only the bills the legislature's Bill History export marks as changed are
        # fetched; without it (or if the export cannot be used) every bill is, as before.
        self.changed_bills = self.known_bills = None
        # OPEN-576: the export is read on full walks too, for its fiscal and actuarial notes
        export = self.read_export(session, special)
        self.export_documents = self.documents_from_export(export)
        if start:
            self.changed_bills, self.known_bills = self.changed_since(export, start)
        self.incremental_stats = {"listed": 0, "selected": 0}

        for chamber in chambers:
            yield from self.scrape_session(chamber, session, special)

        # Nothing changed since the watermark (a quiet week) is a real answer, not a broken
        # scrape: tell do_scrape() so instead of letting it fail on zero objects (as VA and
        # UT do, OPEN-220/OPEN-106). A full walk that finds nothing still fails as before.
        if (
            self.changed_bills is not None
            and self.incremental_stats["listed"]
            and not self.incremental_stats["selected"]
        ):
            self.info("PA OPEN-574: no bill changed since %s", start)
            raise EmptyScrape

    def read_export(self, session, special):
        """The Bill History export's XML, or None (with a warning) if it cannot be read."""
        url = utils.bill_history_url(session, special)
        try:
            response = self.get(url, verify=False)
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = [n for n in archive.namelist() if n.lower().endswith(".xml")]
                return archive.read(names[0])
        except Exception as e:
            self.warning("PA: could not read the Bill History export %s (%s)", url, e)
            return None

    def documents_from_export(self, export):
        """OPEN-576: {bill key: [(note, url)]} of the export's fiscal and actuarial notes,
        or {} (the bill pages alone, as before) when the export cannot be read."""
        if export is None:
            return {}
        try:
            return utils.supporting_documents(export)
        except Exception as e:
            self.warning("PA OPEN-576: could not read the export's documents (%s)", e)
            return {}

    def changed_since(self, export, start):
        """OPEN-574: (changed, known) bill keys from the Bill History export, or
        (None, None) for a full walk when the export cannot be trusted."""
        try:
            start_dt = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            self.warning("PA OPEN-574: invalid start=%r, doing a full walk", start)
            return None, None
        if export is None:
            self.warning("PA OPEN-574: no Bill History export, doing a full walk")
            return None, None
        # the runners' watermark is UTC (run-scrape.sh writes `date -u`)
        start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        try:
            export_date, changed, known = utils.bills_changed_since(
                export, start_dt - EXPORT_LOOKBACK
            )
        except Exception as e:
            self.warning("PA OPEN-574: unreadable export (%s), doing a full walk", e)
            return None, None
        if export_date < _utcnow() - EXPORT_MAX_AGE:
            self.warning(
                "PA OPEN-574: the Bill History export is from %s, more than %s old, "
                "doing a full walk",
                export_date,
                EXPORT_MAX_AGE,
            )
            return None, None
        self.info(
            "PA OPEN-574: export of %s lists %d bills, %d changed since %s (start=%s "
            "minus %s)",
            export_date,
            len(known),
            len(changed),
            start_dt - EXPORT_LOOKBACK,
            start,
            EXPORT_LOOKBACK,
        )
        return changed, known

    def scrape_session(self, chamber, session, special=0):
        url = utils.bill_list_url(chamber, session, special)
        page = self.get_page(url)

        # PA website repeats some bills on the listing page
        # ex: resolutions that are also concurrent resolutions
        bill_urls_seen = set()

        RETRY_TIMES = 5
        for link in page.xpath('//a[@class="bill"]'):
            if link.attrib["href"] in bill_urls_seen:
                continue
            bill_urls_seen.add(link.attrib["href"])
            if self.changed_bills is not None:
                self.incremental_stats["listed"] += 1
                key = utils.bill_key(link.text.strip())
                # a bill the export does not list yet (filed after it was built) is fetched
                if key in self.known_bills and key not in self.changed_bills:
                    continue
                self.incremental_stats["selected"] += 1
            is_parsed = False
            for retry_time in range(0, RETRY_TIMES):
                try:
                    # collect first so a failed attempt yields nothing
                    objs = list(self.parse_bill(chamber, session, special, link))
                    yield from objs
                    is_parsed = True

                    break
                except Exception as e:
                    self.logger.warning(
                        "There was an error in scraping {}: Retry {}: Error: {}".format(
                            link.attrib["href"], retry_time + 1, e
                        )
                    )
            if not is_parsed:
                self.logger.error(
                    "Bill {} did not scrape due to the page scraping error. Skip".format(
                        link.text.strip()
                    )
                )

    def parse_bill(self, chamber, session, special, link):
        bill_id = link.text.strip()
        type_abbr = re.search("(b|r)", link.attrib["href"].split("/")[-1]).group(1)

        if type_abbr == "b":
            btype = ["bill"]
        elif type_abbr == "r":
            btype = ["resolution"]

        url = utils.info_url(session, special, bill_id)
        page = self.get_page(url)

        # Bill title (for PA title is a short abstract)
        # elem contains show/hide sub elements
        title = page.xpath("//div[@id='shortTitle-wrapper']")

        if title:
            title_part_one = title[0].xpath("./text()")  # "teaser" part of title
            title_part_two = title[0].xpath(
                ".//*[@id='shortTitle-more']/text()"
            )  # remainder
            if title_part_one and title_part_two:
                title = f"{title_part_one[0]}{title_part_two[0]}".strip()
            else:
                title = title_part_one[0].strip()
        else:
            self.warning("Skipping {} {}, No title found".format(bill_id, url))
            return

        bill = Bill(
            bill_id,
            legislative_session=session,
            title=title,
            chamber=chamber,
            classification=btype,
        )
        bill.add_source(url)

        # OPEN-576: some nights a bill's page gives none of its fiscal notes (about 70 bills
        # a night in November 2026, usually all of a bill's notes at once, never seen again
        # on a later fetch), and the import then deletes the stored notes until a later
        # walk sees them. The daily export lists the same notes under the same names and
        # links, so they are added from it first, in its order; the page can still add one
        # filed since the export was built.
        for note, doc_url in self.export_documents.get(utils.bill_key(bill_id), []):
            bill.add_document_link(
                note,
                doc_url,
                media_type=utils.document_media_type(doc_url),
                on_duplicate="ignore",
            )

        self.parse_bill_versions(bill, page)

        self.parse_history(
            bill,
            chamber,
            page,
        )

        # only fetch votes if votes were seen in history
        yield from self.parse_votes(bill, page)

        # Dedupe sources.
        sources = bill.sources
        for source in sources:
            if 1 < sources.count(source):
                sources.remove(source)

        yield bill

    def parse_bill_versions(self, bill, page):
        amendment_pages = {}
        for row in page.xpath('//div[@id="section-pn"]/div'):
            printers_number = 0
            for a in row.xpath(
                './/div[contains(@class, "btn-group")][@aria-label="Supporting Documents"]/a'
            ):
                mimetype = self.mimetype_from_class(a)

                doc_url = a.attrib["href"]
                params = doc_url.split("/")

                printers_number = params[-1]

                bill.add_version_link(
                    "Printer's No. %s" % printers_number,
                    doc_url,
                    media_type=mimetype,
                    on_duplicate="ignore",
                )

            for a in row.xpath(
                './/div[@class="accordion"]//div[@aria-label="Supporting Documents"]/a'
            ):
                doc_url = a.attrib["href"]
                doc_title = a.text_content()

                if "Amendments" in doc_title:
                    # House and Senate Amendments
                    amend_chamber = doc_title.replace("Amendments", "").strip()
                    self.scrape_amendments(
                        bill, doc_url, amend_chamber, amendment_pages
                    )
                elif "Fiscal Note" in doc_title:
                    # Senate & House Fiscal Notes
                    mimetype = self.mimetype_from_class(a)
                    bill.add_document_link(
                        # stored stripped anyway; stripped here so it matches the
                        # export's note of the same name (OPEN-576)
                        doc_title.strip(),
                        doc_url,
                        media_type=mimetype,
                        on_duplicate="ignore",
                    )
                elif "Actuarial Note" in doc_title:
                    # Actuarial Notes
                    mimetype = self.mimetype_from_class(a)
                    bill.add_document_link(
                        "Actuarial Note {}".format(printers_number),
                        doc_url,
                        media_type=mimetype,
                        on_duplicate="ignore",
                    )

    def scrape_amendments(self, bill, link, chamber_pretty, pages):
        if link not in pages:
            pages[link] = self.get_page(link)
        page = pages[link]

        for row in page.xpath('//div[contains(@class, "card shadow")]'):
            version_name = "".join(
                row.xpath(
                    './/div[contains(@class, "sponsor-details")]//div[contains(@class, " h5")]//text()'
                )
            ).strip()
            version_name = "{} Amendment {}".format(chamber_pretty, version_name)
            for a in row.xpath('.//div[contains(@class, "position-md-absolute")]//a'):
                mimetype = self.mimetype_from_class(a)
                version_link = a.attrib["href"]
                bill.add_version_link(
                    version_name,
                    version_link,
                    media_type=mimetype,
                    on_duplicate="ignore",
                )

    def parse_history(self, bill, chamber, doc):
        self.parse_sponsors(bill, doc)
        self.parse_actions(bill, chamber, doc)

    def parse_sponsors(self, bill, page):
        # Primary Sponsors
        xpath = (
            '//div[contains(@class, "h3 ")][contains(text(), "Prime Sponsor")]'
            "/following-sibling::div[1]//strong"
        )
        primary_sponsors = page.xpath(xpath)
        for sponsor in primary_sponsors:
            sponsor = utils.clean_sponsor_name(sponsor.text_content())
            if sponsor:
                bill.add_sponsorship(
                    sponsor,
                    classification="primary",
                    chamber=utils.get_sponsor_chamber(sponsor),
                    primary=True,
                    entity_type="person",
                )

        # Co-Sponsors
        xpath = (
            '//div[contains(@class, "h3 ")][text()="Co-Sponsors"]'
            "/following-sibling::div[1]//strong"
        )
        co_sponsors = page.xpath(xpath)
        for sponsor in co_sponsors:
            sponsor = utils.clean_sponsor_name(sponsor.text_content())
            if sponsor:
                bill.add_sponsorship(
                    sponsor,
                    classification="cosponsor",
                    chamber=utils.get_sponsor_chamber(sponsor),
                    primary=False,
                    entity_type="person",
                )
        # Collapsed Co-Sponsors
        xpath = '//div[@id="coSponsAdd"]//strong'
        co_sponsors = page.xpath(xpath)
        for sponsor in co_sponsors:
            sponsor = utils.clean_sponsor_name(sponsor.text_content())
            if sponsor:
                bill.add_sponsorship(
                    sponsor,
                    classification="cosponsor",
                    chamber=utils.get_sponsor_chamber(sponsor),
                    primary=False,
                    entity_type="person",
                )

    def parse_actions(self, bill, chamber, page):
        for tr in page.xpath(
            '//div[@id="billActions"]//div[@id="collapseActions"]//table//tr'
        ):
            action = tr[1].xpath("string()").replace("\xa0", " ").strip()

            if action == "In the House":
                chamber = "lower"
                continue
            elif action == "In the Senate":
                chamber = "upper"
                continue
            elif action.startswith("(Remarks see"):
                continue
            match = re.match(
                r"(.*),\s+(\w+\.?\s+\d{1,2},\s+\d{4})( \(\d+-\d+\))?", action
            )
            if not match:
                continue

            action = match.group(1)
            date = utils.parse_action_date(match.group(2))
            types = list(actions.categorize(action))
            bill.add_action(
                action, tz.localize(date), chamber=chamber, classification=types
            )

    def parse_votes(self, bill, page):
        vote_urls = []

        for url in page.xpath(
            '//div[contains(text(), "Votes")]/following-sibling::div[1]//a/@href'
        ):
            # Floor RC urls have old domain in the website
            # We need to update the new urls
            if url.startswith(utils.old_base_url):
                url = self.fix_url_domain(url)
            # Skip the duplicated URLs
            if url in vote_urls:
                self.logger.debug("Vote URL is duplicated: {}".format(url))
                continue
            vote_urls.append(url)

            bill.add_source(url)
            if "/roll-calls/" in url:
                yield from self.parse_chamber_votes(bill, url)
            elif "/roll-call-votes/" in url:
                # As of Nov 2024, this URL in the new site is broken
                # but works if we add a query param
                if "sessyr" not in url.lower():
                    url = f"{url}&sessYr={self.session_year}"
                yield from self.parse_committee_votes(bill, url)
            else:
                msg = "Unexpected vote url: %r" % url
                raise Exception(msg)

    def get_page(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
        }
        html = self.get(url, verify=False, headers=headers).text
        page = lxml.html.fromstring(html)
        page.make_links_absolute(url)
        return page

    def parse_chamber_votes(self, bill, url):
        page = self.get_page(url)

        chamber = "upper" if "Senate" in page.xpath("string(//h1)") else "lower"
        date_str = (
            page.xpath(
                'string(//div[contains(@class, "col-main")]//div[./div[contains(text(), "Vote Date")]])'
            )
            .replace("Vote Date", "")
            .strip()
        )
        date_str = re.sub(r"\s+", " ", date_str)
        date = tz.localize(
            datetime.datetime.strptime(date_str, "%A %b %d, %Y %I:%M %p")
        )

        xpath = 'string(//div[contains(@class,h6)][contains(text(), "Action")]/..)'
        motion = page.xpath(xpath).replace("Action", "").strip()
        motion = re.sub(r"\s+", " ", motion).upper()
        if motion == "FP":
            motion = "FINAL PASSAGE"

        if re.match(r"CONCUR(RENCE)? IN \w+ AMENDMENTS", motion):
            type = "amendment"
        else:
            # OPEN-478: rules live in config/motion_classification.yaml (pa block)
            type = classify_motion("pa", motion)
            if not motion:
                xpath = '//div[contains(@class,h6)][contains(text(), "Bill")]/../a'
                motion = page.xpath(xpath)[1].text_content().strip()
                motion = re.sub(r"\s+", " ", motion)

        yeas_elements = page.xpath(
            '//div[@id="voteSummary"]//div[contains(., "Yea")]/div[2]'
        )[0]
        yeas = int(yeas_elements.text_content())

        nays_elements = page.xpath(
            '//div[@id="voteSummary"]//div[contains(., "Nay")]/div[2]'
        )[0]
        nays = int(nays_elements.text_content())
        # element
        other = 0
        lve_elements = page.xpath(
            '//div[@id="voteSummary"]//div[contains(., "Leave")]/div[2]'
        )
        if lve_elements:
            other += int(lve_elements[0].text_content())
        nv_elements = page.xpath(
            '//div[@id="voteSummary"]//div[contains(., "No Vote")]/div[2]'
        )
        if nv_elements:
            other += int(nv_elements[0].text_content())

        vote = VoteEvent(
            chamber=chamber,
            start_date=date,
            motion_text=motion,
            classification=type,
            result="pass" if yeas > (nays + other) else "fail",
            bill=bill,
        )
        # dedupe_key situation here is a bit weird, same vote can be used for
        # multiple bills see:
        # so we toss the bill id onto the end of the URL
        vote.dedupe_key = url + "#" + bill.identifier
        rc_number = self.url_param(url, "rcnum")
        if rc_number:
            vote.identifier = "RC#%s" % rc_number
        vote.add_source(url)
        vote.set_count("yes", yeas)
        vote.set_count("no", nays)
        vote.set_count("other", other)

        for div in page.xpath(
            '//div[contains(@class, "rc-member ")][./div[contains(@class, "rc-member-display ")]]'
        ):
            name = div.xpath("string(.//strong)") or div.xpath(
                'string(.//div[contains(@class, "rc-member-print")])'
            )
            name = utils.clean_sponsor_name(name)
            if not name:
                msg = "voter name is none. Referrer url: %s" % url
                raise Exception(msg)
            badge = (
                "".join(div.xpath('.//span[contains(@class, "badge")][@title]/@title'))
                .replace(" ", "")
                .lower()
            )
            if "yea" in badge:
                voteval = "yes"
            elif "nay" in badge:
                voteval = "no"
            elif "novote" in badge:
                voteval = "other"
            elif "leave" in badge:
                voteval = "other"
            else:
                msg = "Unrecognized vote val: %s" % badge
                raise Exception(msg)
            vote.vote(voteval, name)

        yield vote

    def parse_committee_votes(self, bill, url):
        doc = self.get_page(url)

        chamber = "upper" if "Senate" in doc.xpath("string(//h1)") else "lower"
        committee = doc.xpath(
            'string(//div[contains(@class, "detailsLabel")][contains(., "Committe")]/following-sibling::div/a)'
        ).strip()

        date = doc.xpath(
            'string(//div[contains(@class, "detailsLabel")][contains(., "Date")]/following-sibling::div/a)'
        ).strip()
        date = tz.localize(datetime.datetime.strptime(date, "%B %d, %Y"))
        self.logger.info("Committee Vote Date: {}, URL: {}".format(date, url))
        # Motion
        motion = doc.xpath(
            'string(//div[contains(text(), "Type of Motion")]/following-sibling::div[1])'
        ).strip()
        motion = "Committee vote (%s): %s" % (committee, motion)
        # Several amendments can be voted on at one meeting; the amendment
        # number (e.g. "HB 1924 PN 2398 A01909") tells them apart
        bill_info = doc.xpath(
            'string(//div[contains(@class, "detailsLabel")][contains(., "Bill/Resolution")]/following-sibling::div)'
        )
        amendment = re.search(r"\bA\d+\b", bill_info)
        if amendment:
            motion = "%s %s" % (motion, amendment.group(0))

        # Roll call
        rollcall = self.parse_upper_committee_vote_rollcall(doc)

        vote = VoteEvent(
            chamber=chamber,
            start_date=date,
            motion_text=motion,
            classification=classify_motion("pa", motion),
            result="pass" if rollcall["passed"] else "fail",
            bill=bill,
        )
        vote.dedupe_key = url + "#" + bill.identifier
        # Roll calls at one meeting can share motion, date and roll;
        # PA's roll call id tells them apart
        rollcall_id = self.url_param(url, "rollcallid")
        if rollcall_id:
            vote.identifier = "RCS#%s" % rollcall_id
        vote.set_count("yes", rollcall["yes_count"])
        vote.set_count("no", rollcall["no_count"])
        vote.set_count("other", rollcall["other_count"])

        for voteval in ("yes", "no", "other"):
            for name in rollcall.get(voteval + "_votes", []):
                vote.vote(voteval, name)

        vote.add_source(url)

        yield vote

    def parse_upper_committee_vote_rollcall(self, doc):
        rollcall = collections.defaultdict(list)

        for div in doc.xpath(
            '//div[contains(., "Member Votes")][contains(@class, "card-header")]/following-sibling::div[1]//ul/li'
        ):
            name = utils.clean_sponsor_name(div.xpath(".//a/text()")[0])
            badge = (
                "".join(div.xpath('.//span[contains(@class, "badge")][@title]/@title'))
                .replace(" ", "")
                .lower()
            )
            if "yea" in badge:
                voteval = "yes"
            elif "nay" in badge:
                voteval = "no"
            elif "novote" in badge:
                voteval = "other"
            elif "leave" in badge:
                voteval = "other"
            else:
                msg = "Unrecognized vote val: %s" % badge
                raise Exception(msg)
            rollcall[voteval + "_votes"].append(name)

        for voteval, xpath in (
            ("yes", '//ul/li//span[contains(@class, "badge")][@title="Yea"]'),
            ("no", '//ul/li//span[contains(@class, "badge")][@title="Nay"]'),
            (
                "other",
                '//ul/li//span[contains(@class, "badge")][@title="No Vote"]',
            ),
        ):
            count = len(doc.xpath(xpath))
            rollcall[voteval + "_count"] = int(count)

        rollcall["passed"] = rollcall["yes_count"] > rollcall["no_count"]

        return dict(rollcall)

    def mimetype_from_class(self, link):
        mimetypes = {
            "fa-edge": "text/html",
            "fa-file-pdf": "application/pdf",
            "fa-file-word": "application/msword",
        }
        try:
            span = link[0]
        except IndexError:
            return
        for cls in span.attrib["class"].split():
            if cls in mimetypes:
                mimetype = mimetypes[cls]
                return mimetype

    def url_param(self, url, name):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for key, values in query.items():
            if key.lower() == name:
                return values[0]

    def fix_url_domain(self, url):
        # Some vote urls have the old domain in the new website
        # https://www.legis.state.pa.us/cfdocs/legis/RC/Public/rc_view_action2.cfm
        # ?sess_yr=2023&sess_ind=1&rc_body=H&rc_nbr=17
        url_query = url.split("?")[1]
        url_query_obj = urllib.parse.parse_qs(url_query)
        chamber = "house" if url_query_obj["rc_body"][0] == "H" else "senate"
        return utils.vote_url(
            chamber,
            url_query_obj["sess_yr"][0],
            url_query_obj["sess_ind"][0],
            url_query_obj["rc_nbr"][0],
        )
