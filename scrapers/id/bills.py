from openstates.scrape import Scraper
from openstates.scrape import Bill, VoteEvent
import re
import datetime
import dateutil
from collections import defaultdict
import lxml.html
from .actions import Categorizer
from .voter_names import add_voter
from scrapelib import HTTPError
from classify_motion import classify_motion


BILLS_URL = "https://legislature.idaho.gov/sessioninfo/%s/legislation/minidata/"
BILL_URL = "https://legislature.idaho.gov/sessioninfo/%s/legislation/%s/"

_CHAMBERS = {"upper": "Senate", "lower": "House"}
_OTHER_CHAMBERS = {"upper": "lower", "lower": "upper"}
_CHAMBER_BY_NAME = {name: chamber for chamber, name in _CHAMBERS.items()}
# OPEN-770: the row that records a chamber receiving the bill from the other one
_ARRIVAL_RE = re.compile(r"(?:Received|Returned) from (?:the )?(House|Senate)\b")

_BILL_TYPES = {
    "CR": "concurrent resolution",
    "JM": "joint memorial",
    "JR": "joint resolution",
    "P": "proclamation",
    "R": "resolution",
}
_COMMITTEES = {
    "lower": {
        "Loc Gov": "Local Government",
        "Jud": "Judiciary, Rules and Administration",
        "Res/Con": "Resources and Conservation",
        "Com/HuRes": "Commerce and Human Resources",
        "Transp": "Transportation and Defense",
        "St Aff": "State Affairs",
        "Rev/Tax": "Revenues and Taxation",
        "Health/Wel": "Health and Welfare",
        "Env": "Environment, Energy and Technology",
        "Bus": "Business",
        "Educ": "Education",
        "Agric Aff": "Agricultural Affairs",
        "Approp": "Appropriations",
        "W/M": "Ways and Means",
    },
    "upper": {
        "Agric Aff": "Agricultural Affairs",
        "Com/HuRes": "Commerce and Human Resources",
        "Educ": "Education",
        "Fin": "Finance",
        "Health/Wel": "Health and Welfare",
        "Jud": "Judiciary and Rules",
        "Loc Gov": "Local Government and Taxation",
        "Res/Env": "Resources and Environment",
        "St Aff": "State Affairs",
        "Transp": "Transportation",
    },
}


def _motion_text(text):
    return (text or "").replace("\u00a0", " ").replace("-", "").strip()


def get_bill_type(bill_id):
    suffix = bill_id.split(" ")[0]
    if len(suffix) == 1:
        return "bill"
    else:
        return _BILL_TYPES[suffix[1:]]


class IDBillScraper(Scraper):
    categorizer = Categorizer()

    # the following are only used for parsing legislation from 2008 and earlier
    vote = None
    in_vote = False
    ayes = False
    nays = False
    other = False
    last_date = None

    def scrape_subjects(self, session):
        self._subjects = defaultdict(list)

        url = (
            "https://legislature.idaho.gov/sessioninfo" "/{}/legislation/topicind/"
        ).format(session)
        html = self.get(url).text
        doc = lxml.html.fromstring(html)

        # loop through anchors
        anchors = doc.xpath("//td//a")
        for a in anchors:
            # if anchor has a name, that's the subject
            if a.get("name"):
                subject = a.get("name")
            # if anchor is a link to a bill, save that reference
            elif "legislation" in a.get("href"):
                self._subjects[a.text].append(subject)

    def scrape(self, chamber=None, session=None):
        """
        Scrapes all the bills for a given session and chamber
        """
        # specials don't have subjects
        if "spcl" in session:
            self._subjects = defaultdict(list)
        else:
            try:
                self.scrape_subjects(session)
            except HTTPError:
                self.warning("Unable to load subjects.")
                self._subjects = defaultdict(list)

        # if you need to scrape a single bill
        # yield from self.scrape_bill("lower", "2026", "H 0978")
        # return

        chambers = [chamber] if chamber else ["upper", "lower"]
        for chamber in chambers:
            yield from self.scrape_bill_url(chamber, session)

    def scrape_bill_url(self, chamber, session):
        """scrapes legislation for 2009 and above"""
        url = BILLS_URL % session
        bill_index = self.get(url).text
        html = lxml.html.fromstring(bill_index)
        # I check for rows with an id that contains 'bill' and startswith
        # 'H' or 'S' to make sure I dont get any links from the menus
        # might not be necessary
        bill_rows = html.xpath(
            '//tr[contains(@id, "bill") and '
            'starts-with(descendant::td/a/text(), "%s")]' % _CHAMBERS[chamber][0]
        )
        for row in bill_rows:
            matches = re.match(r"([A-Z]*)([0-9]+)", row[0].text_content().strip())
            bill_id = " ".join(matches.groups()).strip()
            short_title = row[1].text_content().strip()
            yield from self.scrape_bill(chamber, session, bill_id, short_title)

    def scrape_bill(self, chamber, session, bill_id, short_title=None):
        """
        Scrapes documents, actions, vote counts and votes for
        bills from the 2009 session and above.
        """
        url = BILL_URL % (session, bill_id.replace(" ", ""))
        bill_page = self.get(url).text
        html = lxml.html.fromstring(bill_page)
        html.make_links_absolute(
            "https://legislature.idaho.gov/legislation/%s/" % session
        )
        bill_tables = html.xpath('//table[contains(@class, "bill-table")]')
        title = bill_tables[1].text_content().strip()
        bill_type = get_bill_type(bill_id)
        bill = Bill(
            legislative_session=session,
            chamber=chamber,
            identifier=bill_id,
            title=title,
            classification=bill_type,
        )
        bill.add_source(url)
        for subject in self._subjects[bill_id.replace(" ", "")]:
            bill.add_subject(subject)

        if short_title and title.lower() != short_title.lower():
            bill.add_title(short_title, "short title")

        # documents
        doc_links = html.xpath('//div[contains(@class,"insert-page")]//a')
        for link in doc_links:
            name = link.text_content().strip()
            href = link.get("href")
            if "Engrossment" in name or "Bill Text" in name or "Amendment" in name:
                bill.add_version_link(note=name, url=href, media_type="application/pdf")
            else:
                bill.add_document_link(
                    note=name, url=href, media_type="application/pdf"
                )

        def _split(string):
            return re.split(r"\w+[,|AND]\s+", string)

        # sponsors range from a committee to one legislator to a group of legs
        sponsor_lists = bill_tables[0].text_content().split("by")
        if len(sponsor_lists) > 1:
            # Adding chamber to further filter search results for committee
            # This is based on the assumption that a House Bill can only be sponsored by a House Committee and so on
            for sponsors in sponsor_lists[1:]:
                if "COMMITTEE" in sponsors.upper():
                    bill.add_sponsorship(
                        name=sponsors.strip(),
                        entity_type="organization",
                        primary=True,
                        classification="primary",
                        chamber=chamber,
                    )
                else:
                    for person in _split(sponsors):
                        person = person.strip()
                        if person != "":
                            bill.add_sponsorship(
                                classification="primary",
                                name=person,
                                entity_type="person",
                                primary=True,
                            )

        # OPEN-770: the chamber that has the bill, followed only from what the rows say (the rows naming a chamber,
        # the other chamber's arrival rows, the "to House"/"to Senate" moves); a committee report in the second
        # chamber no longer flips it (that put 2025 S 1180's House vote, 45-24-1, on the Senate)
        actor = chamber
        last_date = None
        # OPEN-682: the action row above a roll call, for a tally row printed without its own text
        previous_action = ""
        # OPEN-769: the roll-call rows already read on each day, for the votes' dedupe_keys
        roll_calls_by_day = defaultdict(list)
        # OPEN-770: each roll call's result ("pass"/"fail"), by day and roll call
        roll_call_results = {}
        for row in bill_tables[2]:
            # lots of empty rows
            if len(row) == 1:
                previous_action = ""
                continue
            _, date, action, _ = [x.text_content().strip() for x in row]

            if date:
                last_date = date
            else:
                date = last_date
            action_dt = datetime.datetime.strptime(
                date + "/" + session[0:4], "%m/%d/%Y"
            )
            date = action_dt.strftime("%Y-%m-%d")
            if action.startswith("House"):
                actor = "lower"
            elif action.startswith("Senate"):
                actor = "upper"
            # OPEN-770: the other chamber has the bill once the page says it received it ("Received from the House
            # passed", "Returned from Senate Failed")
            arrived_from = _ARRIVAL_RE.match(action.replace("\xa0", " "))
            if arrived_from:
                actor = _OTHER_CHAMBERS[_CHAMBER_BY_NAME[arrived_from.group(1)]]

            # votes
            is_vote = "AYES" in action or "NAYS" in action
            # OPEN-769: a bill page prints no roll-call number, so a roll call is known by its bill page (session,
            # bill), its day and its place among that day's roll calls on the page: the vote's dedupe_key. The
            # chamber is left out (it is worked out from the rows above). A row printed twice word for word on one
            # day, under the same motion, is one roll call and is kept once; a tally row with no text of its own
            # takes its motion from the row above (OPEN-682), so that row is part of what makes it the same.
            seen_today = roll_calls_by_day[date]
            roll_call = (
                action,
                _motion_text(row[2].text) or _motion_text(previous_action),
            )
            if is_vote and roll_call in seen_today:
                self.warning(f"Roll call printed twice on {date}: {url}")
            elif is_vote:
                seen_today.append(roll_call)
                for vote in self.parse_vote(
                    actor,
                    date,
                    row[2],
                    session,
                    bill_id,
                    chamber,
                    url,
                    previous_action,
                    dedupe_key=f"{url}#{date}-{len(seen_today)}",
                ):
                    roll_call_results[date, roll_call] = vote.result
                    yield vote
                # bill.add_vote_event(vote)
            # some td's text is separated by br elements
            if len(row[2]):
                action = "".join(row[2].itertext())
            action = action.replace("\xa0", " ").strip()
            previous_action = "" if is_vote else action
            attrs = self.categorizer.categorize(action)
            atype = attrs["classification"]

            bill.add_action(action, date, chamber=actor, classification=atype)
            # after voice vote/roll call and some actions the bill is sent
            # 'to House' or 'to Senate'
            # OPEN-770: but not on a failed roll call's "Ret'd to House": the Senate can still reconsider the bill
            # (2026 H 760, failed 03/24, re-voted 15-20-0 on 03/25, which was stored as a House vote); the House has
            # it from its "Returned from Senate Failed" row. A passed roll call's "Title apvd - to Senate" still
            # moves it: on a same-day passage the other chamber may print no "Received from" row (2025 H 480).
            if is_vote and roll_call_results.get((date, roll_call)) == "fail":
                pass
            elif "to House" in action:
                actor = "lower"
            elif "to Senate" in action:
                actor = "upper"

            if "Session Law" in action:
                law = re.search(
                    r"Session Law (.*) Effective: (.*)",
                    action,
                    flags=re.MULTILINE | re.IGNORECASE,
                )
                if law and law.groups(0) and law.groups(1):
                    bill_year = action_dt.strftime("%Y")
                    chapter = law.groups()[0].strip()
                    effective = law.groups()[1].strip()

                    try:
                        effective = dateutil.parser.parse(effective).date()
                        bill.add_citation(
                            f"Idaho Session Laws {bill_year}",
                            chapter,
                            "chapter",
                            effective=effective,
                        )
                    except ValueError:
                        bill.add_citation(
                            f"Idaho Session Laws {bill_year}",
                            chapter,
                            "chapter",
                        )
        yield bill

    def get_names(self, name_text, chamber):
        """both of these are unicode non-breaking spaces"""
        if name_text:
            name_text = name_text.replace("\xa0--\xa0", "")
            name_text = name_text.replace("\u00a0", " ")
            name_list = [
                name.replace("\u2013", "").strip()
                for name in name_text.split(",")
                if name
            ]
            # keep district numbers like "Crane(12)" that tell same-surname
            # members apart. OPEN-781: keep a Senate acting senator as printed,
            # "Acting(Senator)" ("Bjerke(Bjerke)", "Bjerke(Keyser)"): the bare
            # surname would match a sitting senator; the printed form matches
            # only the acting senator's dated other name in the people data.
            # Drop other parentheticals, like the House's "Hall(Stone)".
            name_list = [
                (
                    name
                    if re.search(r"\(\d+\)$", name)
                    else (
                        re.sub(r"\s+\(", "(", name)
                        if chamber == "upper" and re.search(r"\(\D+\)$", name)
                        else name.split("(")[0]
                    )
                )
                for name in name_list
            ]
            return name_list
        return []

    def parse_vote(
        self,
        actor,
        date,
        row,
        session,
        bill_id,
        bill_chamber,
        source,
        previous_action="",
        dedupe_key=None,
    ):
        """
        takes the actor, date and row element and returns a Vote object
        """
        spans = row.xpath(".//span")
        # OPEN-682: the motion is the text in front of the tally. A tally row printed without one
        # ("PASSED - 61-6-3", 2025 H 231) is the vote on the reading in the action row just above
        # it ("Rules Suspended: ..., read in full as required"), so that text is the motion; failing
        # that (a roll call right after another), the tally itself, which classifies as nothing.
        motion = _motion_text(row.text) or _motion_text(previous_action)
        motion = motion or spans[0].text_content().replace("\u00a0", " ").strip()
        passed, yes_count, no_count, other_count = (
            spans[0].text_content().rsplit("-", 3)
        )
        # find each list by its label; extra spans like "Tie vote - President
        # voted NAY" can appear before AYES
        yes_votes, no_votes, other_votes = [], [], []
        for span in spans[1:]:
            label = span.text_content()
            if label.startswith("AYES"):
                yes_votes = self.get_names(span.tail, actor)
            elif label.startswith("NAYS"):
                no_votes = self.get_names(span.tail, actor)
            elif label.startswith(("Absent", "Excused")):
                other_votes += self.get_names(span.tail, actor)
        for key, val in {"adopted": "pass", "passed": "pass", "failed": "fail"}.items():
            if key in passed.lower():
                passed = val
                break
        vote = VoteEvent(
            chamber=actor,
            start_date=date,
            motion_text=motion,
            bill=bill_id,
            bill_chamber=bill_chamber,
            result=passed,
            # OPEN-682: what the vote decides, from the id block of config/motion_classification.yaml
            classification=classify_motion("id", motion),
            legislative_session=session,
        )
        if dedupe_key:
            vote.dedupe_key = dedupe_key
        vote.add_source(source)
        vote.set_count("yes", int(yes_count))
        vote.set_count("no", int(no_count))
        vote.set_count("absent", int(other_count))
        for option, names in (
            ("yes", yes_votes),
            ("no", no_votes),
            ("absent", other_votes),
        ):
            for name in names:
                if name and name != "None":
                    add_voter(vote, option, name, actor, session)
        yield vote
