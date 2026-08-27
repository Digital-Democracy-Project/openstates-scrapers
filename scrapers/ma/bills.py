import re
import requests

import os
import json
from datetime import datetime
import lxml.html
from openstates.scrape import Scraper, Bill, VoteEvent
from classify_motion import classify_motion
from openstates.utils import convert_pdf
from openstates.utils.transformers import fix_bill_id

from .actions import Categorizer


requests.packages.urllib3.disable_warnings()


# OPEN-176: a Senate roll call's PDF is named after the roll-call number the
# action text itself cites, and that is the ONLY reliable way to find it.
#
# The scraper used to take `td[3]/a/@href` -- the first link in the action cell --
# and treat it as the roll-call PDF. That cell carries several unrelated kinds of
# link (Chapter-of-the-Acts text, cross-references to another bill number, and an
# amendment's own content page), so the first one is frequently not the roll call.
# Measured across MA 194th: of 118 Senate vote events that imported with a real
# tally and zero voters, 115 had been pointed at
# `/Bills/GetAmendmentContent/.../Preview` -- an 818-byte HTML modal, not a PDF.
# `convert_pdf` on that HTML fails with "Couldn't find trailer dictionary", which
# is why OPEN-176 was first filed as a malformed-PDF problem. The file is not a
# malformed PDF; it was never a PDF.
#
# Deriving the URL from the cited number instead is not a guess -- it is the rule
# the working data already follows. Of the 110 Senate vote events that DID import
# voters, 109 have a `Roll Call #<n>` in their bill's action text whose number
# equals the number in the URL that worked. All 115 broken events have such a
# number available on a same-date action, so this recovers them.
_SENATE_ROLLCALL_URL = "http://malegislature.gov/RollCall/{}/SenateRollCall{}.pdf"
_ROLLCALL_NUMBER_RE = re.compile(r"Roll\s+Call\s+#\s*(\d+)", re.I)

# OPEN-177: Massachusetts writes the nay count three different ways, and the
# scraper only accepted one of them.
#
# The gate used to require the literal substring "nays", so an action reading
# "(Yeas 39 to Nay 0)" created no vote event at all -- not a tally-only vote, no
# vote. Across MA 194th's 236 roll-call actions, 230 match the old condition and
# 6 do not: 3 use the singular "Nay", 1 is a source-side typo that writes the nay
# count as "Yeas" ("Yeas 39 to Yeas 0", S 2565), and 2 are quorum roll calls
# handled separately below. Those 4 are 4 of the 6 bills in OPEN-177 that cite a
# Senate roll call while holding no Senate vote.
#
# The second pattern accepts "Yeas" in the nay position deliberately. It is a
# transcription error on the legislature's side, and the alternative -- dropping
# the vote -- loses a real 39-0 roll call whose PDF is available and readable.
# The count is recorded from the text, as it always was; the voters come from the
# PDF, which is authoritative either way.
_SENATE_TALLY_RES = (
    # "39 yeas ... 0 nays" -- the older form, e.g. 2019 H86.
    re.compile(r"(\d+)\s+yeas\b.*?(\d+)\s+nays\b", re.I),
    # "Yeas 39 to Nays 0" / "Yeas 39 to Nay 0" / "Yeas 39 to Yeas 0".
    re.compile(r"\byeas?\s+(\d+)\s+to\s+(?:nays?|yeas?)\s+(\d+)", re.I),
)

# A quorum roll call establishes that enough members are present. It is not a
# vote on the bill, and the two in MA 194th ("Quorum Roll Call - 149 YEAS to 0
# NAYS (See YEA and NAY No. 249 )") are House counts that were minting Senate
# vote events -- they are the 2 remaining Senate events whose source URL points
# at a *House* roll-call PDF.
_QUORUM_RE = re.compile(r"Quorum\s+Roll\s+Call", re.I)


def parse_senate_tally(action_name):
    """Return (yes, no) from a Senate roll-call action, or None if absent.

    OPEN-177: accepts every spelling of the nay count Massachusetts actually
    uses, not just "nays". See `_SENATE_TALLY_RES`.
    """
    for pattern in _SENATE_TALLY_RES:
        match = pattern.search(action_name or "")
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def senate_rollcall_url(action_name, session):
    """Return the Senate roll-call PDF URL an action cites, or None.

    OPEN-176: built from the roll-call number in the action's own text rather
    than from whichever link happens to sit first in the action cell.
    """
    match = _ROLLCALL_NUMBER_RE.search(action_name or "")
    if not match:
        return None
    return _SENATE_ROLLCALL_URL.format(re.sub(r"\D+$", "", session), match.group(1))


class MABillScraper(Scraper):
    verify = False

    categorizer = Categorizer()
    session_filters = {}
    chamber_filters = {}
    house_pdf_cache = {}

    bill_list = []

    chamber_map = {"lower": "House", "upper": "Senate"}
    chamber_map_reverse = {
        "House": "lower",
        "Senate": "upper",
        "Executive": "executive",
        "Joint": "legislature",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # forcing these values so that 500s come back as skipped bills
        self.raise_errors = False
        self.verify = False
        self.retry_attempts = 0

    def format_bill_number(self, raw):
        return raw.replace("Bill ", "").replace(".", " ").strip()

    def get_refiners(self, page, refinerName):
        # Get the possible values for each category of refiners,
        # e.g. House, Senate for lawsbranchname (Branch)
        filters = page.xpath(
            "//div[@data-refinername='{}']/div/label".format(refinerName)
        )

        refiner_list = {}
        for refiner_filter in filters:
            label = re.sub(r"\([^)]*\)", "", refiner_filter.xpath("text()")[1]).strip()
            refiner = refiner_filter.xpath("input/@data-refinertoken")[0].replace(
                '"', ""
            )
            refiner_list[label] = refiner
        return refiner_list

    # bill_no can be set to a specific bill (no spaces) to scrape only one
    # os-update ma bills --scrape bill_no=H2
    # we can also scrape a "chunk" of all available bills by specifying an integer 1-12 (inclusive)
    # chunks are available to split up this long, slow scrape into 12 smaller scrapes
    # os-update ma bills --scrape scrape_chunk_number=1
    # this trades off comprehensivity for limited scope of failure/faster time to recovery
    def scrape(
        self,
        chamber=None,
        session=None,
        bill_no=None,
        scrape_chunk_number=None,
        start=None,
    ):
        self.scrape_bill_list(session, start=start)

        # optionally scrape a single bill then exit
        if bill_no:
            single_bill_chamber = "lower" if "H" in bill_no else "upper"
            for bill_meta in self.bill_list:
                if bill_no in [bill_meta["DocketNumber"], bill_meta["BillNumber"]]:
                    yield from self.scrape_bill(session, bill_meta, single_bill_chamber)
                    self.info("Finished individual bill scrape, exiting.")
                    return

        if not chamber:
            yield from self.scrape_chamber("lower", session, scrape_chunk_number)
            yield from self.scrape_chamber("upper", session, scrape_chunk_number)
        else:
            yield from self.scrape_chamber(chamber, session, scrape_chunk_number)

    def scrape_bill_list(self, session, start=None):
        session_numeric = re.sub(r"[^0-9]", "", session)
        # note -- this returns XML to a browser, but json to curl/python
        api_url = (
            f"https://malegislature.gov/api/GeneralCourts/{session_numeric}/Documents"
        )

        # OPEN-128: `start` is accepted (ddp-sync passes it on every incremental run) and
        # deliberately NOT used to filter. It used to gate on the newest sponsor ResponseDate,
        # which is wrong in a way that loses data silently: sponsorship is set at filing and a
        # later action never touches it, so a bill that passed a chamber, was amended, or became
        # a Public Act kept its original sponsor date, failed the filter, and was skipped every
        # run. Its actions then went stale indefinitely. Measured against the production
        # database, 8,098 of 11,289 MA bills (71%) have activity after their first action, i.e.
        # activity the sponsor date structurally cannot reflect -- on the order of 80-100 bills
        # a week.
        #
        # There is no cheaper signal to swap in, and this was checked rather than assumed:
        #   * The list endpoint used here carries nine fields per bill and no date of any
        #     activity -- the sponsor ResponseDate is the only date in the payload, which is
        #     presumably why it was reached for (OPEN-133 enumerated this).
        #   * malegislature.gov exposes no dated "recently acted on" surface. Michigan's
        #     equivalent bug (OPEN-134) was fixable cheaply because MI's search results page
        #     prints each bill's last action; MA's /Bills/Search is a keyword search that
        #     returns nothing for empty terms and never lists last actions, so the same trick
        #     does not transfer.
        #   * Bill pages send `Cache-Control: no-cache, no-store` and neither ETag nor
        #     Last-Modified, so conditional requests cannot make a walk cheap either.
        #
        # So the honest options were to accept the staleness or to stop filtering, and this
        # takes the second. Cost, measured from a real full walk in the logs rather than
        # estimated: 11,465 requests in 341 minutes, ~1.01 requests per bill. That is bounded by
        # malegislature.gov's own ~2s response time, NOT by our rate limit -- probing 30 real
        # bill pages paced at 3/sec still only sustained 0.4/sec, all 200s. Raising
        # SCRAPELIB_RPM would therefore buy nothing.
        #
        # If ~6h per run proves too long, the lever already exists and needs no new code:
        # scrape()'s `scrape_chunk_number` splits the corpus into 12 chunks, so a caller can
        # cover everything across several shorter runs instead of one long one.
        if start:
            self.info(
                "MA OPEN-128: ignoring start= and listing every bill. The sponsor ResponseDate "
                "this used to filter on does not move when a bill acts, so filtering on it "
                "silently skipped ~80-100 bills a week. See scrape_bill_list() for why no "
                "cheaper signal exists."
            )

        list_data = self.get(api_url, verify=False).content
        for row in json.loads(list_data):
            chambers = ["H", "S"]

            # bill never flips from house to senate from docket -> intro so we're safe here
            # BillNumber can be set, but mapped to None, so use or here
            bill_id = row["BillNumber"] or row["DocketNumber"]
            # make sure the bill has an H or an S in the code
            if not any([chamber in bill_id for chamber in chambers]):
                self.error(
                    f"Unknown bill type - bill {row['BillNumber']} - docket {row['DocketNumber']}"
                )

            self.bill_list.append(
                {"BillNumber": row["BillNumber"], "DocketNumber": row["DocketNumber"]}
            )

    def scrape_chamber(self, chamber, session, scrape_chunk_number):
        chamber_code = "H" if chamber == "lower" else "S"
        chamber_bill_list = []
        for bill_meta in self.bill_list:
            bill_id = bill_meta["BillNumber"] or bill_meta["DocketNumber"]
            if chamber_code in bill_id:
                chamber_bill_list.append(bill_meta)

        # if scrape_chunk_number is specified, we are being asked to scrape
        # only a specific chunk of the total bills in this chamber
        # let's use 1-based counting so we're not doing scrape_chunk_number=0
        if scrape_chunk_number:
            # divide up the chamber_bill_list into 12 equal-sized lists
            chunk_size = (
                len(chamber_bill_list) // 12 if len(chamber_bill_list) >= 12 else 1
            )
            if len(chamber_bill_list) % 12 > 0:
                chunk_size += 1
            bill_chunks = [
                chamber_bill_list[i : i + chunk_size]
                for i in range(0, len(chamber_bill_list), chunk_size)
            ]
            chunk_number = int(scrape_chunk_number)

            chamber_bill_list = bill_chunks[chunk_number - 1]

        for chamber_bill_meta in chamber_bill_list:
            yield from self.scrape_bill(session, chamber_bill_meta, chamber)

    def scrape_bill(self, session, bill_meta, chamber):
        # https://malegislature.gov/Bills/189/SD2739
        bill_id = bill_meta["BillNumber"] or bill_meta["DocketNumber"]

        session_for_url = self.replace_non_digits(session)
        bill_url = "https://malegislature.gov/Bills/{}/{}".format(
            session_for_url, bill_id
        )

        try:
            response = self.get(bill_url, verify=False)
            self.info("GET (with `requests`) - {}".format(bill_url))
        except requests.exceptions.RequestException:
            self.warning("Server Error on {}".format(bill_url))
            return False

        html = response.text

        page = lxml.html.fromstring(html)

        if not page.xpath('//div[contains(@class, "followable")]/h1/text()'):
            self.warning("Server Error on {}".format(bill_url))
            return False

        # The state website will periodically miss a few bills' titles for a few days
        # These titles will be extant on the bill list page, but missing on the bill detail page
        # The titles are eventually populated under one of two markups
        try:
            bill_title = page.xpath('//div[@id="contentContainer"]/div/div/h2/text()')[
                0
            ]
        except IndexError:
            bill_title = None
            pass

        if bill_title is None:
            try:
                bill_title = page.xpath(
                    '//div[contains(@class,"followable")]/h1/text()'
                )[0]
                bill_title = bill_title.replace("Bill", "").strip()
            except IndexError:
                self.warning("Couldn't find title for {}; skipping".format(bill_id))
                return False

        bill_types = ["H", "HD", "S", "SD", "SRes"]
        if re.sub("[0-9]", "", bill_id) not in bill_types:
            self.warning("Unsupported bill type for {}; skipping".format(bill_id))
            return False
        classification = "proposed bill" if "D" in bill_id else "bill"

        if "SRes" in bill_id:
            bill_id = bill_id.replace("SRes", "SR")

        bill = Bill(
            bill_id,
            legislative_session=session,
            chamber=chamber,
            title=bill_title,
            classification=classification,
        )

        bill_summary = None
        if page.xpath('//p[@id="pinslip"]/text()'):
            bill_summary = page.xpath('//p[@id="pinslip"]/text()')[0].strip()
        if bill_summary and bill_summary != "":
            bill.add_abstract(bill_summary, "summary")

        if bill_meta["BillNumber"] and bill_meta["DocketNumber"]:
            bill.add_related_bill(
                bill_meta["DocketNumber"],
                legislative_session=session,
                relation_type="replaces",
            )

        bill.add_source(bill_url)

        # https://malegislature.gov/Bills/189/SD2739 has a presenter
        # https://malegislature.gov/Bills/189/S2168 no sponsor
        # Find the non-blank text of the dt following Sponsor or Presenter,
        # including any child link text.
        sponsor = page.xpath(
            '//dt[text()="Sponsor:" or text()="Presenter:"]/'
            "following-sibling::dd/descendant-or-self::*/text()[normalize-space()]"
        )
        # Sponsors always have link that follows pattern <a href="/Legislators/Profile/JNR1/193">Jeffrey N. Roy</a>
        # If this is a person i.e. "legislators" it will show in sponsor_href.
        sponsor_href = page.xpath(
            '//dt[text()="Sponsor:" or text()="Presenter:"]/following-sibling::dd//a/@href'
        )
        sponsor_href = sponsor_href[0] if sponsor_href else ""
        entity_type = (
            "person" if "legislators/" in sponsor_href.lower() else "organization"
        )

        if sponsor:
            sponsor = (
                sponsor[0]
                .replace("*", "")
                .replace("%", "")
                .replace("This sponsor is an original petitioner.", "")
                .strip()
            )
            bill.add_sponsorship(
                sponsor, classification="primary", primary=True, entity_type=entity_type
            )

        self.scrape_cosponsors(bill, bill_url)

        version = page.xpath(
            "//div[contains(@class, 'modalBtnGroup')]/"
            "a[contains(text(), 'Download PDF') and not(@disabled)]/@href"
        )
        if version:
            version_url = "https://malegislature.gov{}".format(version[0])
            bill.add_version_link(
                "Bill Text", version_url, media_type="application/pdf"
            )

        yield from self.scrape_actions(bill, bill_url, session)
        yield bill

    def scrape_cosponsors(self, bill, bill_url):
        # https://malegislature.gov/Bills/189/S1194/CoSponsor
        cosponsor_url = "{}/CoSponsor".format(bill_url)
        response = self.get_as_ajax(cosponsor_url)
        if response is None:
            self.warning("Skipping cosponsors for {} -- fetch failed".format(bill_url))
            return
        page = lxml.html.fromstring(response.text)
        cosponsor_rows = page.xpath("//tbody/tr")
        for row in cosponsor_rows:
            # careful, not everyone is a linked representative
            # https://malegislature.gov/Bills/189/S740/CoSponsor
            cosponsor_name = row.xpath("string(td[1])").strip()
            # cosponsor_district = ''
            # # if row.xpath('td[2]/text()'):
            #     cosponsor_district = row.xpath('td[2]/text()')[0]

            # Filter the sponsor out of the petitioners list
            if not any(
                sponsor["name"] == cosponsor_name for sponsor in bill.sponsorships
            ):
                cosponsor_name = (
                    cosponsor_name.replace("*", "")
                    .replace("%", "")
                    .replace("This sponsor is an original petitioner.", "")
                    .strip()
                )
                bill.add_sponsorship(
                    cosponsor_name,
                    classification="cosponsor",
                    primary=False,
                    entity_type="person",
                    # district=cosponsor_district
                )

    def scrape_actions(self, bill, bill_url, session):
        # scrape_action_page adds the actions, and also returns the Page xpath object
        # so that we can check for a paginator
        page = self.get_action_page(bill_url, 1)
        if page is None:
            self.warning("Skipping actions for {} -- fetch failed".format(bill_url))
            return
        yield from self.scrape_action_page(bill, page)

        max_page = page.xpath(
            '//ul[contains(@class,"pagination-sm")]/li[last()]/a/@onclick'
        )
        if max_page:
            max_page = re.sub(r"[^\d]", "", max_page[0]).strip()
            for counter in range(2, int(max_page) + 1):
                page = self.get_action_page(bill_url, counter)
                if page is None:
                    self.warning(
                        "Skipping action page {} for {} -- fetch failed".format(
                            counter, bill_url
                        )
                    )
                    continue
                yield from self.scrape_action_page(bill, page)
                # https://malegislature.gov/Bills/189/S3/BillHistory?pageNumber=2

    def get_action_page(self, bill_url, page_number):
        actions_url = "{}/BillHistory?pageNumber={}".format(bill_url, page_number)
        response = self.get_as_ajax(actions_url)
        if response is None:
            return None
        return lxml.html.fromstring(response.text)

    def scrape_action_page(self, bill, page):
        action_rows = page.xpath("//tbody/tr")
        for row in action_rows:
            if len(row.xpath("td[1]/text()")) == 0:
                continue
            action_date = row.xpath("td[1]/text()")[0]
            action_date = datetime.strptime(action_date, "%m/%d/%Y")
            action_year = action_date.year
            action_date = action_date.strftime("%Y-%m-%d")

            if row.xpath("td[2]/text()"):
                action_actor = row.xpath("td[2]/text()")[0]
                action_actor = self.chamber_map_reverse[action_actor.strip()]

            action_name = row.xpath("string(td[3])")

            # The action-history table's own hrefs carry two independent signals:
            # OPEN-37's enacted Chapter-of-the-Acts link (captured as a second,
            # distinctly-noted bill version so OPEN-34's diff pipeline can diff
            # introduced text against enacted text), and OPEN-36/OPEN-69 Tier 2's
            # cross-references to a different bill number that is a committee-
            # substitute/amendment/conference-report stage of this bill (captured
            # as a related_bill edge, not a version -- see
            # notes/ma-open-69-stage-chain-design-*.md for why).
            for href in row.xpath("td[3]//a/@href"):
                chapter_match = re.search(
                    r"^/Laws/SessionLaws/Acts/(\d{4})/Chapter(\d+)$", href
                )
                if chapter_match:
                    bill.add_version_link(
                        "Chapter Law Text (Enacted)",
                        "https://malegislature.gov{}".format(href),
                        media_type="text/html",
                    )
                    continue

                bill_ref_match = re.match(r"^/Bills/\d+/([A-Za-z]+\d+)/?$", href)
                if bill_ref_match:
                    # relation_type="related" (not "replaces"/"replaced-by"):
                    # OPEN-36 found these cross-references form a directed
                    # stage chain, not a clean linear supersession, and
                    # picking a direction here would presuppose the
                    # canonical-bill answer OPEN-69 explicitly defers (see
                    # notes/ma-open-69-stage-chain-design-*.md).
                    ref_bill_id = fix_bill_id(bill_ref_match.group(1))
                    if ref_bill_id == fix_bill_id(bill.identifier):
                        continue
                    already_related = any(
                        rb["identifier"] == ref_bill_id
                        and rb["relation_type"] == "related"
                        for rb in bill.related_bills
                    )
                    if not already_related:
                        bill.add_related_bill(
                            bill_ref_match.group(1),
                            legislative_session=bill.legislative_session,
                            relation_type="related",
                        )

            # House votes
            #
            # OPEN-169: the trigger used to be `"Supplement" in action_name` alone, and
            # that string does not appear in Massachusetts action text any more. Across
            # the 24 bills that failed the MA 194th coverage comparison, "Supplement"
            # occurs ZERO times while "YEA and NAY" occurs 57 -- so every House roll call
            # was skipped before a single request was made. Not a fetch failure and not a
            # parse failure: the scraper never tried. The Senate branch below matched
            # reality ("Roll Call", 41 occurrences), which is why MA had Senate votes and
            # no House votes at all rather than an obvious total blank.
            #
            # Everything downstream already expects this format. scrape_house_vote()
            # splits the roll-call PDF on "No. " + <number>, which is exactly how
            # "(See YEA and NAY No. 62 )" numbers itself, and the motion/YEAS/NAYS
            # regexes below parse the modern text unchanged. Only the gate was stale.
            #
            # "Supplement" is kept in the condition rather than replaced: older sessions
            # may still use it, and dropping it would trade this bug for its mirror image.
            if "Supplement" in action_name or re.search(
                r"YEA and NAY", action_name, re.IGNORECASE
            ):
                actor = "lower"

                if not re.findall(r"(.+)-\s*\d+\s*YEAS", action_name):
                    self.warning(
                        "vote {} did not match regex, skipping".format(action_name)
                    )
                    continue

                vote_action = re.findall(r"(.+)-\s*\d+\s*YEAS", action_name)[0].strip()

                y = int(re.findall(r"(\d+)\s*YEAS", action_name)[0])
                n = int(re.findall(r"(\d+)\s*NAYS", action_name)[0])

                # get supplement number
                n_supplement = int(
                    re.findall(r"No\.\s*(\d+)", action_name, re.IGNORECASE)[0]
                )
                cached_vote = VoteEvent(
                    chamber=actor,
                    start_date=action_date,
                    motion_text=vote_action,
                    result="pass" if y > n else "fail",
                    classification=classify_motion("ma", vote_action),
                    bill=bill,
                )
                cached_vote.set_count("yes", y)
                cached_vote.set_count("no", n)

                # OPEN-169: the session goes into this URL WITHOUT its ordinal suffix.
                # `bill.legislative_session` is "194th" and produced
                # .../Journal/House/194th/2025/RollCalls, which is a 404. The site
                # wants .../Journal/House/194/2025/RollCalls, which returns the real
                # ~740KB year-aggregate PDF.
                #
                # The 404 was silent and that is the reason it survived: urlretrieve
                # saved the 404 HTML error page, convert_pdf turned it into junk text,
                # the "No. <n>" lookup in scrape_house_vote() missed, and that path
                # `return`s (not `return False`) -- so the caller treated it as success
                # and yielded a vote event with correct counts and ZERO voters. Tallies
                # looked right while every individual House vote was quietly dropped.
                housevote_pdf = (
                    "https://malegislature.gov/Journal/House/{}/{}/RollCalls".format(
                        re.sub(r"\D+$", "", bill.legislative_session), action_year
                    )
                )
                # OPEN-176: same rule as the Senate branch below -- the tally is
                # real, so record the vote either way and label it when the roll
                # call could not be read.
                #
                # The 34 House events that imported tally-only in MA 194th are all
                # 2026 supplements #237-#270, while every supplement up to #235
                # resolved. The year-aggregate journal PDF simply had not been
                # republished with the July sittings yet, so this is a source-side
                # lag rather than a parse failure: the same bills will fill in on a
                # later run, and until they do the gap is now visible instead of
                # looking like a complete vote.
                if not self.scrape_house_vote(cached_vote, housevote_pdf, n_supplement):
                    self.warning(
                        "MA House roll call unreadable for {} supplement #{}: {} -- "
                        "recording the tally with voters_unavailable".format(
                            bill.identifier, n_supplement, housevote_pdf
                        )
                    )
                    cached_vote.extras[
                        "voters_unavailable"
                    ] = "house-rollcall-unreadable"

                cached_vote.add_source(housevote_pdf)
                cached_vote.dedupe_key = "{}#{}".format(housevote_pdf, n_supplement)
                yield cached_vote

            # Senate votes
            #
            # OPEN-176: a quorum roll call is not a vote on the bill. The two in
            # MA 194th are House counts, and they were minting Senate vote events
            # pointed at a House roll-call PDF -- 2 of the 118 Senate events that
            # imported a tally with nobody in it.
            if "Roll Call" in action_name and not _QUORUM_RE.search(action_name):
                actor = "upper"
                # placeholder
                vote_action = action_name.split(" -")[0]
                # 2019 H86 Breaks our regex,
                # Ordered to a third reading --
                # see Senate   Roll Call #25 and House Roll Call 56
                tally = parse_senate_tally(action_name)
                if tally is not None:
                    y, n = tally

                    # TODO: other count isn't included, set later
                    cached_vote = VoteEvent(
                        chamber=actor,
                        start_date=action_date,
                        motion_text=vote_action,
                        result="pass" if y > n else "fail",
                        classification=classify_motion("ma", vote_action),
                        bill=bill,
                    )
                    cached_vote.set_count("yes", y)
                    cached_vote.set_count("no", n)

                    # OPEN-176: derive the roll-call PDF from the number this
                    # action cites, not from the first link in the cell.
                    rollcall_pdf = senate_rollcall_url(
                        action_name, bill.legislative_session
                    )
                    read_voters = False
                    if rollcall_pdf:
                        read_voters = self.scrape_senate_vote(cached_vote, rollcall_pdf)

                    # OPEN-176/OPEN-177: the tally came from the action text and
                    # is real whatever the PDF does. Record the vote either way,
                    # and say plainly when nobody could be read from it.
                    #
                    # Dropping it instead -- which is what this branch used to do
                    # on a fetch failure -- is how OPEN-177's H 4530 and S 2903
                    # ended up citing a Senate roll call while holding no Senate
                    # vote at all: SenateRollCall70.pdf and SenateRollCall128.pdf
                    # both failed to fetch during the 2026-08-12 run, and each
                    # took its whole vote with it. A silent absence is worse than
                    # a labelled gap, because only the labelled one can be found
                    # again.
                    if not read_voters:
                        self.warning(
                            "MA Senate roll call unreadable for {} on {}: {} -- "
                            "recording the tally with voters_unavailable".format(
                                bill.identifier,
                                action_date,
                                rollcall_pdf or "no roll-call number in action text",
                            )
                        )
                        cached_vote.extras[
                            "voters_unavailable"
                        ] = "senate-rollcall-unreadable"

                    # A VoteEvent needs a source. When the action cites no
                    # roll-call number there is no roll-call URL to give it, so
                    # fall back to the bill's own page -- which is where the
                    # claim actually came from.
                    fallback_source = (
                        bill.sources[0]["url"]
                        if bill.sources
                        else "https://malegislature.gov"
                    )
                    cached_vote.add_source(rollcall_pdf or fallback_source)
                    cached_vote.dedupe_key = rollcall_pdf or "{}#senate-{}-{}".format(
                        fallback_source, action_date, y
                    )
                    yield cached_vote

            attrs = self.categorizer.categorize(action_name)
            action = bill.add_action(
                action_name.strip(),
                action_date,
                chamber=action_actor,
                classification=attrs["classification"],
            )
            for com in attrs.get("committees", []):
                com = com.strip()
                action.add_related_entity(com, entity_type="organization")

    def get_house_pdf(self, vurl):
        """cache house PDFs since they are done by year"""
        if vurl not in self.house_pdf_cache:
            try:
                (path, resp) = self.urlretrieve(vurl)
            except requests.exceptions.RequestException:
                self.warning("Server Error on {}".format(vurl))
                return None
            pdflines = convert_pdf(path, "text")
            os.remove(path)
            self.house_pdf_cache[vurl] = pdflines.decode("utf-8").replace("\u2019", "'")
        return self.house_pdf_cache[vurl]

    def scrape_house_vote(self, vote, vurl, supplement):
        """Attach individual House voters to `vote`.

        OPEN-176: returns True only when at least one voter was actually
        attached. Every failure path now returns False.

        This used to be three different answers to one question. A failed fetch
        returned False, a missing supplement did a bare `return` (None), and a
        parse that read the PDF but produced no voters returned None as well --
        while the caller tested `is False`. So two of the three failures were
        indistinguishable from success, and yielded a vote event carrying the
        action's tally and an empty voter list. That is the mechanism behind
        every one of the 152 tally-only Massachusetts roll calls, and it is why
        they accumulated with nothing flagging them.
        """
        pdflines = self.get_house_pdf(vurl)
        if pdflines is None:
            return False
        # get pdf data from supplement number
        try:
            vote_text = pdflines.split("No. " + str(supplement))[1].split(
                "MASSACHUSETTS"
            )[0]
        except IndexError:
            self.info("No vote found in supplement for vote #%s" % supplement)
            return False

        # create list of independent items in vote_text
        rows = vote_text.splitlines()
        lines = []
        for row in rows:
            lines.extend(row.split("   "))

        # retrieving votes in columns
        vote_tally = []
        voters = []
        for line in lines:
            # removes whitespace and after-vote '*' tag
            line = line.strip().strip("*").strip()

            if "NAYS" in line or "YEAS" in line or "=" in line or "/" in line:
                continue
            elif line == "":
                continue
            elif line == "N":
                vote_tally.append("n")
            elif line == "Y":
                vote_tally.append("y")
            # Not Voting
            elif line == "X":
                vote_tally.append("x")
            # Present
            elif line == "P":
                vote_tally.append("p")
            else:
                voters.append(line)

        house_votes = list(zip(voters, vote_tally))
        # iterate list and add individual names to vote.yes, vote.no
        for tup1 in house_votes:
            if tup1[1] == "y":
                vote.yes(tup1[0])
            elif tup1[1] == "n":
                vote.no(tup1[0])
            else:
                vote.vote("other", tup1[0])

        # OPEN-176: a PDF that read cleanly but named nobody is a failure, not a
        # unanimous silence.
        return bool(house_votes)

    def scrape_senate_vote(self, vote, vurl):
        """Attach individual Senate voters to `vote`.

        OPEN-176: returns True only when at least one voter was attached, for
        the same reason as `scrape_house_vote()` above.
        """
        # download file to server
        try:
            (path, resp) = self.urlretrieve(vurl)
        except requests.exceptions.RequestException:
            self.warning("Server Error on {}".format(vurl))
            return False
        pdflines = convert_pdf(path, "text")
        os.remove(path)

        # for y, n
        mode = None
        attached = 0

        lines = pdflines.splitlines()

        # handle individual lines in pdf to id legislator votes
        for line in lines:
            line = line.strip()
            line = line.decode("utf-8").replace("\u2212", "-")
            if line == "":
                continue
            # change mode accordingly
            elif line.startswith("YEAS"):
                mode = "y"
            elif line.startswith("NAYS"):
                mode = "n"
            elif line.startswith("ABSENT OR"):
                mode = "o"
            # else parse line with names
            else:
                nameline = line.split("   ")

                for raw_name in nameline:
                    raw_name = raw_name.strip()
                    if raw_name == "":
                        continue

                    # handles vote count lines
                    cut_name = raw_name.split("-")
                    clean_name = ""
                    if cut_name[-1].strip(" .").isdigit():
                        del cut_name[-1]
                        clean_name = "".join(cut_name)
                    else:
                        clean_name = raw_name.strip()
                    # update vote object with names
                    if mode == "y":
                        vote.yes(clean_name)
                        attached += 1
                    elif mode == "n":
                        vote.no(clean_name)
                        attached += 1
                    elif mode == "o":
                        vote.vote("other", clean_name)
                        attached += 1

        # OPEN-176: an HTML error page or an amendment modal converts to text
        # without raising, reaches this loop, and matches none of the YEAS/NAYS
        # section headers -- so `attached` stays 0 and the caller is told the
        # roll call could not be read, instead of being handed a vote with
        # nobody in it.
        return attached > 0

    def get_as_ajax(self, url):
        # set the X-Requested-With:XMLHttpRequest so the server only sends along the bits we want
        s = requests.Session()
        s.verify = False
        s.headers.update({"X-Requested-With": "XMLHttpRequest"})
        try:
            return s.get(url)
        except requests.exceptions.RequestException:
            self.warning("Server Error on {}".format(url))
            return None

    def replace_non_digits(self, str):
        return re.sub(r"[^\d]", "", str).strip()
