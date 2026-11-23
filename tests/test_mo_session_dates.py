"""Missouri session dates: each session is dated in its own year (OPEN-737) and runs from its
first legislative day to its official close as the journals record it (OPEN-791).

The import copies each entry's start_date and end_date onto the stored session, and api-v3's
current-session logic and the broker's map year read them.

OPEN-791 (read 2026-11-23; Ramon's rule of 2026-11-22: a session ends on the legislature's official
close, sine die, even when set later than the last sitting). Sources are the Senate journals
(senate.mo.gov/{yy}info/Journals/..., listed on senate.mo.gov/journallist) and the House journals
(documents.house.mo.gov/billtracking/bills{code}/jrnpdf/jrnNNN.pdf):

* A regular session closes at midnight on May 30 (Mo. Const. art. III, sec. 20, "adjournment at
  midnight on May thirtieth"). The House's last regular-session journal says so every year: the
  Speaker declared the House "adjourned [sine die] as of midnight, May 30, <year>, in accordance
  with the Constitution". The Senate's last journal either "adjourned sine die, pursuant to the
  Constitution" on an earlier day (2020, 2022, 2026) or "adjourned pursuant to the Constitution"
  (2019, 2021, 2023, 2025), or adjourned sine die on May 30 itself (2024). The September veto
  session is not a separate session in the scraper's list (OPEN-736) and does not move the close.
* An extraordinary session closes on the later of the two chambers' sine die (the House declares
  its own "adjourned sine die as of <date>").

Each close below names the journal that records it. Each start is the first day of the chamber that
met first (the Senate's RDay01/T1Day01/T2Day01 journal or the House's jrn001); the only start the
journals showed wrong was 2022S1's (2022-09-15, now 2022-09-14).

The session list is read from the package's source, as test_ms_session_dates.py does: importing
the mo package needs DDP's openstates-core.
"""
import ast
import os
from datetime import date

import pytest

INIT = os.path.join(os.path.dirname(__file__), "..", "scrapers", "mo", "__init__.py")


def _sessions():
    tree = ast.parse(open(INIT).read())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "legislative_sessions"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("mo has no legislative_sessions")


SESSIONS = _sessions()
IDS = [s["identifier"] for s in SESSIONS]


def _year(session):
    year = session["identifier"][:4]
    assert year.isdigit()
    return int(year)


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_start_falls_in_the_identifiers_year_and_precedes_end(session):
    start = date.fromisoformat(session["start_date"])
    assert start.year == _year(session)
    assert start <= date.fromisoformat(session["end_date"])


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_end_falls_in_the_identifiers_year(session):
    assert date.fromisoformat(session["end_date"]).year == _year(session)


# identifier: (start, official close). "S" is the Senate journal file under
# senate.mo.gov/{yy}info/Journals/, "H" the House journal bills{code}/jrnpdf/jrnNNN.pdf.
MO_JOURNAL_DATES = {
    # S RDay7105291686-1690 (May 29: adjourned pursuant to the Constitution);
    # H bills191 jrn073: "adjourned as of midnight, May 30, 2019"
    "2019": ("2019-01-09", "2019-05-30"),
    # S T1Day06091627 (Sep 16: adjourned sine die); H bills193 jrn005: "adjourned sine die as of
    # September 24, 2019"
    "2019S1": ("2019-09-09", "2019-09-24"),
    # S RDay5905271215-1218 (May 27: adjourned sine die); H bills201 jrn065: "adjourned sine die
    # as of midnight, May 30, 2020"
    "2020": ("2020-01-08", "2020-05-30"),
    # S T1Day13091677-79 and H bills203 jrn012: both adjourned sine die September 16, 2020
    "2020S1": ("2020-07-27", "2020-09-16"),
    # S T2Day07121036-37 (Dec 10: adjourned sine die); H bills204 jrn010: "adjourned sine die as
    # of December 16, 2020"
    "2020S2": ("2020-11-05", "2020-12-16"),
    # S RDay6905252072-2082 (May 25: adjourned pursuant to the Constitution);
    # H bills211 jrn073: "adjourned as of midnight, May 30, 2021"
    "2021": ("2021-01-06", "2021-05-30"),
    # S T1Day05063023-25 and H bills213 jrn003: both adjourned sine die June 30, 2021
    "2021S1": ("2021-06-23", "2021-06-30"),
    # S RDay6505182868-2874 (May 18: adjourned sine die); H bills221 jrn072: "adjourned sine die
    # as of midnight, May 30, 2022"
    "2022": ("2022-01-05", "2022-05-30"),
    # first day Wednesday, September 14, 2022 in both S T1Day0109141-7 and H bills223 jrn001;
    # both adjourned sine die October 4, 2022 (S T1Day08100454-58, H bills223 jrn009; OPEN-737)
    "2022S1": ("2022-09-14", "2022-10-04"),
    # S RDay7005302796-2810 (May 30: adjourned pursuant to the Constitution);
    # H bills231 jrn073: "adjourned as of midnight, May 30, 2023"
    "2023": ("2023-01-04", "2023-05-30"),
    # S RDay6805301307-1318 (May 30: adjourned sine die); H bills241 jrn078: "adjourned sine die
    # as of midnight, May 30, 2024"
    "2024": ("2024-01-03", "2024-05-30"),
    # S RDay7205301778-1785 (May 30: adjourned pursuant to the Constitution);
    # H bills251 jrn073: "adjourned as of midnight, May 30, 2025"
    "2025": ("2025-01-08", "2025-05-30"),
    # Senate first day June 2 (S T1Day0106021-8; the House convened June 9); S T1Day05061131-33
    # and H bills253 jrn003: both adjourned sine die June 11, 2025
    "2025S1": ("2025-06-02", "2025-06-11"),
    # House first day September 3 (H bills254 jrn001; the Senate convened September 10);
    # S T2Day03091223-31 and H bills254 jrn007: both adjourned sine die September 12, 2025
    "2025S2": ("2025-09-03", "2025-09-12"),
    # S RDay7005281892-1909 (May 28: adjourned sine die); H bills261 jrn072: "adjourned sine die
    # as of midnight, May 30, 2026"
    "2026": ("2026-01-07", "2026-05-30"),
}


def test_every_session_is_pinned_to_its_journals():
    assert sorted(IDS) == sorted(MO_JOURNAL_DATES)


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_session_runs_to_its_official_close(session):
    assert (session["start_date"], session["end_date"]) == MO_JOURNAL_DATES[
        session["identifier"]
    ]
