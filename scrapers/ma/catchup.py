"""OPEN-609: which Massachusetts bills a catch-up run reads, and what it remembers between runs.

malegislature.gov has no "changed since" list (OPEN-133), so a run used to read all ~11,900 bills (10-14 h).
Measured over 2026-09-21 to 11-15 against our own data (ddp-open-states notes/ma-journal-change-signal-20261117.md),
four cheap sources together name 98.3% of each week's changed bills (94.0% over the 2026-03-02 to 04-26 formal
session, where most of the rest are committee reporting-date extensions, which the journals do not list by bill):

* the House and Senate daily journals (99.5% of floor activity, 68% of all changes on their own);
* bills new in the Documents list since the last run (the new filings and dockets, 44% of the week's activity);
* the Session Laws page (governor signings);
* hearings posted since the last run (hearing notices).

The journals are posted 0-6 days after a sitting (House) and edited for up to 15 (Senate), so a run re-reads
every journal dated in the 21 days before start=. The new-bill and hearing diffs need the last run's lists: this
module keeps them in one small file in the cache directory (on Fargate the collector carries it between runs). A
periodic full walk stays the backstop for the rest and for format changes.
"""
import datetime
import json
import os
import re

import lxml.html
from openstates import settings
from openstates.utils.transformers import fix_bill_id

JOURNAL_LOOKBACK = datetime.timedelta(days=21)
# The backstop: a whole run walks every bill when the last full walk is at least this old (Ramon's choice; 28 days
# is every fourth weekly run).
FULL_WALK_EVERY = datetime.timedelta(days=28)

# --- the journals: bill numbers named in the text ---------------------------------------------------------------

_NUM = r"\d{1,5}"
_NUM_LIST = rf"{_NUM}(?:\s*(?:,\s*(?:and\s+)?|and\s+|to\s+|through\s+){_NUM})*"
# "House, No. 5719", "Senate, Nos. 2950 and 2951", "House, Nos. 5525, 5557, 5579 and 5642", "House Bill No. 12"
_BILL_REF_RE = re.compile(
    rf"\b(House|Senate)\s*,?\s*(?:Bills?\s+|documents?\s+)?"
    rf"(?:Nos?\.|numbered|(?<=document )|(?<=documents ))\s*({_NUM_LIST})",
    re.I,
)
_RANGE_RE = re.compile(rf"({_NUM})\s*(?:to|through)\s*({_NUM})")
# the Senate prints each paper's docket number in the margin ("SD4349"); the House prints none
_DOCKET_RE = re.compile(r"\b(HD|SD)\s?(\d{2,5})\b")
_PAGE_FURNITURE_RE = re.compile(
    r"\s*(UNCORRECTED PROOF\.?|\d{1,4}|JOURNAL OF THE (HOUSE|SENATE)\.?)\s*"
)


def _main_column(line):
    """A journal line without its margin note (pdftotext -layout puts the note right of the text, after a gap of 4+
    spaces past column 45), so a note's words never join the next line's "House, No."."""
    gap = re.search(r"\S(\s{4,})\S", line[45:])
    return line[: 45 + gap.start() + 1] if gap else line


def journal_bills(text):
    """Bill and docket numbers ("H 5525", "SD 4349") a journal's text (pdftotext -layout) names."""
    kept = []
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        # blank lines, margin-only lines and page headers
        if not line.strip() or indent >= 60 or _PAGE_FURNITURE_RE.fullmatch(line):
            continue
        kept.append(_main_column(line))
    flat = re.sub(r"\s+", " ", "\n".join(kept))
    # a number hyphenated across a line break
    flat = re.sub(r"(\d)- (\d)", r"\1\2", flat)
    found = set()
    for chamber, numbers in _BILL_REF_RE.findall(flat):
        prefix = "H" if chamber.lower() == "house" else "S"
        listed = re.findall(_NUM, numbers)
        # "Nos. 10 to 14" lists every paper between; a wider span is not a list of papers
        for low, high in _RANGE_RE.findall(numbers):
            if 0 < int(high) - int(low) <= 50:
                listed += [str(n) for n in range(int(low), int(high) + 1)]
        found.update("{} {}".format(prefix, int(n)) for n in listed)
    found.update("{} {}".format(kind, int(n)) for kind, n in _DOCKET_RE.findall(text))
    return found


# --- the Session Laws page: bills the governor approved ---------------------------------------------------------

_BILL_LINK_RE = re.compile(r"^/Bills/(\d+)/([A-Za-z]+\d+)")
_APPROVED_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def session_law_bills(html, session_number, since):
    """(bills of `session_number` whose chapter the governor approved on or after `since`, chapters on the page)."""
    page = lxml.html.fromstring(html)
    chapters = page.xpath('//span[contains(@class, "sessionLaw")]')
    found = set()
    for law in chapters:
        approved = _APPROVED_RE.search(
            " ".join(law.xpath('.//span[contains(@class, "governor")]//text()'))
        )
        if not approved:
            continue
        on = datetime.datetime.strptime(approved.group(1), "%B %d, %Y").date()
        if on < since:
            continue
        for href in law.xpath('.//a[contains(@class, "bill")]/@href'):
            link = _BILL_LINK_RE.match(href)
            if link and link.group(1) == session_number:
                found.add(fix_bill_id(link.group(2)))
    return found, len(chapters)


# --- hearings ----------------------------------------------------------------------------------------------------


def hearing_bills(detail, session_number):
    """Bills and dockets on a hearing's agenda (/api/Hearings/{id})."""
    found = set()
    for agenda in detail.get("HearingAgendas") or []:
        for doc in agenda.get("DocumentsInAgenda") or []:
            if str(doc.get("GeneralCourtNumber")) != session_number:
                continue
            for number in (doc.get("BillNumber"), doc.get("DocketNumber")):
                if number:
                    found.add(fix_bill_id(number))
    return found


# --- what a run remembers ----------------------------------------------------------------------------------------


def state_path(session):
    """ma_catchup_194.json in the cache directory (the collector's memory carries ma_catchup_*.json on Fargate)."""
    return os.path.join(
        settings.CACHE_DIR, "ma_catchup_{}.json".format(re.sub(r"\D", "", session))
    )


def load_state(path):
    """The last whole run's record, or None when there is none or it cannot be read (the caller then walks)."""
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        return {
            "bills": set(state["bills"]),
            "hearings": None if state["hearings"] is None else set(state["hearings"]),
            "full_walk_on": datetime.date.fromisoformat(state["full_walk_on"]),
            "retry": set(state["retry"]),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_state(path, bills, hearings, full_walk_on, retry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {
                "bills": sorted(bills),
                "hearings": None if hearings is None else sorted(hearings),
                "full_walk_on": full_walk_on.isoformat(),
                "retry": sorted(retry),
            },
            f,
        )
    os.replace(tmp, path)


def months(first, last):
    """The first day of every month from `first`'s to `last`'s."""
    month = first.replace(day=1)
    while month <= last:
        yield month
        month = (month + datetime.timedelta(days=32)).replace(day=1)
