"""Missouri member-level floor roll calls (OPEN-696).

The bills scraper only makes totals-only votes. Member names come from two places:

* House: one PDF per roll call, numbered by session day and roll call
  (documents.house.mo.gov/billtracking/bills261/rollcalls/049.010.pdf). They cover every
  House roll call, on House and Senate bills alike; a number that does not exist answers
  with an HTML error page instead of a PDF.
* Senate: the daily journal PDFs listed on senate.mo.gov/journallist, where each roll
  call follows "... by the following vote:" as YEAS / NAYS / Absent / Absent with leave.

Roll calls not tied to a bill (approving the journal, appointments) are skipped.
What each roll call decides comes from the mo block of config/motion_classification.yaml
(OPEN-705, vote_classification() below); a concurrence or conference report vote followed by
the bill's final passage roll call is not passage (OPEN-714, final_vote_only() below).
"""

import datetime as dt
import os
import re

import lxml.html

from openstates.scrape import Scraper, VoteEvent
from openstates.utils import convert_pdf

from classify_motion import classify_motion

from .bills import MOBillScraper

HOUSE_ROLLCALL_URL = "https://documents.house.mo.gov/billtracking/bills{code}/rollcalls/{day:03}.{rc:03}.pdf"
SENATE_JOURNAL_LIST_URL = "https://www.senate.mo.gov/journallist/?SelectedYear={year}"

# a session day without roll call 001 has no roll calls; this many in a row ends the walk
HOUSE_EMPTY_DAYS_TO_STOP = 10

# "HB 2885", "SBs 835 & 1111", "SS No. 2 for SCS for HCS for HB 2292"
SHORT_BILL_RE = re.compile(r"\b(HJR|SJR|HCR|SCR|HB|SB|HR|SR)S?\s+(\d+)", re.I)
# "House Bill No. 2474", "SENATE BILLS NOS. 835 and 1111", "Senate Joint Resolution No. 87"
LONG_BILL_RE = re.compile(
    r"\b(House|Senate)\s+(Bill|Joint\s+Resolution|Concurrent\s+Resolution|Resolution)s?"
    r"\s+Nos?\.\s*(\d+)",
    re.I,
)
LONG_BILL_TYPES = {
    "bill": "B",
    "joint resolution": "JR",
    "concurrent resolution": "CR",
    "resolution": "R",
}

HOUSE_OPTIONS = {"Y": "yes", "N": "no", "P": "other", "@": "absent"}
HOUSE_VOTE_RE = re.compile(r"([YNP@])\s+-\s+(\S.*?)(?=\s{2,}[YNP@]\s+-|\s*$)")

# Vacancies is a count, not a list of senators
SENATE_OPTIONS = {
    "yeas": "yes",
    "nays": "no",
    "present": "other",
    "absent": "absent",
    "absent with leave": "excused",
    "excused from voting": "not voting",
    "vacancies": None,
}
SENATE_LABEL_RE = re.compile(
    r"^\s*(Absent with leave|Absent|Excused from voting|YEAS|NAYS|PRESENT|Vacancies)\s*[—-]",
    re.I,
)
JOURNAL_DATE_RE = re.compile(
    r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+([A-Z]+)\s+(\d+),\s+(\d{4})"
)
# running page headers: "378   Journal of the Senate" and
# "Twentieth Day - Thursday, February 12, 2026   379"; the first page has its number at the foot
PAGE_HEADER_RE = re.compile(
    r"^\s*(?:(\d+)\s{2,}(?:Journal of the Senate|.*\bDay\b.*)"
    r"|(?:Journal of the Senate|.*\bDay\b.*?)\s{2,}(\d+))\s*$"
)
BARE_NUMBER_RE = re.compile(r"^\s*(\d+)\s*$")
# journal files are {R|V|T1|T2}Day...pdf: regular, veto, first and second extraordinary
SENATE_JOURNAL_PREFIXES = {"": ("R", "V"), "S1": ("T1",), "S2": ("T2",)}

# OPEN-705: an amendment roll call, labelled here because config/motion_classification.yaml
# only decides passage: a House header's amendment line ("... - *HA 1 - ...", "HA 1 HA 2")
# or a Senate "SA 2 was adopted" / "SA 3 failed of adoption". A previous question or a
# motion on it (" - PREVIOUS QUESTION", " - THAT ...", "... be reconsidered") is not.
AMENDMENT_VOTE_RE = re.compile(r"(^| - )\*?[HS]A \d+\b", re.I)
MOTION_ON_RE = re.compile(r" - (PREVIOUS QUESTION|\*?THAT )|\breconsider", re.I)
# a House roll-call PDF names no motion, so the emergency clause vote that follows a bill's
# passage has the same header; the House scraper adds this to tell them apart
EMERGENCY_CLAUSE = " - EMERGENCY CLAUSE"

# OPEN-714 (Ramon 2026-11-20, "Final vote only"): the vote that takes the other chamber's
# version (House "HBs WITH SENATE AMENDMENTS", whose header repeats on the final vote that
# follows; Senate "moved that HCS for SB 982 be adopted") or adopts a conference report
# (House "BILLS IN CONFERENCE - CCR ...", then "- CCS ..."; Senate "the above conference
# committee report be adopted", then "Was read the 3rd time and passed") is passage only
# when no final passage roll call on the bill follows it in that chamber.
CONCURRENCE_RE = re.compile(
    r"^HBs (WITH|W/) ?SENATE AMENDMENTS - |\bmoved that (HCS|HS|HA \d+) (for|to) ", re.I
)
CONFERENCE_REPORT_RE = re.compile(
    r"^BILLS IN CONFERENCE - CCR |\bconference committee report\b", re.I
)


def bill_from_text(text, last=False):
    """The first (or last) bill named in the text, as 'SB 835'; None if there is none."""
    found = [
        (m.start(), f"{m.group(1).upper()} {int(m.group(2))}")
        for m in SHORT_BILL_RE.finditer(text)
    ]
    for m in LONG_BILL_RE.finditer(text):
        kind = LONG_BILL_TYPES[re.sub(r"\s+", " ", m.group(2).lower())]
        found.append((m.start(), f"{m.group(1)[0].upper()}{kind} {int(m.group(3))}"))
    if not found:
        return None
    found.sort()
    return found[-1][1] if last else found[0][1]


def house_voter_name(name):
    # "SMITH 46" -> "SMITH (46)", the same-surname form the Senate journal uses
    return re.sub(r"\s+(\d+)$", r" (\1)", name.strip())


def parse_house_rollcall(text):
    """One House roll-call PDF's text -> dict, or None when the roll call names no bill."""
    lines = text.splitlines()
    head = re.search(
        r"Session Day\s*:\s*(\d+)\s+(.*?)\s+Date\s*:\s*(\d+/\d+/\d{4})", text
    )
    rc_line = next(
        (i for i, line in enumerate(lines) if re.search(r"Roll Call\s*:", line)), None
    )
    if not head or rc_line is None:
        return None
    m = re.search(r"Roll Call\s*:\s*(\d+)\s+(.*)", lines[rc_line])
    bill_string = m.group(2).strip()
    bill = bill_from_text(bill_string)
    if not bill:
        return None

    # the lines between "Roll Call" and the grid: amendment, sponsor, title, LR number, motion
    votes, motion_lines = [], [head.group(2).strip(), bill_string]
    for line in lines[rc_line + 1 :]:
        found = HOUSE_VOTE_RE.findall(line)
        if found:
            votes.extend(
                (HOUSE_OPTIONS[code], house_voter_name(name)) for code, name in found
            )
        elif not votes and line.strip():
            motion_lines.append(line.strip())

    totals = {}
    for option, label in (
        ("yes", "Yes"),
        ("no", "No"),
        ("other", "Present"),
        ("absent", "Absent"),
    ):
        total = re.search(rf"Total {label}\s*:\s*(\d+)", text)
        if total:
            totals[option] = int(total.group(1))
    return {
        "date": dt.datetime.strptime(head.group(3), "%m/%d/%Y"),
        "bill": bill,
        "motion": " - ".join(motion_lines),
        "votes": votes,
        "totals": totals,
    }


def _page_number(page):
    lines = [line for line in page.splitlines() if line.strip()]
    for line in lines[:2]:
        m = PAGE_HEADER_RE.match(line)
        if m:
            return int(m.group(1) or m.group(2))
    if lines and BARE_NUMBER_RE.match(lines[-1]):
        return int(lines[-1])
    return None


def parse_senate_journal(text):
    """One Senate journal's text -> its roll calls on bills, in journal order."""
    date = dt.datetime.strptime(
        " ".join(JOURNAL_DATE_RE.search(text.upper()).groups()), "%B %d %Y"
    )

    # pdftotext separates pages with form feeds; the first page has no running header
    pages = text.split("\f")
    known = next(((i, n) for i, n in enumerate(map(_page_number, pages)) if n), (0, 0))
    lines = [
        (known[1] - known[0] + i, line)
        for i, page in enumerate(pages)
        for line in page.splitlines()
    ]

    roll_calls, context_start, i = [], 0, 0
    while i < len(lines):
        page, line = lines[i]
        # OPEN-707: the lead-in can wrap, "... passed by the following" / "vote:"
        if (
            re.search(r"\bfollowing\s*$", line)
            and i + 1 < len(lines)
            and re.match(r"^\s*vote:\s*$", lines[i + 1][1])
        ):
            i += 1
        elif not re.search(r"following vote:\s*$", line):
            i += 1
            continue
        # the motion is the paragraph ending here: a paragraph opens indented and runs on
        # at column 0
        start = i
        while start > context_start and not re.match(r"^\s{2,}\S", lines[start][1]):
            start -= 1
        motion = " ".join(ln for _, ln in lines[start : i + 1])
        motion = re.sub(r"\s+", " ", motion).strip()
        # "Was read the 3rd time and passed" and "the above conference committee report"
        # name no bill; it is the last one named since the previous roll call
        context = " ".join(ln for _, ln in lines[context_start:start])
        # OPEN-714: "Was read the 3rd time" follows "CCS for ... HBs 2637 and 3155,
        # entitled:" and the bill's title, which can name other bills ("... as enacted by
        # ... house bills nos. 2273, 1946 ...")
        if motion.startswith("Was read the 3rd time") and "entitled:" in context:
            context = context[: context.rindex("entitled:")]
        bill = bill_from_text(motion) or bill_from_text(context, last=True)
        # "The emergency clause was adopted" follows the passage of the bill voted on last
        if not bill and "emergency clause" in motion.lower() and roll_calls:
            bill = roll_calls[-1]["bill"]

        votes, totals, option = [], {}, None
        i += 1
        while i < len(lines):
            ln = lines[i][1]
            label = SENATE_LABEL_RE.match(ln)
            if label:
                i += 1
                option = SENATE_OPTIONS[label.group(1).lower()]
                if option is None:
                    # "Vacancies—None"; "Excused from voting" may still follow
                    continue
                ln = re.sub(r"^\s*Senators?\s*[—-]?", "", ln[label.end() :])
                if re.match(r"\s*None\b", ln):
                    continue
                # "NAYS—Senators—2", the names on the lines below
                if BARE_NUMBER_RE.match(ln):
                    totals[option] = int(ln)
                    continue
            elif not ln.strip() or PAGE_HEADER_RE.match(ln) or BARE_NUMBER_RE.match(ln):
                i += 1
                continue
            elif option is None or re.match(r"^\s{2,}\S", ln):
                # names run at column 0; an indented line is the journal going on
                break
            else:
                i += 1
            for name in re.split(r"\s{2,}", ln.strip()):
                # the last name of a list carries its count: "Webber—32"
                m = re.match(r"(.*?)\s*[—-](\d+)$", name)
                if m:
                    name, totals[option] = m.group(1), int(m.group(2))
                if name:
                    votes.append((option, name))
        context_start = i
        if bill and votes:
            roll_calls.append(
                {
                    "page": page,
                    "date": date,
                    "bill": bill,
                    "motion": motion,
                    "votes": votes,
                    "totals": totals,
                }
            )
    return roll_calls


def vote_classification(motion):
    """What a roll call decides: passage from the mo block of
    config/motion_classification.yaml, else "amendment" for an amendment roll call, else
    nothing."""
    classification = classify_motion("mo", motion)
    if classification:
        return classification
    if AMENDMENT_VOTE_RE.search(motion) and not MOTION_ON_RE.search(motion):
        return ["amendment"]
    return []


def final_vote_only(roll_calls):
    """One chamber's roll calls of a session, in order -> each one's classification.
    A concurrence or conference report vote followed by a later passage roll call on the
    same bill is not passage (OPEN-714): a concurrence is labelled "amendment" (it takes
    the other chamber's changes, as ia labels it), a conference report vote is left
    unlabelled. One with no passage vote after it stays passage (pa OPEN-617, la
    OPEN-583)."""
    labels = [vote_classification(rc["motion"]) for rc in roll_calls]
    for i, rc in enumerate(roll_calls):
        if "passage" not in labels[i]:
            continue
        if CONCURRENCE_RE.search(rc["motion"]):
            first = ["amendment"]
        elif CONFERENCE_REPORT_RE.search(rc["motion"]):
            first = []
        else:
            continue
        if any(
            "passage" in labels[j] and roll_calls[j]["bill"] == rc["bill"]
            for j in range(i + 1, len(roll_calls))
        ):
            labels[i] = first
    return labels


def mark_emergency_clauses(roll_calls):
    """One House session day's roll calls, in order. A bill with an emergency clause
    (", E.C." in its header) is voted on and then its emergency clause is, both under the
    same header ("HCS HB 3080 was read the third time and passed ... The emergency clause
    was defeated", House journal day 49); the last of a run of identical headers is the
    emergency clause."""
    for i, rc in enumerate(roll_calls):
        same_before = i > 0 and roll_calls[i - 1]["motion"] == rc["motion"]
        same_after = (
            i + 1 < len(roll_calls) and roll_calls[i + 1]["motion"] == rc["motion"]
        )
        if ", E.C." in rc["motion"] and same_before and not same_after:
            rc["emergency_clause"] = True
    for rc in roll_calls:
        if rc.pop("emergency_clause", False):
            rc["motion"] += EMERGENCY_CLAUSE
    return roll_calls


def vote_result(motion, yes, no):
    # the outcome word nearest the vote decides: "moved that the vote by which SA 1 failed
    # be reconsidered, which motion prevailed" passed
    words = re.findall(
        r"\b(failed|lost|defeated|passed|prevailed|adopted)\b", motion, re.I
    )
    if words:
        return "fail" if words[-1].lower() in ("failed", "lost", "defeated") else "pass"
    return "pass" if yes > no else "fail"


class MOVoteScraper(Scraper):
    def _get_pdf_text(self, url):
        """The PDF's text, or None when the URL answers with something other than a PDF."""
        path, _ = self.urlretrieve(url)
        try:
            with open(path, "rb") as f:
                if f.read(4) != b"%PDF":
                    return None
            return convert_pdf(path, type="text").decode("utf-8", "replace")
        finally:
            os.remove(path)

    def _make_vote(self, session, chamber, rc, dedupe_key, sources, classification):
        counts = {}
        for option, _ in rc["votes"]:
            counts[option] = counts.get(option, 0) + 1
        for option, total in rc["totals"].items():
            if counts.get(option, 0) != total:
                self.warning(
                    f"{dedupe_key}: {counts.get(option, 0)} {option} names, "
                    f"the roll call says {total}"
                )
        yes, no = counts.get("yes", 0), counts.get("no", 0)
        # the journal says whether a Senate motion passed; a House roll-call PDF does not,
        # and its header holds the bill's short title, so it is not searched for "failed"
        if chamber == "upper":
            result = vote_result(rc["motion"], yes, no)
        else:
            result = "pass" if yes > no else "fail"
        vote = VoteEvent(
            chamber=chamber,
            start_date=rc["date"].strftime("%Y-%m-%d"),
            motion_text=rc["motion"],
            result=result,
            legislative_session=session,
            classification=classification,
            bill=rc["bill"],
            bill_chamber="lower" if rc["bill"].startswith("H") else "upper",
        )
        # unique across sessions and bills (PRIMITIVES: OPEN-252, OPEN-397)
        vote.dedupe_key = dedupe_key
        for option, count in counts.items():
            vote.set_count(option, count)
        for option, name in rc["votes"]:
            vote.vote(option, name)
        for url in sources:
            vote.add_source(url)
        return vote

    def _scrape_lower_chamber(self, session):
        # the bills scraper's House session code: 2026 -> 261, 2025S1 -> 253
        code = MOBillScraper._get_session_code(self, session)
        day, empty_days, roll_calls = 0, 0, []
        while empty_days < HOUSE_EMPTY_DAYS_TO_STOP:
            day += 1
            rc, found = 1, []
            while True:
                url = HOUSE_ROLLCALL_URL.format(code=code, day=day, rc=rc)
                text = self._get_pdf_text(url)
                if text is None:
                    break
                parsed = parse_house_rollcall(text)
                if parsed:
                    parsed["key"] = f"mo-{session}-H-{day:03}.{rc:03}"
                    parsed["url"] = url
                    found.append(parsed)
                rc += 1
            roll_calls.extend(mark_emergency_clauses(found))
            empty_days = empty_days + 1 if rc == 1 else 0
        # the whole session first: a final passage vote can come on a later day
        for parsed, label in zip(roll_calls, final_vote_only(roll_calls)):
            yield self._make_vote(
                session, "lower", parsed, parsed["key"], [parsed["url"]], label
            )

    def _scrape_upper_chamber(self, session):
        year, kind = session[:4], session[4:]
        list_url = SENATE_JOURNAL_LIST_URL.format(year=year)
        page = lxml.html.fromstring(self.get(list_url).content)
        page.make_links_absolute(list_url)
        prefixes = "|".join(SENATE_JOURNAL_PREFIXES[kind])
        pattern = re.compile(
            rf"/{year[2:]}info/Journals/({prefixes})Day[^/]*\.pdf$", re.I
        )
        seen, roll_calls = set(), []
        for url in dict.fromkeys(page.xpath("//a/@href")):
            if not pattern.search(url):
                continue
            text = self._get_pdf_text(url)
            if text is None:
                self.warning(f"not a PDF: {url}")
                continue
            per_page = {}
            for rc in parse_senate_journal(text):
                # journal pages number straight through a session, so page + order on the
                # page is unique; the list carries some days twice (RDay21.pdf and
                # RDay210217387-397.pdf), and the second copy is skipped
                per_page[rc["page"]] = per_page.get(rc["page"], 0) + 1
                key = f"mo-{session}-S-{rc['page']}-{per_page[rc['page']]}"
                if key in seen:
                    continue
                seen.add(key)
                rc["key"], rc["sources"] = key, [list_url, url]
                rc["order"] = (rc["date"], rc["page"], per_page[rc["page"]])
                roll_calls.append(rc)
        # the whole session in journal order (the list is not: RDay21.pdf comes first):
        # SB 973's conference report was adopted on May 11 and the bill passed on May 15
        roll_calls.sort(key=lambda rc: rc["order"])
        for rc, label in zip(roll_calls, final_vote_only(roll_calls)):
            yield self._make_vote(session, "upper", rc, rc["key"], rc["sources"], label)

    def scrape(self, chamber=None, session=None):
        if chamber in ["upper", None]:
            yield from self._scrape_upper_chamber(session)
        if chamber in ["lower", None]:
            yield from self._scrape_lower_chamber(session)
