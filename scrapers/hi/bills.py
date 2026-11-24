import datetime as dt
import logging
import lxml.html
import re
from openstates.exceptions import EmptyScrape
from openstates.scrape import Scraper, Bill, VoteEvent
from .actions import Categorizer, find_committee
from .members import load_members
from .sessions import (
    CARRIED_INTO,
    belongs_to_earlier_year,
    is_special,
    scraped_name,
    special_session_on,
)
from .utils import get_short_codes, make_data_url
from . import special_measures
from classify_motion import classify_motion
from urllib import parse as urlparse
import dateutil
import pytz

HI_URL_BASE = "https://www.capitol.hawaii.gov"
SHORT_CODES = f"{HI_URL_BASE}/legislature/committees.aspx?chamber=all"
# Set this flag to true to run scrape for just one bill
TEST_SINGLE_BILL = False
TEST_SINGLE_BILL_NUMBER = "572"  # set to bill num you want to test
repeated_action = ["Excused: none", "Representative(s) Eli"]

vote_re_list = [
    # OPEN-825: the Senate floor tally, which prints an aye count and names only the exceptions:
    # "Ayes, 21; Aye(s) with reservations: Senator(s) Chang .  Noes, 2 (Senator(s) Awa, Lee, C.).
    # Excused, 2 (Senator(s) Gabbard, Kouchi)." ("Ayes, 18." on a nomination). Tried first: the
    # second pattern below ends a "(Senator(s) ...)" list at the "(s)" and the fourth keeps no
    # names for the noes, so those names were lost. Same counts as those patterns read.
    r"""
    Ayes,\s(?P<n_yes>\d+)[.;]\s*
    Aye\(s\)\swith\sreservations:\s*(?P<yes_resv>none|Senator\(s\)[^()]*?)\s*\.\s+
    Noes,\s(?P<n_no>\d+)\s\((?P<no>none|Senator\(s\)[^()]*)\)\.\s+
    Excused,\s(?P<n_excused>\d+)\s\((?P<excused>none|Senator\(s\)[^()]*)\)
""",
    r"""
        (?P<n_yes>\d+)\sAye\(?s\)?  # Yes vote count
        (:\s+(?P<yes>.*?))?;\s+  # Yes members
        Aye\(?s\)?\swith\sreservations:\s+(?P<yes_resv>.*?);?
        (?P<n_no>\d*)\sNo\(?es\)?:\s+(?P<no>.*?);?
        (\s+and\s+)?
        (?P<n_excused>\d*)\sExcused:\s(?P<excused>.*)\.?
        """,
    r"""
        Ayes,?\s(?P<n_yes>\d+)  # Capture number of Ayes
        (?:;\s*(?P<yes>[^.;]*))?  # Capture Yes members if present
        [.;]?\s*Aye\(s\)?\swith\sreservations:?\s(?P<yes_resv>[^.;]*)?  # Capture Ayes with reservations
        [.;]?\s*Noes?,?\s(?P<n_no>\d+)  # Capture number of Noes
        (?:\s?\((?P<no>[^)]*)\))?  # Optional: Noes details in parentheses
        [.;]?\s*Excused,?\s(?P<n_excused>\d+)  # Capture number of Excused
        (?:\s?\((?P<excused>[^)]*)\))?  # Optional: Excused details in parentheses
        [.;]?  # Optional end punctuation
        """,
    r"""
    (?P<n_yes>\d+)\sAyes?:\s(?:Representative|Senator)\(s\)\s(?P<yes>.*?);
    \s*Ayes?\swith\sreservations:\s+(?P<yes_resv>.*?);
    \s*(?P<n_no>\d*)\sNoes?:\s(?:Representative\(s\)|Senator\(s\)|)\s?(?P<no>.*?);?
    \s*and\s*(?P<n_excused>\d*)\sExcused:\s(?P<excused>.*)\.?
""",
    r"""
    Passed.*?Reading.*?  # Match "Passed...Reading" including amendments
    Ayes,?\s(?P<n_yes>\d+);?  # Capture Yes vote count
    \s*Aye\(s\)?\swith\sreservations:?\s(?P<yes_resv>[^.;]*)[.;]?  # Capture Yes with reservations
    \s*Noes?,?\s(?P<n_no>\d+)\s?\(?([^)]*)\).*\)?\.? # Capture No votes
    \s*Excused,?\s(?P<n_excused>\d+)\s?\(?(?P<excused>[^)]*)\)?\.?  # Capture Excused votes
""",
    # OPEN-709: Senate Final Reading, missed by every pattern above. Tried last, so a
    # text an earlier pattern reads is read exactly as before. "Ayes, 23; Aye(s) with
    # reservations: Senator(s) Chang . 2 No(es): Senator(s) Acasio, Fevella.  0 Excused: none."
    r"""
    Ayes,\s(?P<n_yes>\d+);\s*
    Aye\(s\)\swith\sreservations:\s*(?P<yes_resv>.*?)\s*\.\s+
    (?P<n_no>\d+)\sNo\(es\):\s*(?P<no>.*?)\.\s+
    (?P<n_excused>\d+)\sExcused:\s*(?P<excused>.*?)\.?\s*$
""",
    # OPEN-709: the forms below print no aye count (no n_yes group). Their ayes are worked out
    # from the members seated that day (hi/members.py). House floor: "... with Representative(s)
    # Kila voting aye with reservations; Representative(s) Alcos, Garcia voting no (2) and
    # none excused (0)."
    r"""
    with\s(?P<yes_resv>none|Representative\(s\)\s[^;]*?)\svoting\saye\swith\sreservations;\s*
    (?P<no>none|Representative\(s\)\s[^;]*?)\svoting\sno\s\((?P<n_no>\d+)\)\s+and\s+
    (?P<excused>none|Representative\(s\)\s[^;]*?)\sexcused\s\((?P<n_excused>\d+)\)
""",
    # Senate resolution adoption: "Report and Resolution Adopted as amended (SD 1).  Aye(s) with
    # reservations: none. Noes, 2 (Senator(s) DeCorte, Fevella)." (an excused list is optional)
    r"""
    Resolution\sAdopted.*?Aye\(s\)\swith\sreservations:\s*(?P<yes_resv>.*?)\s*\.\s+
    Noes,\s(?P<n_no>\d+)\s\((?P<no>.*?)\)\.
    (?:\s*Excused,\s(?P<n_excused>\d+)\s\((?P<excused>.*?)\)\.)?
""",
    # OPEN-710: veto overrides (2021 HB 862), read by no pattern above. Senate: "Veto overridden -
    # 2/3's vote: Ayes, 17; Aye(s) with reservations: Senator(s) Moriwaki . Noes, 8 (Senator(s)
    # Acasio, ...). Excused, 0 (none)." The aye count includes those with reservations.
    r"""
    Veto\soverridden.*?Ayes,\s(?P<n_yes>\d+);\s*
    Aye\(s\)\swith\sreservations:\s*(?P<yes_resv>.*?)\s*\.\s+
    Noes,\s(?P<n_no>\d+)\s\((?P<no>.*?)\)\.\s+
    Excused,\s(?P<n_excused>\d+)\s\((?P<excused>.*?)\)\.
""",
    # House: "Veto overridden by 2/3's vote with 38 Ayes; 8 Noes Representative(s) Har, ...; and
    # 4 Excused Representative(s) Ilagan, ... ." (no reservations list)
    r"""
    Veto\soverridden.*?(?P<n_yes>\d+)\sAyes;(?P<yes_resv>)\s*
    (?P<n_no>\d+)\sNoes\s*(?P<no>.*?);\s*and\s+
    (?P<n_excused>\d+)\sExcused\s*(?P<excused>.*?)\.?\s*$
""",
]

# OPEN-710: a roll call's result is the outcome its text states, else the threshold the vote needs.
FAILED_RE = re.compile(r"\b(failed|sustained)\b", re.IGNORECASE)
PASSED_RE = re.compile(r"\b(passed|adopted|overridden)\b", re.IGNORECASE)
OVERRIDE_RE = re.compile(r"\boverrid", re.IGNORECASE)
# Hawaii Constitution Art. III sec. 17: an override needs two-thirds of all the members to which
# each house is entitled (House 51, Senate 25), not of those voting.
CHAMBER_SIZE = {"lower": 51, "upper": 25}


def vote_result(chamber, text, yes_count, no_count):
    """'pass' or 'fail' for one roll call in chamber "upper"/"lower": the outcome the text states
    (passed, adopted, overridden; failed, sustained), else two-thirds of the house's seats for a
    veto override, else more yeas than nays."""
    if FAILED_RE.search(text):
        return "fail"
    if PASSED_RE.search(text):
        return "pass"
    if OVERRIDE_RE.search(text):
        return "pass" if 3 * yes_count >= 2 * CHAMBER_SIZE[chamber] else "fail"
    return "pass" if yes_count > no_count else "fail"


def create_bill_report_url(chamber, year, bill_type):
    cname = {"upper": "s", "lower": "h"}[chamber]
    bill_slug = {
        "bill": "%sb" % (cname),
        "cr": "%scr" % (cname.upper()),
        "r": "%sr" % (cname.upper()),
        "gm": "gm",
    }

    return (
        HI_URL_BASE
        + "/advreports/advreport.aspx?report=deadline&rpt_type=&measuretype="
        + bill_slug[bill_type]
        + "&year="
        + year
    )


logger = logging.getLogger(__name__)


def first_action_date(action_table):
    """The earliest date in a measure page's status table, or None (OPEN-748)."""
    dates = []
    for row in action_table.cssselect("tr")[1:]:
        cells = row.cssselect("td")
        try:
            dates.append(
                dt.datetime.strptime(cells[0].text_content().strip(), "%m/%d/%Y").date()
            )
        except (IndexError, ValueError):
            continue
    return min(dates, default=None)


def with_year(url, year):
    """A measure page URL asking for the site's year `year` instead."""
    parts = urlparse.urlparse(url)
    qs = dict(urlparse.parse_qsl(parts.query))
    qs["year"] = year
    return urlparse.urlunparse(parts._replace(query=urlparse.urlencode(qs)))


# A voter-name token that's really just a middle initial (e.g. "C." in
# "Lee, C.") stranded by the blind ", ".split() below.
MIDDLE_INITIAL_RE = re.compile(r"^[A-Z]\.?$")
# A "Senator(s)"/"Representative(s)" role-prefix with no name attached,
# including the garbled/truncated form missing the closing paren
# (e.g. "Senator(s" with no name and no ")").
PLACEHOLDER_VOTER_RE = re.compile(r"^(Senator|Representative)\(s\)?$", re.IGNORECASE)


def split_specific_votes(voters):
    if voters is None or voters.startswith("none") or voters == "":
        return []
    elif voters.startswith("Senator(s)"):
        voters = voters.replace("Senator(s) ", "")
    elif voters.startswith("Representative(s)"):
        voters = voters.replace("Representative(s)", "")
    elif voters.startswith("Senator(s"):
        # malformed/truncated source data, e.g. "Senator(s" with no name and
        # no closing paren -- nothing usable to parse out
        voters = voters[len("Senator(s") :]
    elif voters.startswith("Representative(s"):
        voters = voters[len("Representative(s") :]

    # Remove trailing spaces and semicolons
    tokens = [v.rstrip(" ;") for v in voters.split(", ")]

    # Re-merge middle-initial fragments (e.g. "Lee", "C." -> "Lee, C.") that
    # the blind ", ".split() above breaks apart, and drop any leftover
    # unparseable role placeholders instead of treating them as voters.
    merged = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if MIDDLE_INITIAL_RE.match(token) and merged:
            merged[-1] = f"{merged[-1]}, {token}"
        elif PLACEHOLDER_VOTER_RE.match(token):
            logger.warning("Dropping unparseable placeholder voter name: %r", token)
        else:
            merged.append(token)
    return merged


# OPEN-804: the bill page's "All Versions of this Measure" names each text by its file ("HB1163", "HB1163_HD1",
# "HB1163_CD1"), which has no stage. What each is, from the Legislative Reference Bureau's Advocate's Guide, Part 1
# (lrb.hawaii.gov/par, 2026), "Bill Numbers", and the texts' own headers (read 2026-11-23):
#   the bill number alone: the bill as introduced ("H.B. NO. 1163").
#   HD<N> / SD<N>: House Draft N / Senate Draft N, a committee's amended text ("If the bill is revised or amended, it
#   will be indicated by a new draft number (e.g., HD 1, SD 1, etc.)"); the bill's own chamber's drafts come first,
#   then the other chamber's after crossover ("SB145 SD2 HD1"). The file carries only the newest draft number.
#   CD<N>: Conference Draft N, the text the conference committee agreed ("SB145 SD2 HD1 CD1"); a CD2 follows when
#   both chambers floor-amend the CD1 (2026 HB 1334).
#   _PROPOSED: a committee's proposed draft, posted for its hearing before it decides ("S.D. 1 ... Proposed"; the
#   guide: "Keep an eye out for 'proposed drafts'"). Not a text the bill took: a document.
#   _HFA<N> / _SFA<N>: a House / Senate floor amendment to the draft named before it ("HOUSE AMENDMENT TO: H.B. No.
#   1334, H.D. 3, S.D. 2, C.D. 1"; "SENATE FLOOR AMENDMENT"): a document.
# A GM (governor's message) is a letter to the Legislature (an appointment, a bill signed into law, ...; the guide's
# "Governor's Messages (GM)"), not a bill: its file is a document. A trailing "_" or ".pdf" in the link text is the
# file name showing through ("HB900_HD1.pdf" is House Draft 1). Any other shape keeps its own name as a version.
VERSION_FILE_RE = re.compile(
    r"(?P<measure>[A-Z]+)\d+(?:_(?P<draft>[HSC]D)(?P<number>\d+))?"
    r"(?:_(?:(?P<proposed>PROPOSED)|(?P<floor>[HS])FA(?P<amendment>\d+)))?_?(?:\.pdf)?",
    re.IGNORECASE,
)
DRAFT_NAMES = {"HD": "House Draft", "SD": "Senate Draft", "CD": "Conference Draft"}


def version_name(link_text):
    """(name, is_version) for a link of the bill page's "All Versions of this Measure" (OPEN-804, see above)."""
    link_text = link_text.strip()
    m = VERSION_FILE_RE.fullmatch(link_text)
    if not m:
        return link_text, True
    if m["measure"].upper() == "GM":
        return "Governor's Message", False
    draft = (
        f"{DRAFT_NAMES[m['draft'].upper()]} {int(m['number'])}" if m["draft"] else None
    )
    if m["proposed"]:
        return (f"Proposed {draft}" if draft else link_text), False
    if m["floor"]:
        chamber = {"H": "House", "S": "Senate"}[m["floor"].upper()]
        name = f"{chamber} Floor Amendment {int(m['amendment'])}"
        return (f"{name} to {draft}" if draft else name), False
    return (draft or "Introduced"), True


class HIBillScraper(Scraper):
    categorizer = Categorizer()
    bill_types = ["HB", "HR", "HCR", "SB", "SR", "SCR", "GM"]
    tz = pytz.timezone("US/Hawaii")

    def parse_bill_metainf_table(self, metainf_table):
        def _sponsor_interceptor(line):
            # OPEN-805: the page writes a member who shares a surname as "SURNAME, I." ("LEE, C.",
            # "LEE, M."), in the same comma-separated list, so an initial after a comma belongs to
            # the name before it, as split_specific_votes rejoins them for roll calls. The list can
            # end in " (Introduced by request of another party)", removed in scrape_bill.
            names = []
            for guy in line.split(","):
                guy = guy.strip()
                if MIDDLE_INITIAL_RE.match(guy.split(" (", 1)[0]) and names:
                    names[-1] = f"{names[-1]}, {guy}"
                else:
                    names.append(guy)
            return names

        interceptors = {"Introducer(s)": _sponsor_interceptor}

        ret = {}
        for tr in metainf_table.cssselect("tr"):
            # a th and a td, or (the 2011-2012 archive pages, OPEN-748) two tds
            cells = tr.xpath("th|td")
            if len(cells) < 2:
                continue  # skip malformed rows
            key = cells[0].text_content().strip()
            value = cells[1].text_content().strip()
            if key[-1:] == ":":
                key = key[:-1]
            if key in interceptors:
                value = interceptors[key](value)
            ret[key] = value
        return ret

    _vote_type_map = {
        "S": "upper",
        "H": "lower",
        "D": "legislature",  # "Data Systems",
        "$": "Appropriation measure",
        "CONAM": "Constitutional Amendment",
    }

    def parse_bill_actions_table(
        self, bill, action_table, bill_id, session, url, bill_chamber
    ):

        # vote types that have been reconsidered since last vote of that type
        reconsiderations = set()

        for index, action_row in enumerate(action_table.cssselect("tr")[1:]):
            cells = action_row.cssselect("td")
            date_cell = cells[0]
            actor_cell = cells[1]
            desc_cell = cells[2]

            date = date_cell.text_content()
            date = dt.datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
            actor_code = actor_cell.text_content().upper()
            string = desc_cell.text_content()
            actor = self._vote_type_map[actor_code]
            committees = find_committee(string)

            action_attr = self.categorizer.categorize(string)
            atype = action_attr["classification"]
            # XXX: Translate short-code to full committee name for the
            #      matcher.

            real_committees = []

            if committees:
                for committee in committees:
                    try:
                        committee = self.short_ids[committee]["name"]
                        real_committees.append(committee)
                    except KeyError:
                        pass
            # there are some double actions on the source site
            if (
                bill_id == "HB2466"
                and date == "2022-04-29"
                and any(description in string for description in repeated_action)
            ):
                continue
            act = bill.add_action(string, date, chamber=actor, classification=atype)

            for committee in real_committees:
                act.add_related_entity(name=committee, entity_type="organization")
            vote = self.parse_vote(string)
            seated_ayes = []
            derived = bool(vote) and vote[0].get("n_yes") is None
            if derived:
                # OPEN-709: no aye count printed; None when the ayes cannot be worked out
                seated_ayes = self.seated_ayes(vote[0], actor, date, bill_id)
                if seated_ayes is None:
                    vote = None
            elif (
                vote
                and actor == "upper"
                and not split_specific_votes(vote[0].get("yes"))
            ):
                # OPEN-825: a Senate tally with an aye count and no aye names
                seated_ayes = self.counted_ayes(vote[0], actor, date, bill_id)

            if vote:
                v, motion = vote
                # OPEN-709: a tally whose ayes are worked out neither takes nor clears a pending
                # "Reconsider: " prefix, so the roll calls kept before read exactly as they did
                motion_text = (
                    ("Reconsider: " + motion)
                    if actor in reconsiderations and not derived
                    else motion
                )
                yays = v.get("n_yes")
                nays = v["n_no"]
                v_yes = v.get("yes", "")
                v_no = v.get("no", "")
                if yays is None:
                    yays = len(seated_ayes) + len(split_specific_votes(v["yes_resv"]))
                yays, nays = int(yays or 0), int(nays or 0)
                vote = VoteEvent(
                    start_date=date,
                    chamber=actor,
                    bill=bill_id,
                    bill_chamber=bill_chamber,
                    legislative_session=session,
                    motion_text=motion_text,
                    # OPEN-710: the stated outcome, else the vote's threshold
                    result=vote_result(actor, string, yays, nays),
                    # OPEN-691: what the roll call decides, from the hi block of
                    # config/motion_classification.yaml (committee reports are
                    # committee-passage; texts no rule names stay unlabelled)
                    classification=classify_motion("hi", motion_text),
                )
                if not derived:
                    reconsiderations.discard(actor)
                vote.add_source(url)
                vote.set_count("yes", yays)
                vote.set_count("no", nays)
                vote.set_count("not voting", int(v.get("n_excused") or 0))
                vote.dedupe_key = f"{index}#{bill_id}#{date}#{string[:300]}"
                for voter in split_specific_votes(v_yes):
                    voter = self.clean_voter_name(voter)
                    vote.yes(voter)
                for voter in split_specific_votes(v["yes_resv"]):
                    voter = self.clean_voter_name(voter)
                    vote.yes(voter)
                for voter in split_specific_votes(v_no):
                    voter = self.clean_voter_name(voter)
                    vote.no(voter)
                for voter in split_specific_votes(v.get("excused")):
                    voter = self.clean_voter_name(voter)
                    vote.vote("not voting", voter)
                for voter in seated_ayes:
                    vote.yes(voter)

                yield vote

            elif re.search("reconsider", string, re.IGNORECASE):
                reconsiderations.add(actor)

    def counted_ayes(self, v, chamber, date, bill_id):
        """OPEN-825: the plain ayes of a Senate tally that prints an aye count but names only the
        exceptions ("Ayes, 25; Aye(s) with reservations: none .  Noes, 0 (none). Excused, 0
        (none)."): seated_ayes' rule, kept only when those ayes plus the ayes with reservations
        come to the printed aye count. Otherwise none, with a warning: the roll call keeps its
        counts and the names it prints, as before."""
        kept = "plain ayes not stored, counts kept"
        ayes = self.seated_ayes(v, chamber, date, bill_id, kept)
        if ayes is None:
            return []
        resv = len(split_specific_votes(v["yes_resv"]))
        if len(ayes) + resv != int(v["n_yes"]):
            logger.warning(
                f"OPEN-825: {bill_id} {date} {chamber} {kept}: {len(ayes)} seated and not named "
                f"plus {resv} with reservations is not the printed {v['n_yes']} ayes"
            )
            return []
        return ayes

    def seated_ayes(self, v, chamber, date, bill_id, skipped="tally skipped"):
        """OPEN-709: the plain ayes of a tally that prints no aye count: the members seated in
        the chamber that day, minus those the text names (no, excused, aye with reservations).
        None, with a warning, when that cannot be done without guessing: no people data or no
        clear list of who sat, a named list whose length is not its printed count, or a name
        that is not exactly one seated member or names someone already listed. `skipped` says
        in the warning what the caller then does."""
        members = getattr(self, "members", None)
        if members is None:
            logger.warning(
                f"OPEN-709: {bill_id} {date} {chamber} {skipped}: no people data"
            )
            return None
        seated = members.seated(chamber, date)
        if seated is None:
            logger.warning(
                f"OPEN-709: {bill_id} {date} {chamber} {skipped}: the people data gives no "
                "clear list of who sat that day"
            )
            return None
        named = []
        for group, count in (
            ("yes_resv", None),
            ("no", "n_no"),
            ("excused", "n_excused"),
        ):
            names = [
                self.clean_voter_name(n) for n in split_specific_votes(v.get(group))
            ]
            if count and len(names) != int(v.get(count) or 0):
                logger.warning(
                    f"OPEN-709: {bill_id} {date} {chamber} {skipped}: {group} lists "
                    f"{len(names)} names for a count of {v.get(count)}"
                )
                return None
            for name in names:
                person = members.find(seated, name)
                if person is None or any(person["id"] == n["id"] for n in named):
                    logger.warning(
                        f"OPEN-709: {bill_id} {date} {chamber} {skipped}: {name!r} is not "
                        "exactly one member seated that day, or is listed twice"
                    )
                    return None
                named.append(person)
        named_ids = {n["id"] for n in named}
        return sorted(p["name"] for p in seated if p["id"] not in named_ids)

    def clean_voter_name(self, name):
        if name[-1] == ".":
            name = name[:-1]
        return name.strip()

    def parse_bill_versions_table(self, bill, bill_page):
        no_versions_warnings = bill_page.xpath(
            "//*[contains(@id, 'MainContent_UpdatePanel2')]"
            "//span[contains(text(),'You may search in our Document Directories')]"
        )
        if len(no_versions_warnings) == 1:
            # Text on the page indicates there are no versions for this bill, which happens once in a while
            self.logger.info(
                "No bill versions posted yet for {}".format(bill.identifier)
            )
            return
        else:
            versions = bill_page.xpath(
                "//*[contains(@id, 'MainContent_UpdatePanel2')]//a/img/../.."
            )
            if len(versions) == 0:
                self.logger.warning(
                    "Failed to select bill versions for {}".format(bill.identifier)
                )
                return

        for version in versions:
            td = version.xpath("./a")[0]
            if "No other versions" in td.text_content():
                return

            if version.xpath("./a"):
                http_href = td.attrib["href"]
                name, is_version = version_name(td.text_content())
                add_link = (
                    bill.add_version_link if is_version else bill.add_document_link
                )

                if not http_href.startswith("http"):
                    http_link = f"{HI_URL_BASE}{http_href}"
                else:
                    http_link = http_href
                pdf_link = http_link.replace("HTM", "PDF")

                # some bills (and GMs) swap the order or double-link to the same format
                # so detect the type, and ignore dupes
                add_link(
                    name,
                    make_data_url(http_link),
                    media_type=self.classify_media(http_link),
                )
                add_link(
                    name,
                    make_data_url(pdf_link),
                    media_type=self.classify_media(pdf_link),
                    on_duplicate="ignore",
                )

    def classify_media(self, url):
        media_type = None
        if "pdf" in url.lower():
            media_type = "application/pdf"
        elif ".htm" in url.lower():
            media_type = "text/html"
        elif ".docx" in url.lower():
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ".doc" in url.lower():
            media_type = "application/msword"
        return media_type

    def parse_testimony(self, bill, page):
        links = page.xpath("//table[contains(@id, 'GridViewTestimony')]/tr/td/a")

        # sometimes they have a second link w/ an icon for the pdf, sometimes now
        last_item = ""

        for link in links:
            filename = link.attrib["href"].replace("www.", "")
            name = link.text_content().strip()
            if name == "" and last_item != "":
                name = last_item
            else:
                name = "Testimony {}".format(name)

            last_item = name
            media_type = self.classify_media(filename)

            bill.add_document_link(name, filename, media_type=media_type)

    def parse_cmte_reports(self, bill, page):
        links = page.xpath("//table[contains(@id, 'GridViewCommRpt')]/tr/td/a")
        # sometimes they have a second link w/ an icon for the pdf, sometimes now
        last_item = ""

        for link in links:
            filename = link.attrib["href"].replace("www.", "")
            name = link.text_content().strip()
            if name == "" and last_item != "":
                name = last_item
            else:
                name = "Committee Report {}".format(name)

            last_item = name
            media_type = self.classify_media(filename)

            bill.add_document_link(name, filename, media_type=media_type)

    def scrape_bill(self, session, chamber, bill_type, url):
        bill_html = self.get(make_data_url(url)).text
        bill_page = lxml.html.fromstring(bill_html)
        bill_page.make_links_absolute(url)

        qs = dict(urlparse.parse_qsl(urlparse.urlparse(url).query))
        bill_id = "{}{}".format(qs["billtype"], qs["billnumber"])

        try:
            metainf_table = bill_page.xpath(
                '//div[contains(@id, "itemPlaceholder")]//table[1]'
            )[0]
        except IndexError:
            self.error(f"Missing Metainf table on {url}")
            return

        action_table = bill_page.xpath(
            '//div[contains(@id, "UpdatePanel1")]//table[1]'
        )[0]

        meta = self.parse_bill_metainf_table(metainf_table)

        # OPEN-748: a carried-over 2011 bill on the 2012 list is filed under 2011 (sessions.py)
        year = scraped_name(self.jurisdiction.legislative_sessions, session)
        if year in CARRIED_INTO.values():
            first_action = first_action_date(action_table)
            if first_action is None:
                first_action = self.companion_first_action(bill_page)
            if belongs_to_earlier_year(year, first_action):
                self.info(
                    f"Skipping {bill_id}: first acted on {first_action}, before {year}"
                )
                return

        subs = [s.strip() for s in re.split(r";|,", meta["Report Title"])]
        if "" in subs:
            subs.remove("")
        b = Bill(
            bill_id,
            session,
            meta["Measure Title"],
            chamber=chamber,
            classification=bill_type,
        )
        if meta["Description"]:
            b.add_abstract(meta["Description"], "description")
        for subject in subs:
            b.add_subject(subject)
        if url:
            b.add_source(url)

        # check for companion bills
        companion = meta["Companion"].strip()
        if companion:
            companion_url_elems = bill_page.xpath(
                "//span[contains(@id, 'ListView1_companionLabel_0')]/a/@href"
            )
            if len(companion_url_elems) > 0:
                companion_url = companion_url_elems[0]
                # a companion's session year is the last 4 chars of the link
                # this will match the _scraped_name of a session in __init__.py
                companion_year = companion_url[-4:]
                # OPEN-748: the 2012 pages link 2011 bills carried over as 2012; such a
                # companion is filed under the year of its first dated action
                if companion_year in CARRIED_INTO.values():
                    first = self.companion_first_action(bill_page)
                    if belongs_to_earlier_year(companion_year, first):
                        companion_year = str(first.year)
                companion_session = self.session_from_scraped_name(companion_year)
                b.add_related_bill(
                    identifier=companion.replace("\xa0", " "),
                    legislative_session=companion_session,
                    relation_type="companion",
                )
            else:
                self.logger.warning(
                    f"Failed to find companion when expected at {make_data_url(url)}"
                )
        # check for prior session bills
        if bill_page.xpath(
            "//table[@id='ContentPlaceHolderCol1_GridViewStatus']/tr/td/font/text()"
        ):
            prior = bill_page.xpath(
                "//table[@id='ContentPlaceHolderCol1_GridViewStatus']/tr/td/font/text()"
            )[-1]
            # "2023 Regular Session" -> "2022" -> "2022 Regular Session"
            prior_year = str(int(session[:4]) - 1)
            prior_session = f"{prior_year} Regular Session"
            if "carried over" in prior.lower():
                b.add_related_bill(
                    identifier=bill_id.replace("\xa0", " "),
                    legislative_session=prior_session,
                    relation_type="prior-session",
                )

        for sponsor in meta["Introducer(s)"]:
            if "(Introduced by request of another party)" in sponsor:
                sponsor = sponsor.replace(
                    " (Introduced by request of another party)", ""
                )
            if sponsor != "":
                # all caps sponsors are primary, others are secondary
                primary = sponsor.upper() == sponsor
                b.add_sponsorship(
                    sponsor, "primary" if primary else "cosponsor", "person", primary
                )

        if "gm" in bill_id.lower():
            # OPEN-805: a governor's message comes from the Governor, so its sponsor is Hawaii's
            # executive organization (core's metadata executive_name), as Massachusetts names its
            # governor's bills; "governor" as a person matched no one
            b.add_sponsorship("Office of the Governor", "primary", "organization", True)

        self.parse_bill_versions_table(b, bill_page)
        self.parse_testimony(b, bill_page)
        self.parse_cmte_reports(b, bill_page)

        if (
            bill_page.xpath("//input[@id='MainContent_ImageButtonPDF']")
            and len(b.versions) == 0
            # OPEN-804: a GM's file is a document, so a GM has no version
            and not bill_id.upper().startswith("GM")
        ):
            self.parse_bill_header_versions(b, bill_id, session, bill_page)

        current_referral = meta["Current Referral"].strip()
        if current_referral:
            b.extras["current_referral"] = current_referral

        if meta.get("Act"):
            act_num = meta["Act"]
            act_url = bill_page.xpath(f"//a[text()={act_num}]/@href")[0]
            b.add_citation(f"Hawaii {session} Acts", act_num, "chapter", url=act_url)

        for vote in self.parse_bill_actions_table(
            b, action_table, bill_id, session, url, chamber
        ):
            # OPEN-748: a roll call taken while a special session sat is that session's; its
            # bill link (made above, under `session`) stays on the regular bill
            special = special_session_on(
                self.jurisdiction.legislative_sessions, vote.start_date
            )
            if special:
                vote.legislative_session = special
            yield vote
        yield b

    def companion_first_action(self, bill_page):
        """The first dated action of the companion the measure page lists, or None."""
        hrefs = bill_page.xpath(
            "//span[contains(@id, 'ListView1_companionLabel_0')]/a/@href"
        )
        if not hrefs:
            return None
        page = lxml.html.fromstring(self.get(make_data_url(hrefs[0])).text)
        tables = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')
        return first_action_date(tables[0]) if tables else None

    # sometimes they link to a version that's only in the header,
    # and works via a form submit, so hardcode it here
    # jessemortenson: not sure that this condition still occurs
    #                 couldn't find evidence of it in late 2024 session
    def parse_bill_header_versions(self, bill, bill_id, session, page):
        pdf_link = f"https://capitol.hawaii.gov/session/session{session[0:4]}/bills/{bill_id}_.PDF"
        bill.add_version_link(
            "Introduced",
            pdf_link,
            media_type="application/pdf",
            on_duplicate="ignore",
        )

    def parse_vote(self, action):
        # Try regex for a couple of edge cases
        result = None
        for vote_re in vote_re_list:
            result = re.search(vote_re, action, re.VERBOSE)
            if result:
                break
        if result is None:
            return None
        result = result.groupdict()
        motion = action.split(".")[0] + "."
        return result, motion

    def scrape_type(self, chamber, session, billtype):
        for i in self.jurisdiction.legislative_sessions:
            if i["identifier"] == session:
                session_urlslug = i["_scraped_name"]
        report_page_url = create_bill_report_url(chamber, session_urlslug, billtype)
        billtype_map = {
            "bill": "bill",
            "cr": "concurrent resolution",
            "r": "resolution",
            "gm": "proclamation",
        }[billtype]

        # OPEN-748: a 2011 bill also on the 2012 list was carried over; its 2012 page holds its
        # whole history, 2012 actions included (sessions.py)
        later = CARRIED_INTO.get(session_urlslug)
        carried = set()
        if later:
            carried = {
                self.measure_key(a.attrib["href"])
                for a in self.report_links(
                    create_bill_report_url(chamber, later, billtype)
                )
            }

        for bill_url in self.report_links(report_page_url):
            bill_url = bill_url.attrib["href"].replace("www.", "")
            if not bill_url.startswith("http"):
                bill_url = f"{HI_URL_BASE}{bill_url}"
            if self.measure_key(bill_url) in carried:
                bill_url = with_year(bill_url, later)
            if (
                TEST_SINGLE_BILL is False
                or f"billnumber={TEST_SINGLE_BILL_NUMBER}" in bill_url
            ):
                yield from self.scrape_bill(session, chamber, billtype_map, bill_url)

    def report_links(self, report_page_url):
        list_html = self.get(make_data_url(report_page_url)).text
        return lxml.html.fromstring(list_html).xpath("//a[@class='report']")

    @staticmethod
    def measure_key(url):
        qs = dict(urlparse.parse_qsl(urlparse.urlparse(url).query))
        return qs.get("billtype"), qs.get("billnumber")

    def scrape(self, chamber=None, session=None, scrape_since=None):
        if is_special(self.jurisdiction.legislative_sessions, session):
            # OPEN-748: the site lists no special-session measures, and this session's roll calls
            # on regular bills come with those bills. OPEN-751: the measures of the four special
            # sessions both chambers sat in are read from their PDFs (special_measures.py); the
            # other special sessions were the Senate alone confirming appointments
            if session not in special_measures.SOURCES:
                raise EmptyScrape(
                    f"{session}: the Senate alone sat; no measures of its own"
                )
            yield from self.scrape_special(session, chamber)
            return
        get_short_codes(self)
        # OPEN-709: seated members, for the tallies that print no aye count
        self.members = load_members(self)

        if scrape_since is None:
            bill_types = ["bill", "cr", "r"]
            chambers = [chamber] if chamber else ["lower", "upper"]
            for chamber in chambers:
                # only scrape GMs once
                if chamber == "upper":
                    bill_types.append("gm")
                for typ in bill_types:
                    yield from self.scrape_type(chamber, session, typ)
        else:
            day = dt.datetime.now(self.tz).date() - dt.timedelta(days=int(scrape_since))
            yield from self.scrape_xml(session, day)

    def scrape_special(self, session, chamber=None):
        """OPEN-751: the bills and resolutions of a two-chamber special session, from its
        document folder and both chambers' journals on data.capitol.hawaii.gov."""
        source = special_measures.SOURCES[session]
        (entry,) = [
            s
            for s in self.jurisdiction.legislative_sessions
            if s["identifier"] == session
        ]
        start = dt.date.fromisoformat(entry["start_date"])
        end = dt.date.fromisoformat(entry["end_date"])
        folder = special_measures.DATA + source["folder"]
        measures = special_measures.folder_measures(self.get(folder).text)
        if not measures:
            raise EmptyScrape(f"{session}: no measures in {folder}")
        events, journals = {}, {}
        for side in ("upper", "lower"):
            days = []
            for path in source[side]:
                url = special_measures.DATA + path
                xml = special_measures.pdf_bytes_xml(self.get(url).content)
                read = special_measures.journal_days(special_measures.xml_pages(xml))
                # a journal must read as sitting days of this session, or nothing it says can be
                # dated: stop rather than file its measures without their history
                if not read or not all(start <= d <= end for d, _ in read):
                    raise ValueError(
                        f"{url}: sitting days {[str(d) for d, _ in read]} not within "
                        f"{session} ({start} to {end})"
                    )
                days.extend(read)
                journals.setdefault(side, []).append(url)
            events[side] = special_measures.measure_events(days, side, set(measures))
        for key in sorted(measures, key=lambda k: (k[0], int(k[1]))):
            if chamber and special_measures.TYPES[key[0]][0] != chamber:
                continue
            yield from self.special_bill(
                session, key, measures[key], events, folder, journals
            )

    def special_bill(self, session, key, measure, events, folder, journals):
        """The Bill (and its VoteEvents) of one special-session measure: `measure` from
        folder_measures(), `events` {"upper": ..., "lower": ...} from measure_events(), `journals`
        {"upper": [url], "lower": [url]}."""
        bill_chamber, classification, _ = special_measures.TYPES[key[0]]
        bill_id = f"{key[0]}{key[1]}"
        other = "lower" if bill_chamber == "upper" else "upper"
        # the title its own chamber's journal gives it, else the other chamber's; a measure that
        # cannot be titled cannot be read reliably, so it stops the scrape (OPEN-751)
        title = None
        for side in (bill_chamber, other):
            titles = {t for _, t in events[side][key]["titles"]}
            if len(titles) > 1:
                raise ValueError(
                    f"{session} {bill_id}: the {side} journal gives two titles {titles}"
                )
            if titles:
                title = titles.pop()
                break
        if title is None:
            raise ValueError(f"{session} {bill_id}: no journal gives its title")
        bill = Bill(
            bill_id,
            session,
            title,
            chamber=bill_chamber,
            classification=classification,
        )
        for url in [folder] + journals["upper"] + journals["lower"]:
            bill.add_source(url)
        # the journal names each introducer alike ("Introduced by: Representatives McKelvey,
        # Carroll, Evans and Kawakami"; "jointly offered by"), so each is a primary sponsor
        for name in dict.fromkeys(events[bill_chamber][key]["sponsors"]):
            bill.add_sponsorship(name, "primary", "person", True)
        if not bill.sponsorships:
            self.warning(f"{session} {bill_id}: no introducer read from the journal")
        # folder_measures gives only the introduced text and HD/SD/CD drafts as versions (its floor
        # amendments and committee reports are already documents), so each is a version here
        for name, url in measure["versions"]:
            version, _ = version_name(name if name == bill_id else f"{bill_id}_{name}")
            bill.add_version_link(version, url, media_type="application/pdf")
        for name, url in measure["documents"]:
            bill.add_document_link(name, url, media_type="application/pdf")
        actions = events["upper"][key]["actions"] + events["lower"][key]["actions"]
        for date, actor, description, action_type in sorted(
            actions, key=lambda a: a[0]
        ):
            bill.add_action(
                description, date.isoformat(), chamber=actor, classification=action_type
            )
        votes = events["upper"][key]["votes"] + events["lower"][key]["votes"]
        for index, (date, actor, motion, tally) in enumerate(votes):
            if tally == "unreadable":
                self.warning(
                    f"{session} {bill_id}: {actor} roll call of {date} ({motion}) does not read "
                    "cleanly; left out"
                )
                continue
            vote = VoteEvent(
                start_date=date.isoformat(),
                chamber=actor,
                bill=bill_id,
                bill_chamber=bill_chamber,
                legislative_session=session,
                motion_text=motion,
                result=vote_result(actor, motion, tally["yes"], tally["no"]),
                classification=classify_motion("hi", motion),
            )
            for url in journals[actor]:
                vote.add_source(url)
            vote.set_count("yes", tally["yes"])
            vote.set_count("no", tally["no"])
            vote.set_count("not voting", tally["excused"])
            for option, name in tally["voters"]:
                vote.vote(option, name)
            vote.dedupe_key = f"{session}#{bill_id}#{actor}#{date}#{motion}#{index}"
            yield vote
        yield bill

    def scrape_xml(self, session, day):
        url = "https://www.capitol.hawaii.gov/sessions/session2024/rss/"
        self.info(f"fetching url {url}")
        page = self.get(make_data_url(url)).text
        # this content isn't amenable to lxml, but it's machine generated so regex should be ok
        bill_re = r"(?P<date>\d+\/\d+\/\d+)\s+(?P<time>.*?)\s+\d+\s\<a href=\"(?P<url>.*?)\">(?P<filename>.*?)\.xml<\/a>"
        for match in re.finditer(bill_re, page, flags=re.IGNORECASE):
            posted = dateutil.parser.parse(
                f"{match.group('date')} {match.group('time')}"
            )
            posted = self.tz.localize(posted)
            posted = posted.date()
            try:
                bill_type, bill_num = self.parse_bill_number(match.group("filename"))
            except TypeError:
                self.error(f"Skipping {match.group('filename')}")
                continue
            if posted >= day and bill_type in self.bill_types:
                self.info(
                    f"Scraping {bill_type}{bill_num} posted on {posted.strftime('%Y-%m-%d')}"
                )
                chamber, classification = self.classify_bill_type(
                    match.group("filename")
                )

                # https://www.capitol.hawaii.gov/session/measure_indiv.aspx?billtype=SB&billnumber=3013
                bill_url = f"https://www.capitol.hawaii.gov/session/measure_indiv.aspx?billtype={bill_type}&billnumber={bill_num}"

                yield from self.scrape_bill(session, chamber, classification, bill_url)
            else:
                self.info(
                    f"Skipping {bill_type}{bill_num} posted on {posted.strftime('%Y-%m-%d')}"
                )

    def session_from_scraped_name(self, scraped_name):
        # find the session from __init__.py matching scraped_name
        details = next(
            each
            for each in self.jurisdiction.legislative_sessions
            # special sessions (OPEN-748) have no site year
            if each.get("_scraped_name") == scraped_name
        )
        return details["name"]

    def classify_bill_type(self, bill: str) -> tuple:
        billtypes = {
            "HB": ("lower", "bill"),
            "HR": ("lower", "resolution"),
            "HCR": ("lower", "concurrent resolution"),
            "SB": ("upper", "bill"),
            "SR": ("upper", "resolution"),
            "SCR": ("upper", "concurrent resolution"),
            "GM": ("upper", "proclamation"),
        }

        for key, val in billtypes.items():
            if bill.startswith(key):
                return val

        self.error(f"Invalid bill type: {bill}")

    def parse_bill_number(self, bill: str) -> tuple:
        match = re.search(r"(?P<type>[A-Z]+)(?P<number>\d+)", bill)
        if match:
            return (match.group("type"), match.group("number"))
