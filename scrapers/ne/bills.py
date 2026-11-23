import pytz
import re
import urllib
from datetime import datetime
import dateutil

from openstates.scrape import Scraper, Bill, VoteEvent

from classify_motion import classify_motion
from utils import LXMLMixin


TIMEZONE = pytz.timezone("US/Central")

# OPEN-504: the history row's text is the vote's outcome. Bills say "Passed on Final Reading"
# or "Advanced to E&R"; amendments and motions say "<sponsor> AM123 adopted" or
# "<sponsor> MO45 prevailed" (or "lost" / "failed"). "Returned to Select File for specific
# amendment" is a motion to return that carried (Ramon, 2026-11-07). A failure word wins.
VOTE_FAILED = re.compile(
    r"\bfail(ed|s)?\b|\blost\b|\bnot adopted\b|\bwithdrawn\b", re.I
)
VOTE_PASSED = re.compile(
    r"\b(passed|(re)?advanced|adopted|prevailed|returned to select file)\b", re.I
)


# BROKER-579: since 2026 an override roll call sits on its motion's row ("Cavanaugh, J. MO585 failed",
# LB 1256), and only the motion's filed row says what it is ("Cavanaugh, J. MO585 That LB1256 becomes law
# notwithstanding the objections of the Governor filed"; 2025: "Rountree MO259 That the bill becomes law ...").
# A whole-bill override only: a line-item one stays unlabelled.
OVERRIDE_MOTION = re.compile(
    r"\b(MO\d+)\s+That\b(?!.*\bline[- ]item).*\bbecomes? law notwithstanding the objections of the Governor\b",
    re.I,
)
VOTE_ON_MOTION = re.compile(r"\b(MO\d+)\s+(prevailed|failed|lost)\b", re.I)


def override_motions(history_texts):
    """The bill's motion numbers ("MO585") filed as a veto override."""
    return {
        m.group(1).upper()
        for m in (OVERRIDE_MOTION.search(text) for text in history_texts)
        if m
    }


def vote_passed(motion_text):
    if VOTE_FAILED.search(motion_text):
        return False
    return bool(VOTE_PASSED.search(motion_text))


# OPEN-794 (PLAN-companion-lineage §5.3.1, Ramon 2026-11-23 "Store all three"): Nebraska names another bill only in a
# history line like "Provisions/portions of LB890 amended into LB901 by AM2406" (also "LB77A ... by rules suspension"), on
# both bills' histories. A bill carried in another is not a companion (D2): stored as related, the label saying which way.
AMENDED_INTO = re.compile(
    r"Provisions/portions of (LB\s*\d+A?) amended into (LB\s*\d+A?)\b", re.I
)
CARRIED_LABEL = "amended into"  # on the bill whose provisions moved
CARRYING_LABEL = "provisions amended in"  # on the bill that took them in


def amended_into_links(bill_identifier, history_text):
    """[(other bill, label)] for one history line of `bill_identifier`: the bill it was amended into, or the bill whose
    provisions it took in. A line naming the same bill twice, or two other bills, gives none."""

    def key(identifier):
        return re.sub(r"\s+", "", identifier).upper()

    own = key(bill_identifier)
    links = []
    for m in AMENDED_INTO.finditer(history_text):
        carried, carrying = key(m.group(1)), key(m.group(2))
        if carried == carrying:
            continue
        if own == carried:
            links.append((carrying, CARRIED_LABEL))
        elif own == carrying:
            links.append((carried, CARRYING_LABEL))
    return links


def add_missing_reverse_links(bills):
    """OPEN-794 follow-up (Ramon, 2026-11-23: show a one-sided "amended into" line on both bills): when only one bill's
    history names a pair (LB 958 names LB 1033 as carried into it; LB 1033's own history doesn't), the other bill of the
    session gets the matching link too. `bills` is every Bill of one session's walk; a bill named but not among them is
    left alone."""

    def key(identifier):
        return re.sub(r"\s+", "", identifier).upper()

    reverse = {CARRIED_LABEL: CARRYING_LABEL, CARRYING_LABEL: CARRIED_LABEL}
    by_key = {key(bill.identifier): bill for bill in bills}
    added = 0
    for bill in bills:
        for link in list(bill.related_bills):
            label = link.get("ddp_relation_label")
            other = by_key.get(key(link["identifier"]))
            if label not in reverse or other is None or other is bill:
                continue
            want = (key(bill.identifier), reverse[label])
            if want not in {
                (key(r["identifier"]), r.get("ddp_relation_label"))
                for r in other.related_bills
            }:
                other.add_related_bill(
                    bill.identifier,
                    other.legislative_session,
                    "related",
                    label=reverse[label],
                )
                added += 1
    return added


class NEBillScraper(Scraper, LXMLMixin):
    priority_bills = {}
    # SSL bad as of 2024-11-18
    verify = False

    def scrape(self, session=None, start=None):
        # OPEN-500: the runners append start=<watermark> on every run after the first. NE has
        # no cheaper change signal, so accept it and ignore it: every run is a full walk (as MA
        # does, OPEN-128).
        if start:
            self.info("NE OPEN-500: ignoring start=%s and doing a full walk", start)

        if session is None:
            session = self.jurisdiction.legislative_sessions[-1]
            self.info("no session specified, using %s", session["identifier"])
        else:
            session = next(
                (
                    item
                    for item in self.jurisdiction.legislative_sessions
                    if item["identifier"] == session
                ),
                None,
            )

        yield from self.with_reverse_links(self.scrape_session(session))

    def scrape_session(self, session):
        if session["classification"] == "special":
            start = dateutil.parser.parse(session["start_date"])
            yield from self.scrape_special(session["identifier"], start)
        else:
            self.scrape_priorities()
            start_year = datetime.strptime(session["start_date"], "%Y-%m-%d").year
            end_year = datetime.strptime(session["end_date"], "%Y-%m-%d").year
            yield from self.scrape_year(session["identifier"], start_year)
            if start_year != end_year:
                yield from self.scrape_year(session["identifier"], end_year)

    def with_reverse_links(self, items):
        """OPEN-794 follow-up: the session's bills are held until the walk ends, so a pair named on only one bill's page can
        be added to the other bill too (add_missing_reverse_links). Votes go out as they come (a vote points at its bill
        by id, so the order of saving does not matter)."""
        bills = []
        try:
            for item in items:
                if isinstance(item, Bill):
                    bills.append(item)
                else:
                    yield item
        except Exception:
            # a walk that fails part way still hands over the bills it read (as before this step), without the reverse
            # links, so no vote is ever left without its bill in a partial output
            yield from bills
            raise
        added = add_missing_reverse_links(bills)
        if added:
            self.info(
                "OPEN-794: %d amended-into link(s) added to the other bill", added
            )
        yield from bills

    def scrape_priorities(self):
        priority_url = "https://nebraskalegislature.gov/session/priority.php"
        page = self.lxmlize(priority_url, verify=False)

        for row in page.xpath(
            "//table[@id='committee_bill_results' or @id='senator_bill_results' or @id='speaker_bill_results']/tr"
        ):
            bill_id = row.xpath("td[2]/a/text()")[0].strip()
            prioritizer = row.xpath("td[1]/text()")[0].strip()

            self.priority_bills[bill_id] = {
                "prioritizer": prioritizer,
            }

    # NE Specials are lumped in with regular data, just duped bill numbers.
    # Scrape by intro date, instead of by year.
    def scrape_special(self, session: str, start_date: datetime):
        main_url = (
            "https://nebraskalegislature.gov/bills/search_by_date.php?"
            "SessionDay={}&special=1".format(start_date.strftime("%Y"))
        )
        page = self.lxmlize(main_url, verify=False)

        document_links = self.get_nodes(
            page,
            '//div[@class="main-content"]//div[@class="table-responsive"]//'
            "table/tbody/tr/td[1]/a",
        )

        for document_link in document_links:
            # bill_number = document_link.text
            bill_link = document_link.attrib["href"]
            main_url = (
                "https://nebraskalegislature.gov/bills/search_by_date.php?"
                "SessionDay={}&special=1".format(start_date.strftime("%Y-%m-%d"))
            )
            yield from self.bill_info(bill_link, session, main_url)

    def scrape_year(self, session, year):

        main_url = (
            "https://nebraskalegislature.gov/bills/search_by_date.php?"
            "SessionDay={}".format(year)
        )
        page = self.lxmlize(main_url, verify=False)

        document_links = self.get_nodes(
            page,
            '//div[@class="main-content"]//div[contains(@class,"table-responsive")]//'
            'table[contains(@class,"table")]/tbody/tr/td[1]/a',
        )

        for document_link in document_links:
            # bill_number = document_link.text
            bill_link = document_link.attrib["href"]

            # POST request for search form
            # post_dict = {'DocumentNumber': bill_number, 'Legislature': session}
            # headers = urllib.urlencode(post_dict)
            # bill_resp = self.post('http://nebraskalegislature.gov/bills/'
            #     'search_by_number.php', data=post_dict)
            # bill_link = bill_resp.url
            # bill_page = bill_resp.text

            yield from self.bill_info(bill_link, session, main_url)

    def bill_info(self, bill_link, session, main_url):
        bill_page = self.lxmlize(bill_link, verify=False)

        long_title = self.get_node(
            bill_page, '//div[@class="main-content"]//h2'
        ).text.split()

        bill_number = long_title[0]
        title = ""
        for x in range(2, len(long_title)):
            title += long_title[x] + " "
        title = title[0:-1]

        if not title:
            self.error("no title, skipping %s", bill_number)
            return

        bill_type = "resolution" if "LR" in bill_number else "bill"

        bill = Bill(bill_number, session, title, classification=bill_type)

        bill.add_source(main_url)
        bill.add_source(bill_link)

        introduced_by = self.get_node(
            bill_page,
            "//body/div[3]/div[2]/div[2]/div/div[3]/div[1]/ul/li[1]/a[1]/text()",
        )

        if not introduced_by:
            introduced_by = self.get_node(
                bill_page,
                "//body/div[3]/div[2]/div[2]/div/div[2]/div[1]/ul/li[1]/text()",
            )
            introduced_by = introduced_by.split("Introduced By:")[1].strip()

        introduced_by = introduced_by.strip()
        entity_type = "person"
        if "committee" in introduced_by.lower():
            entity_type = "organization"
        bill.add_sponsorship(
            name=introduced_by,
            entity_type=entity_type,
            primary=True,
            classification="primary",
        )

        self.scrape_actions(bill, bill_page)

        # Grabs bill version documents.
        version_links = self.get_nodes(
            bill_page, "/html/body/div[3]/div[2]/div[2]/div/" "div[3]/div[2]/ul/li/a"
        )

        for version_link in version_links:
            version_name = version_link.text
            version_url = version_link.attrib["href"]
            # replace Current w/ session number
            version_url = version_url.replace("Current", session)
            bill.add_version_link(
                version_name, version_url, media_type="application/pdf"
            )

        soi = self.get_nodes(bill_page, ".//a[contains(text(), 'Statement of Intent')]")
        if soi:
            bill.add_document_link(
                "Statement of Intent", soi[0].get("href"), media_type="application/pdf"
            )
        comstmt = self.get_nodes(
            bill_page, ".//a[contains(text(), 'Committee Statement')]"
        )
        if comstmt:
            bill.add_document_link(
                "Committee Statement",
                comstmt[0].get("href"),
                media_type="application/pdf",
            )
        fn = self.get_nodes(bill_page, ".//a[contains(text(), 'Fiscal Note')]")
        if fn:
            bill.add_document_link(
                "Fiscal Note", fn[0].get("href"), media_type="application/pdf"
            )

        # Add amendments
        amendment_rows = self.get_nodes(
            bill_page,
            ".//div[contains(@class, 'amends') and .//a[contains(@href, '/AM/')]]",
        )

        for row in amendment_rows:
            if not row.xpath(".//p[contains(@class,'fw-bold')]"):
                continue
            status = (
                row.xpath(".//p[contains(@class,'fw-bold')]")[0].text_content().strip()
            )
            amendment_names = row.xpath(".//h6/a/text()")
            amendment_names = [name.strip() for name in amendment_names]
            amendment_name = " ".join(amendment_names)
            amendment_url = row.xpath(".//h6/a/@href")[0]
            # adopted amendments get added as versions, everything else goes into documents
            if "adopted" in status.lower():
                bill.add_version_link(
                    amendment_name, amendment_url, media_type="application/pdf"
                )
            else:
                amendment_name = f"{amendment_name} ({status})"
                bill.add_document_link(
                    amendment_name, amendment_url, media_type="application/pdf"
                )

        if bill_number in self.priority_bills:
            priority = self.priority_bills[bill_number]
            bill.extras["NE_PRIORITIZER"] = priority["prioritizer"]

        yield bill

        # Nebraska's one house casts every vote (this was the oldest action's actor, which on the
        # replica is "legislature" for every bill and all 1,772 votes)
        yield from self.scrape_votes(bill, bill_page, "legislature")

    def scrape_actions(self, bill, bill_page):
        action_nodes = self.get_nodes(
            bill_page, '//table[contains(@class,"history")]/tbody/tr'
        )

        # The site lists a bill's history newest first, a day's actions included; they are read
        # oldest first (a plain reverse, not a date sort), so a day ends on its last action and
        # that becomes the latest action (OPEN-535, as OPEN-528 for Alabama)
        for action_node in reversed(action_nodes):
            date = self.get_node(action_node, "./td[1]").text
            date = datetime.strptime(date, "%b %d, %Y")

            # The action node may have an anchor element within it, so
            # we grab all the text within.
            action = self.get_node(action_node, "./td[2]").text_content()

            # NE legislature site does not list cosponsors, so we grab it from action statements
            if "name added" in action:
                cosponsor_name = action.split("name added")[0].strip()
                entity_type = "person"
                if "committee" in cosponsor_name.lower():
                    entity_type = "organization"
                bill.add_sponsorship(
                    cosponsor_name,
                    entity_type=entity_type,
                    classification="cosponsor",
                    primary=False,
                )

            if "Governor" in action:
                actor = "executive"
            else:
                actor = "legislature"

            action_type = self.action_types(action)
            bill.add_action(
                action,
                date.strftime("%Y-%m-%d"),
                chamber=actor,
                classification=action_type,
            )

            # OPEN-794: a bill carried in another, or carrying one; each other bill once per bill
            for other, label in amended_into_links(bill.identifier, action):
                if other not in {
                    re.sub(r"\s+", "", r["identifier"]).upper()
                    for r in bill.related_bills
                    if r["ddp_relation_label"] == label
                }:
                    bill.add_related_bill(
                        other, bill.legislative_session, "related", label=label
                    )

            if "Notice of hearing for" in action:
                ref_date = action.replace("Notice of hearing for", "").strip()
                bill.extras["NE_REF_DATE"] = ref_date

            if "Referred to" in action:
                ref_com = action.split("Referred to")[1].strip()
                bill.extras["NE_REF_COM"] = ref_com

    def scrape_amendments(self, bill, bill_page):
        amd_xpath = '//div[contains(@class,"amends") and not(contains(@class,"mb-3"))]'
        for row in bill_page.xpath(amd_xpath):
            status = row.xpath("string(./div[2])").strip()
            if "adopted" in status.lower():
                version_url = row.xpath("./div[1]/a/@href")[0]
                version_name = row.xpath("./div[1]/a/text()")[0]
                bill.add_version_link(
                    version_name,
                    version_url,
                    media_type="application/pdf",
                    on_duplicate="ignore",
                )

    def scrape_votes(self, bill, bill_page, chamber):
        vote_links = bill_page.xpath(
            '//table[contains(@class,"history")]//a[contains(@href, "view_votes")]'
        )
        overrides = override_motions(
            tds[1].text_content()
            for tds in (
                row.xpath("./td")
                for row in bill_page.xpath('//table[contains(@class,"history")]//tr')
            )
            if len(tds) > 1
        )
        for vote_link in vote_links:
            vote_url = vote_link.attrib["href"]
            date_td, motion_td, *_ = vote_link.xpath("ancestor::tr/td")
            date = datetime.strptime(date_td.text, "%b %d, %Y")
            motion_text = motion_td.text_content()
            vote_page = self.lxmlize(vote_url, verify=False)
            passed = vote_passed(motion_text)

            vote = VoteEvent(
                bill=bill,
                chamber=chamber,
                start_date=TIMEZONE.localize(date),
                motion_text=motion_text,
                classification=(
                    ["passage"]
                    if (m := VOTE_ON_MOTION.search(motion_text))
                    and m.group(1).upper() in overrides
                    else classify_motion("ne", motion_text)
                ),
                result="pass" if passed else "fail",
            )

            yes_voters, yes_count = self.get_votes(vote_page, "Yes :")
            no_voters, no_count = self.get_votes(vote_page, "No :")
            exc_voters, exc_count = self.get_votes(vote_page, "Excused Not Voting:")
            abs_voters, absent_count = self.get_votes(vote_page, "Absent Not Voting:")
            pre_voters, present_count = self.get_votes(vote_page, "Present Not Voting:")

            vote.set_count("yes", yes_count)
            vote.set_count("no", no_count)
            vote.set_count("excused", exc_count)
            vote.set_count("absent", absent_count)
            vote.set_count("abstain", present_count)

            query_params = urllib.parse.parse_qs(urllib.parse.urlparse(vote_url).query)
            vote.dedupe_key = query_params["KeyID"][0]
            # OPEN-685: Nebraska gives a vote its day only, so two roll calls on a bill the same day
            # (LB 48, 2025-05-30: failed with the emergency clause, then passed with it stricken)
            # tie. The KeyID rises in the order the votes were taken (12956, then 12957); the broker
            # reads this key into Motion.rollcall_num to order them (as OPEN-628 did for MI and WA).
            vote.extras["legislature-rollcall-num"] = vote.dedupe_key
            vote.add_source(vote_url)

            for name in yes_voters:
                vote.yes(name)
            for name in no_voters:
                vote.no(name)
            for name in exc_voters:
                vote.vote("excused", name)
            for name in abs_voters:
                vote.vote("absent", name)
            for name in pre_voters:
                vote.vote("abstain", name)

            yield vote

    # Find the vote count row containing row_string, and return the integer count
    def get_votes(self, page, row_string):
        count_xpath = 'string(//div[@id="by_vote_viewport"]//div[contains(@class, "card-header")][contains(text(),"{}")])'
        count_text = page.xpath(count_xpath.format(row_string))
        value = "".join(x for x in count_text if x and x.isdigit())
        cells_xpath = (
            '//div[@id="by_vote_viewport"]//div[contains(@class, "card-header")][contains(text(),"{}")]'
            "/following-sibling::table//td/div/text()"
        )
        cells_xpath = page.xpath(cells_xpath.format(row_string))
        # OPEN-761: a trailing "*" ("Hansen*", "Cavanaugh, M.*") marks a senator who was Present Not
        # Voting when the vote was taken and had the vote recorded later (Rule 6, Sec. 9). The vote
        # counts as cast; the marker is not part of the name, and left on it the name matches no one.
        cells = [cell.strip().rstrip("*").rstrip() for cell in cells_xpath]
        cells = [cell for cell in cells if cell]

        return cells, int(value) if value else 0

    def action_types(self, action):
        if "Date of introduction" in action:
            action_type = "introduction"
        elif "Referred to" in action:
            action_type = "referral-committee"
        elif "Indefinitely postponed" in action:
            action_type = "committee-failure"
        elif "Placed on General File" in action:
            action_type = "committee-passage"
        elif ("File" in action) or ("filed" in action):
            action_type = "filing"
        elif "Placed on Final Reading" in action:
            action_type = "reading-3"
        elif "Passed" in action or "President/Speaker signed" in action:
            action_type = "passage"
        elif "Presented to Governor" in action:
            action_type = "executive-receipt"
        elif "Approved by Governor" in action:
            action_type = "executive-signature"
        elif "Failed to pass notwithstanding the objections of the Governor" in action:
            action_type = "executive-veto"
        elif "Failed" in action:
            action_type = "failure"
        elif "Bill withdrawn" in action:
            action_type = "withdrawal"
        elif "Became law without Governor's signature" in action:
            action_type = "became-law"
        else:
            action_type = None
        return action_type
