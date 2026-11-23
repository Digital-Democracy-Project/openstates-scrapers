"""OPEN-732: every Mississippi session is dated in the year its identifier names.

The import copies each entry's start_date and end_date onto the stored session, and api-v3's
current-session logic and the broker's map year read them, so a 2026 session dated 2025 sorts and
matches as the wrong year. The 2026 Regular Session's dates are the legislature's own (read
2026-11-21 on billstatus.ls.state.ms.us):

* start 2026-01-06: the first 2026 Daily Action Report (2026/pdf/list_dar.htm, 01062026.xml),
  and the House calendar for April 15, 2026 (2026/pdf/misc/h_cal.htm) calls it the "100th
  CALENDAR DAY";
* end 2026-04-15: House Concurrent Resolution 64 (documents/2026/pdf/HC/HC0064SG.pdf, adopted by
  both chambers 03/30-03/31) extends the session and sets sine die "at 11:59 p.m. on Wednesday,
  April 15, 2026".

OPEN-759 (read 2026-11-22): 20093E, the 2009 Third Extraordinary Session, ended "2013-06-27",
breaking the rule. The legislature's site gives no sine die date for it; every floor action in
its bill histories (billstatus.ls.state.ms.us/20093E/pdf/history/) is dated 07/10/2009, the
House calendar's "1st LEGISLATIVE DAY", so it ends 2009-07-10, the last day the chambers met
(Ramon 2026-11-22, "Fix it to last action"). The Senate President's 07/13 signing of HB 1 and
HB 2 is not counted as a sitting.

OPEN-792 (read 2026-11-23): 20261E, the 2026 First Extraordinary Session, was stored as starting
"2026-07-14", the day Governor Reeves issued the call, not the day the Legislature met under
it. The call convened it "tomorrow, July 15, at 3pm" (the Governor's statement of 2026-07-14, as reported by
WLBT/WLOX that day). The legislature's own record agrees: the first Daily Action Report
(20261E/pdf/list_dar.htm, 07152026.xml) carries the House and Senate roll calls of 07/15/2026,
there is no report for 07/14, and the House and Senate calendars for July 16
(20261E/pdf/misc/h_cal.htm, s_cal.htm) call it the "2nd CALENDAR DAY". The end stays 2026-07-17.

The session list is read from the package's source, as test_session_classification.py does:
importing the ms package needs DDP's openstates-core.
"""
import ast
import os
from datetime import date

import pytest

INIT = os.path.join(os.path.dirname(__file__), "..", "scrapers", "ms", "__init__.py")


def _sessions():
    tree = ast.parse(open(INIT).read())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "legislative_sessions"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("ms has no legislative_sessions")


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


def test_2026_regular_session_dates_are_the_legislatures():
    session = next(s for s in SESSIONS if s["identifier"] == "2026")
    assert (session["start_date"], session["end_date"]) == ("2026-01-06", "2026-04-15")


def test_2009_third_extraordinary_session_ends_on_its_last_floor_day():
    session = next(s for s in SESSIONS if s["identifier"] == "20093E")
    assert (session["start_date"], session["end_date"]) == ("2009-07-10", "2009-07-10")


def test_2026_first_extraordinary_session_starts_the_day_it_convened():
    session = next(s for s in SESSIONS if s["identifier"] == "20261E")
    assert (session["start_date"], session["end_date"]) == ("2026-07-15", "2026-07-17")
