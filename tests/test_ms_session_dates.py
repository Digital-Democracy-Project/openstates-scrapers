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

One other entry breaks the rule and is left alone here (the ticket changes only 2026): 20093E,
the 2009 Third Extraordinary Session, ends "2013-06-27". The legislature's site gives no sine die
date for it (its last legislative action is 07/10, billstatus.ls.state.ms.us/20093E/pdf/
all_measures/allmsrs.xml), so its end-year check alone is marked as a known failure until a follow-up sets a cited date;
the mark is strict, so the test reports it once that entry is fixed.

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
KNOWN_WRONG_END = {
    "20093E": "end_date 2013-06-27; no cited end date yet (follow-up to OPEN-732)"
}


def _year(session):
    year = session["identifier"][:4]
    assert year.isdigit()
    return int(year)


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_start_falls_in_the_identifiers_year_and_precedes_end(session):
    start = date.fromisoformat(session["start_date"])
    assert start.year == _year(session)
    assert start <= date.fromisoformat(session["end_date"])


def _end_param(session):
    reason = KNOWN_WRONG_END.get(session["identifier"])
    marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
    return pytest.param(session, id=session["identifier"], marks=marks)


@pytest.mark.parametrize("session", [_end_param(s) for s in SESSIONS])
def test_end_falls_in_the_identifiers_year(session):
    assert date.fromisoformat(session["end_date"]).year == _year(session)


def test_2026_regular_session_dates_are_the_legislatures():
    session = next(s for s in SESSIONS if s["identifier"] == "2026")
    assert (session["start_date"], session["end_date"]) == ("2026-01-06", "2026-04-15")
