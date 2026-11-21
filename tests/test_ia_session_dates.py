"""OPEN-743: every Iowa General Assembly ends on its second year's sine die, not its first's.

The import copies each entry's start_date and end_date onto the stored session, and api-v3's
current-session logic and the broker's map year read them. Iowa's legislature meets in both
years of a two-year General Assembly, but 2017-2018, 2019-2020, 2021-2022, 2023-2024 and
2025-2026 ended on a first-year or wrong date (2025-2026 on 2025-04-22), so their second-year
meeting fell after the recorded end.

Each end date below is the day the legislature itself declared the regular session adjourned
sine die, read 2026-11-21 in the FINAL ADJOURNMENT paragraph of the daily journals on
legis.iowa.gov (docs/publications/HJNL/<date>_HJNL.pdf and SJNL/<date>_SJNL.pdf). Where the two
chambers' days differ, the later one is the General Assembly's last adjournment:

* 2012-05-09: House and Senate journals of May 9, 2012 ("the day of May 9, 2012 having arrived");
* 2014-05-02: Senate journal of May 2, 2014 ("the day of May 2, 2014, having arrived"); the
  House adjourned earlier, at 5:54 a.m. on May 1 (House journal of April 30, 2014);
* 2016-04-29: House and Senate journals of April 29, 2016;
* 2018-05-05: House and Senate journals of May 5, 2018;
* 2020-06-14: House and Senate journals of June 14, 2020 (the session resumed in June);
* 2022-05-24: House and Senate journals of May 24, 2022;
* 2024-04-19: House and Senate journals of April 19, 2024 (the House at 4:23 a.m., after an
  overnight sitting; both chambers declare "the day of April 19, 2024");
* 2026-05-03: House journal of May 2, 2026 and Senate journal of May 3, 2026 ("the day of
  Sunday, May 3, 2026, having arrived"); the Governor's proclamation in the House journal of
  October 2, 2026 also says the 2026 regular session adjourned sine die on May 3, 2026.

2027-2028 (General Assembly 92, OPEN-744) has not met: it starts on the second Monday of January
2027 (Iowa Constitution Art. III, Sec. 2) and its end date is the scheduled one, the 100th
calendar day of its second session (Iowa Code Sec. 2.10(1)), until the journals record its sine die.

The session list is read from the package's source, as test_mo_session_dates.py does: importing
the ia package needs DDP's openstates-core.
"""
import ast
import os
from datetime import date, timedelta

import pytest

INIT = os.path.join(os.path.dirname(__file__), "..", "scrapers", "ia", "__init__.py")


def _sessions():
    tree = ast.parse(open(INIT).read())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "legislative_sessions"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("ia has no legislative_sessions")


SESSIONS = _sessions()
IDS = [s["identifier"] for s in SESSIONS]

# The last day the legislature met in each General Assembly's second year (its sine die).
SECOND_YEAR_SINE_DIE = {
    "2011-2012": "2012-05-09",
    "2013-2014": "2014-05-02",
    "2015-2016": "2016-04-29",
    "2017-2018": "2018-05-05",
    "2019-2020": "2020-06-14",
    "2021-2022": "2022-05-24",
    "2023-2024": "2024-04-19",
    "2025-2026": "2026-05-03",
}
# General Assemblies that have not yet adjourned sine die (none at 2026-11-21).
STILL_SITTING = set()
# General Assemblies that have not yet met (OPEN-744); their dates follow the rules checked in
# test_a_general_assembly_not_yet_met_follows_the_rules below.
NOT_YET_MET = {"2027-2028"}


def _years(session):
    first, second = session["identifier"].split("-")
    assert first.isdigit() and second.isdigit()
    return int(first), int(second)


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_start_falls_in_the_first_year_and_precedes_end(session):
    start = date.fromisoformat(session["start_date"])
    assert start.year == _years(session)[0]
    assert start <= date.fromisoformat(session["end_date"])


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_end_falls_in_the_second_year(session):
    assert date.fromisoformat(session["end_date"]).year == _years(session)[1]


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_end_is_the_second_years_sine_die(session):
    # Every General Assembly needs a cited sine die above; one still sitting has none yet and
    # is listed in STILL_SITTING instead (its end year is still checked above).
    if session["identifier"] in STILL_SITTING | NOT_YET_MET:
        return
    assert session["identifier"] in SECOND_YEAR_SINE_DIE, "no cited sine die"
    assert session["end_date"] == SECOND_YEAR_SINE_DIE[session["identifier"]]


def _second_monday_of_january(year):
    mondays = [
        date(year, 1, d) for d in range(1, 15) if date(year, 1, d).weekday() == 0
    ]
    return mondays[1]


@pytest.mark.parametrize("identifier", sorted(NOT_YET_MET))
def test_a_general_assembly_not_yet_met_follows_the_rules(identifier):
    (session,) = [s for s in SESSIONS if s["identifier"] == identifier]
    first, second = _years(session)
    # Iowa Constitution Art. III, Sec. 2: the general assembly meets on the second Monday of
    # January of each year
    assert session["start_date"] == _second_monday_of_january(first).isoformat()
    # Iowa Code Sec. 2.10(1): the second regular session's scheduled length is 100 calendar
    # days, counted from its first day
    second_session = _second_monday_of_january(second)
    assert session["end_date"] == (second_session + timedelta(days=99)).isoformat()
    # not scraped until its bills appear on the site
    assert session["active"] is False
