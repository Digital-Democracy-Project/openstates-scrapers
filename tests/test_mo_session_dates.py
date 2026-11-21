"""OPEN-737: every Missouri session ends on or after it starts, in the year its identifier names.

The import copies each entry's start_date and end_date onto the stored session, and api-v3's
current-session logic and the broker's map year read them. 2022S1 (the 2022 1st Extraordinary
Session) was dated 2022-09-15 to "2021-09-23", ending a year before it began. Its end date is now
the legislature's own (read 2026-11-21): both chambers adjourned sine die on October 4, 2022,

* Senate journal, eighth day, Tuesday, October 4, 2022 (senate.mo.gov/22info/Journals/
  T1Day08100454-58.pdf): "the Senate of the First Extra Session of the Second Regular Session of
  the 101st General Assembly adjourned sine die";
* House journal, ninth day, Tuesday, October 4, 2022 (documents.house.mo.gov/billtracking/
  bills223/jrnpdf/jrn009.pdf): the Speaker declared the House "adjourned sine die as of
  October 4, 2022".

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


def test_2022_first_extraordinary_session_ends_on_the_legislatures_sine_die():
    session = next(s for s in SESSIONS if s["identifier"] == "2022S1")
    assert session["end_date"] == "2022-10-04"
