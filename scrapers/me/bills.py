import re
import html
import pytz
import socket
import time
import datetime
import dateutil.parser

import requests
import lxml.html
import scrapelib

from openstates.scrape import Scraper, Bill, VoteEvent

from classify_motion import classify_motion

from .actions import Categorizer
from .sessions import legislature, session_for_bill, session_for_roll_call

# by Legislature (OPEN-747: every session of it reads its one bill list)
BLACKLISTED_BILL_IDS = {128: ("SP 601", "SP 602"), 129: (), 130: ()}

# OPEN-698: a floor amendment roll call ("ADOPT HAH-126 to CAS-44", "INDEF PP HAH-2 TO
# CAH-1", "IPP HAH-640", "INDEFINITELY POSTPONE SENATE AMENDMENT (SAS-1)"), labelled here
# because config/motion_classification.yaml only decides passage. It needs both an adopt or
# postpone verb and an amendment (the word, or a filing number such as CAH-1 or S-426), so
# a bare "INDEFINITELY POSTPONE" of the bill itself is not one.
AMENDMENT_VOTE = re.compile(
    r"^(adopt|indef(initely)?\.? ?pp|indefinitely postpone|ipp)\b"
    r".*(\bamend|\b[a-z]{1,3}-\d+\b|\bc ?a\b)",
    re.I,
)


# OPEN-698 (Ramon, comment 21956): accepting an "Ought to Pass" report ("ACC MAJ OTP AS AMENDED
# REP", "ACCEPT REPORT 'A' OUGHT TO PASS", 'acc report "a" otp-am by ca "a"', a bare "OTP-AM") is
# passage unless the same chamber also held the bill's enactment or final roll call (FINAL_ROLL_CALL):
# that chamber's final roll call replaces it (Ramon, OPEN-698: per chamber, not per bill). Decided in
# scrape_votes(), since one roll call's text cannot say.
OUGHT_TO_PASS_REPORT = re.compile(
    r"^((acc(ept(ance of the)?)? |report ).*\b(ought to pass|otp)\b|otp(-am)?$)", re.I
)
# A bill's (or resolve's, order's, resolution's) own final roll call: enactment, final passage, an
# emergency measure's passage, an order's "PASSAGE", a resolution's "ADOPTION".
FINAL_ROLL_CALL = re.compile(
    r"^(enact|final passage\b|passage( of emergency measure)?$|adoption$)", re.I
)


def first_action_date(html):
    """The earliest date in a dockets.asp page's action table, or None (OPEN-747)."""
    page = lxml.html.fromstring(html)
    dates = []
    for row in page.xpath("//b[. = 'Date']/../../../following-sibling::tr"):
        try:
            dates.append(
                datetime.datetime.strptime(row.xpath("string(td[1])"), "%m/%d/%Y")
            )
        except ValueError:
            continue
    return min(dates).date() if dates else None


def vote_classification(motion):
    """What a floor roll call decides: passage from the me block of
    config/motion_classification.yaml, else "amendment" for an amendment roll call,
    else nothing (committee-report, postponement, recede and procedural votes)."""
    classification = classify_motion("me", motion)
    if classification:
        return classification
    if AMENDMENT_VOTE.search(motion):
        return ["amendment"]
    return []


class MEBillScraper(Scraper):
    categorizer = Categorizer()
    _tz = pytz.timezone("US/Eastern")

    def get(self, url, **kwargs):
        # scrapelib never retries an SSLError, but the site now and then drops
        # a connection mid TLS handshake (SSLEOFError), which ended the scrape
        for attempt in range(self.retry_attempts):
            try:
                return super().get(url, **kwargs)
            except requests.exceptions.SSLError as e:
                self.warning(f"{e}, retrying")
                time.sleep(self.retry_wait_seconds * 2**attempt)
        return super().get(url, **kwargs)

    def scrape(self, chamber=None, session=None, first_item=1):
        first_item = int(first_item)  # parse string arg from CLI to int
        chambers = [chamber] if chamber is not None else ["upper", "lower"]

        for chamber in chambers:
            yield from self.scrape_chamber(chamber, session, first_item)

    def _start_search(self, request_session, chamber, session):
        # the result pages belong to this search, held server side on the session
        search_url = "https://legislature.maine.gov/LawMakerWeb/doadvancedsearch.asp"
        number = legislature(self.jurisdiction.legislative_sessions, session)
        session_number = str(number - 116)
        paper_type = "HP" if chamber == "lower" else "SP"
        form_data = {
            "PaperType": paper_type,
            "LegSession": session_number,
            "LRType": "None",
            "Sponsor": "None",
            "Introducer": "None",
            "Committee": "None",
            "AmdFilingChamber": "None",
            "RollcallChamber": "None",
            "Action": "None",
            "ActionChamber": "None",
            "GovernorAction": "None",
            "FinalLawType": "None",
        }
        r = request_session.post(url=search_url, data=form_data, timeout=self.timeout)
        r.raise_for_status()

    def scrape_chamber(self, chamber, session, first_item=1):
        # Create a Bill for each Paper of the chamber's session
        request_session = requests.Session()
        self._start_search(request_session, chamber, session)

        self.seen = set()
        self.dockets = {}
        yield from self._recursively_process_bills(
            request_session=request_session,
            chamber=chamber,
            session=session,
            first_item=first_item,
        )

    def _recursively_process_bills(
        self, request_session, chamber, session, first_item=1
    ):
        """
        Once a search has been initiated, this function will save a
        Bill object for every Paper from the given chamber
        """

        self.logger.info(
            f"Searching bills in {chamber} starting with item {first_item}"
        )
        url = "https://legislature.maine.gov/LawMakerWeb/searchresults.asp"
        # a page of results occasionally comes back empty, or the connection
        # drops, part way through a chamber: both end the scrape where it stands,
        # so re-run the search and ask once more before believing either
        bills = []
        for attempt in range(2):
            if attempt:
                self._start_search(request_session, chamber, session)
            try:
                r = request_session.get(
                    url, params={"StartWith": first_item}, timeout=self.timeout
                )
                r.raise_for_status()
            except requests.exceptions.RequestException as e:
                self.warning(f"search results at item {first_item} failed: {e}")
                continue
            bills = lxml.html.fromstring(r.text).xpath("//tr/td/b/a")
            if bills:
                break
        if bills:
            for bill in bills:
                bill_id_slug = bill.xpath("./@href")[0]
                if bill_id_slug == "summary.asp?ID=280068396":
                    self.logger.info("Skipping bill_id_slug ID=280068396")
                    continue
                bill_url = "https://legislature.maine.gov/LawMakerWeb/{}".format(
                    bill_id_slug
                )
                bill_id = bill.text[:2] + " " + bill.text[2:]
                bill_id = re.sub(r"\s+", " ", bill_id).strip()

                number = legislature(self.jurisdiction.legislative_sessions, session)
                if bill_id in BLACKLISTED_BILL_IDS.get(number, ()):
                    self.logger.info(f"Skipping blacklisted bill ID {bill_id}")
                    continue

                # avoid duplicates
                if bill_id in self.seen:
                    continue
                self.seen.add(bill_id)

                # OPEN-747: every session of the Legislature reads its one bill list; a bill
                # belongs to one session only, decided by its first dated action (sessions.py).
                # Its docket (the Actions tab) is read here, once, and kept for scrape_actions.
                docket_url = bill_url.replace("summary.asp", "dockets.asp")
                docket = self.get(docket_url, retry_on_404=True).text
                first_action = first_action_date(docket)
                owner = session_for_bill(
                    self.jurisdiction.legislative_sessions, number, first_action
                )
                if owner is None:
                    self.warning(
                        f"Skipping {bill_id}: no session of the {number} Legislature holds "
                        f"its first dated action ({first_action})"
                    )
                    continue
                if owner != session:
                    self.info(f"Skipping {bill_id}: it belongs to {owner}")
                    continue
                self.dockets[docket_url] = docket

                bill = Bill(
                    identifier=bill_id,
                    legislative_session=session,
                    title="",
                    chamber=chamber,
                )
                bill.add_source(bill_url)

                yield from self.scrape_bill(bill, chamber)
                yield bill

            # Make a recursive call to this function, for the next page
            PAGE_SIZE = 25
            yield from self._recursively_process_bills(
                request_session=request_session,
                chamber=chamber,
                session=session,
                first_item=first_item + PAGE_SIZE,
            )
        else:
            self.logger.info(f"Found no bills at search StartWith {first_item}")

    def scrape_bill(self, bill: Bill, chamber):
        url = bill.sources[0]["url"]
        html = self.get(url).text
        page = lxml.html.fromstring(html)
        page.make_links_absolute(url)

        # Get and apply the bill title
        bill_title = page.xpath("./body/table/td/table/td/b/text()")[0]
        bill_title = bill_title[1:-1].title()
        bill.title = bill_title

        if bill_title.startswith("Joint Order") or bill_title.startswith(
            "Joint Resolution"
        ):
            bill.classification = ["joint resolution"]
        else:
            bill.classification = ["bill"]

        # Add the LD number in.
        for ld_num in page.xpath("//b[contains(text(), 'LD ')]/text()"):
            if re.search(r"LD \d+", ld_num):
                bill.extras = {"ld_number": ld_num}

        if "Bill not found." in html:
            raise AssertionError('%s returned "Bill not found." page' % url)

        # Add bill sponsors.
        try:
            xpath = '//a[contains(@href, "sponsors")]/@href'
            sponsors_url = page.xpath(xpath)[0]
        except IndexError:
            msg = (
                "Page didn't contain sponsors url with expected "
                "format. Page url was %s" % url
            )
            raise ValueError(msg)
        sponsors_html = self.get(sponsors_url, retry_on_404=True).text
        sponsors_page = lxml.html.fromstring(sponsors_html)
        sponsors_page.make_links_absolute(sponsors_url)

        tr_text = sponsors_page.xpath("./body/table/td/table/tr/td//text()")
        rgx = r"^\s*(Speaker|President|Senator|Representative) ([\w\s]+?)( of .+)\s*$"

        for text in tr_text:
            if "the Majority" in text:
                # At least one bill was sponsored by 'the Majority'.
                bill.add_sponsorship(
                    name="the Majority",
                    chamber=chamber,
                    entity_type="person",
                    classification="primary",
                    primary=True,
                )
                continue

            if text.lower().startswith("sponsored by:"):
                type_ = "primary"
            elif "introduc" in text.lower():
                type_ = "primary"
            elif text.lower().startswith("cosponsored by:"):
                type_ = "cosponsor"

            elif re.match(rgx, text):
                chamber_title, name = [
                    x.strip() for x in re.search(rgx, text).groups()[:2]
                ]
                if chamber_title in ["President", "Speaker"]:
                    spon_chamber = chamber
                else:
                    spon_chamber = {"Senator": "upper", "Representative": "lower"}[
                        chamber_title
                    ]
                bill.add_sponsorship(
                    name=name.strip(),
                    chamber=spon_chamber,
                    entity_type="person",
                    classification=type_.lower(),
                    primary=type_.lower() == "primary",
                )

        bill.add_source(sponsors_url)

        docket_link = page.xpath("//a[contains(@href, 'dockets.asp')]")[0]
        self.scrape_actions(bill, docket_link.attrib["href"])

        # Add signed by guv action.
        if page.xpath('//b[contains(text(), "Signed by the Governor")]'):
            # TODO: this is a problematic way to get governor signed action,
            #       see 122nd legislature LD 1235 for an example of this phrase
            #       appearing in the bill title!
            date = page.xpath(
                (
                    'string(//td[contains(text(), "Date")]/'
                    "following-sibling::td/b/text())"
                )
            )
            try:
                dt = datetime.datetime.strptime(date, "%m/%d/%Y")
            except ValueError:
                self.warning("Could not parse signed date {0}".format(date))
            else:
                bill.add_action(
                    "Signed by Governor",
                    date=dt.strftime("%Y-%m-%d"),
                    chamber="executive",
                    classification=["executive-signature"],
                )
        # Add Become Law action
        if page.xpath(
            '//b[contains(text(), "Became Law without Governor\'s Signature")]'
        ):
            date = page.xpath(
                (
                    'string(//td[contains(text(), "Date")]/'
                    "following-sibling::td/b/text())"
                )
            )
            try:
                dt = datetime.datetime.strptime(date, "%m/%d/%Y")
            except ValueError:
                self.warning("Could not parse signed date {0}".format(date))
            else:
                bill.add_action(
                    "Became Law without Governor's Signature",
                    date=dt.strftime("%Y-%m-%d"),
                    chamber=chamber,
                    classification=["became-law"],
                )

        xpath = "//a[contains(@href, 'rollcalls.asp')]"
        votes_link = page.xpath(xpath)[0]
        yield from self.scrape_votes(bill, votes_link.attrib["href"])

        spon_link = page.xpath("//a[contains(@href, 'subjects.asp')]")[0]
        spon_url = spon_link.get("href")
        bill.add_source(spon_url)
        spon_html = self.get(spon_url, retry_on_404=True).text
        sdoc = lxml.html.fromstring(spon_html)
        xpath = '//table[@class="sectionbody"]/tr[2]/td/text()'
        srow = sdoc.xpath(xpath)[1:]
        if srow:
            bill.subject = [s.strip() for s in srow if s.strip()]

        # Attempt to find link to bill text/documents.
        ver_link = page.xpath("//a[contains(@href, 'display_ps.asp')]")[0]
        ver_url = ver_link.get("href")

        try:
            ver_html = self.get(
                ver_url.replace("http://www.", "https://www.", 1), retry_on_404=True
            ).text
        except (socket.timeout, requests.exceptions.HTTPError):
            pass
        else:
            if ver_html:
                vdoc = lxml.html.fromstring(ver_html)

                # Check whether the bill text is missing.
                is_bill_text_missing = vdoc.xpath(
                    'boolean(//div[@id = "sec0" \
                    and contains(.,"Cannot find requested paper")])'
                )

                previous_title = ""
                if not is_bill_text_missing:
                    vdoc.make_links_absolute(ver_url)
                    for row in vdoc.cssselect("span.tlnk-bill, span.tlnk-fiscal"):
                        title = " ".join(
                            row.xpath(
                                ".//span[@class='story_header' or @class='story_subhead' or @class='inlineHeading']/text()"
                            )
                        ).strip()
                        title = (
                            title.replace("Text", "")
                            .replace("RESLV ", "")
                            .replace("ACTPUB", "")
                            .replace("Chapter Fiscal Note", "")
                            .strip()
                        )
                        classification = ""
                        if row.xpath("parent::span[contains(@class, 'tlnk-amdblk')]"):
                            title = f"Amendment {title}"
                            classification = "amendment"

                        if row.xpath(".//a[contains(@href, 'getPDF')]"):
                            pdf_url = row.xpath(
                                ".//a[contains(@href, 'getPDF')]/@href"
                            )[0]
                            bill.add_version_link(
                                title,
                                pdf_url,
                                classification=classification,
                                media_type="application/pdf",
                                on_duplicate="ignore",
                            )
                        if row.xpath(".//a[contains(@href, '/fiscalpdfs/')]"):
                            pdf_url = row.xpath(
                                ".//a[contains(@href, 'fiscalpdfs')]/@href"
                            )[0]
                            bill.add_document_link(
                                f"{previous_title} - Fiscal Note",
                                pdf_url,
                                classification="fiscal-note",
                                media_type="application/pdf",
                                on_duplicate="ignore",
                            )
                        previous_title = title
                    # committee actions are also on this page
                    for row in vdoc.xpath('//table[@name="CDtab"]/tr')[2:]:
                        action_date = row.xpath("td[1]/text()")[0].strip()
                        action_date = dateutil.parser.parse(action_date)
                        action_date = self._tz.localize(action_date)

                        action = row.xpath("td[2]/text()")[0].strip()

                        result = row.xpath("td[3]/text()")[0].strip()
                        if result != "":
                            action = f"{action} - {result}".strip()

                        attrs = self.categorizer.categorize(action)
                        bill.add_action(
                            action,
                            action_date,
                            chamber="legislature",  # Maine committees are joint
                            classification=attrs["classification"],
                        )

    def scrape_votes(self, bill, url):
        page = self.get(url, retry_on_404=True).text
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)

        path = "//div/a[contains(@href, 'rollcall.asp')]"
        seen_urls = set()
        votes = []
        for link in page.xpath(path):
            # skip blank motions, nothing we can do with these
            # seen on /LawMakerWeb/rollcalls.asp?ID=280039835
            if link.text:
                motion = link.text.strip()
                url = link.attrib["href"]

                # some roll calls are listed twice on the same page
                # seen on /LawMakerWeb/rollcalls.asp?ID=280097788
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                votes.extend(self.scrape_vote(bill, motion, url))

        # chambers with their own final roll call, by the identifier's "S-" / "H-" prefix
        final_chambers = {
            v.identifier.split("-")[0]
            for v in votes
            if FINAL_ROLL_CALL.search(v.motion_text)
        }
        for vote in votes:
            chamber = vote.identifier.split("-")[0]
            if chamber not in final_chambers and OUGHT_TO_PASS_REPORT.search(
                vote.motion_text
            ):
                vote.motion_classification = ["passage"]
            yield vote

    def scrape_vote(self, bill, motion, url):
        page = self.get(url, retry_on_404=True).text
        page = lxml.html.fromstring(page)

        yeas_cell = page.xpath("//td[text() = 'Yeas (Y):']")[0]
        yes_count = int(yeas_cell.xpath("string(following-sibling::td)"))

        nays_cell = page.xpath("//td[text() = 'Nays (N):']")[0]
        no_count = int(nays_cell.xpath("string(following-sibling::td)"))

        abs_cell = page.xpath("//td[text() = 'Absent (X):']")[0]
        abs_count = int(abs_cell.xpath("string(following-sibling::td)"))

        ex_cell = page.xpath("//td[text() = 'Excused (E):']")[0]
        ex_count = int(ex_cell.xpath("string(following-sibling::td)"))

        other_count = abs_count + ex_count

        if "chamber=House" in url:
            chamber = "lower"
        elif "chamber=Senate" in url:
            chamber = "upper"

        date_cell = page.xpath("//td[text() = 'Date:']")[0]
        date = date_cell.xpath("string(following-sibling::td)")
        try:
            date = datetime.datetime.strptime(date, "%B %d, %Y")
        except ValueError:
            date = datetime.datetime.strptime(date, "%b. %d, %Y")

        outcome_cell = page.xpath("//td[text()='Outcome:']")[0]
        outcome = outcome_cell.xpath("string(following-sibling::td)")

        # OPEN-747: a roll call is filed under the session sitting on its date, though its bill
        # may be filed under an earlier session of the same Legislature
        sessions = self.jurisdiction.legislative_sessions
        number = legislature(sessions, bill.legislative_session)
        sitting = session_for_roll_call(sessions, number, date.date())
        if sitting is None:
            self.warning(
                f"Skipping roll call {url}: no session of the {number} Legislature sat on "
                f"{date.date()}"
            )
            return

        # same-day roll calls can share motion and roll, so keep the RC number
        serial = re.search(r"serialnumber=(\d+)", url).group(1)
        vote = VoteEvent(
            legislative_session=sitting,
            identifier=f"{'S' if chamber == 'upper' else 'H'}-RC {serial}",
            chamber=chamber,
            start_date=date.strftime("%Y-%m-%d"),
            motion_text=motion,
            result="pass" if outcome == "PREVAILS" else "fail",
            classification=vote_classification(motion),
            bill=bill,
        )
        vote.set_count("yes", yes_count)
        vote.set_count("no", no_count)
        vote.set_count("other", other_count)
        vote.add_source(url)
        vote.dedupe_key = url

        member_cell = page.xpath("//td[text() = 'Member']")[0]
        for row in member_cell.xpath("../../tr")[1:]:
            name = row.xpath("string(td[2])")
            # name = name.split(" of ")[0]

            vtype = row.xpath("string(td[4])")
            if vtype == "Y":
                vote.vote("yes", name)
            elif vtype == "N":
                vote.vote("no", name)
            elif vtype == "X" or vtype == "E":
                vote.vote("other", name)

        yield vote

    def scrape_actions(self, bill, url):
        try:
            page = self.dockets.pop(url, None) or self.get(url, retry_on_404=True).text
        except scrapelib.HTTPError:
            self.warning(
                "Error loading actions webpage for bill {}".format(bill["bill_id"])
            )
            return

        page = lxml.html.fromstring(page)
        bill.add_source(url)

        path = "//b[. = 'Date']/../../../following-sibling::tr"
        for row in page.xpath(path):
            date = row.xpath("string(td[1])")
            date = datetime.datetime.strptime(date, "%m/%d/%Y").date()

            chamber = row.xpath("string(td[2])").strip()
            if chamber == "Senate":
                chamber = "upper"
            elif chamber == "House":
                chamber = "lower"

            action = gettext(row[2])
            action = html.unescape(action).strip()

            actions = []
            for action in action.splitlines():
                action = re.sub(r"\s+", " ", action)
                action = action.strip()
                if not action or "Unfinished Business" in action:
                    continue

                actions.append(action)

            for action in actions:
                attrs = self.categorizer.categorize(action)
                bill.add_action(
                    action,
                    date,
                    chamber=chamber,
                    classification=attrs["classification"],
                )


def _get_chunks(el, buff=None):
    tagmap = {"br": "\n"}
    buff = buff or []

    # Tag, text, tail, recur...
    yield tagmap.get(el.tag.lower(), "")
    yield el.text or ""

    for kid in el:
        for text in _get_chunks(kid):
            yield text
    if el.tail:
        yield el.tail
    if el.tag == "text":
        yield "\n"


def gettext(el):
    """Join the chunks, then split and rejoin to normalize the whitespace."""
    return "".join(_get_chunks(el))
