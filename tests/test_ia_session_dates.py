"""OPEN-743, OPEN-745: every Iowa regular session runs from the day it convened to the day it
adjourned sine die, one session per year, and no regular session's dates hold an extraordinary
session's day (nor an extraordinary session's dates a regular day).

The import copies each entry's start_date and end_date onto the stored session, and api-v3's
current-session logic and the broker's map year read them. OPEN-743 set each two-year General
Assembly's end to its second year's sine die. OPEN-745 (Ramon 2026-11-21: "regular session and
special session are two different things. don't ever mix their dates together", then "Two yearly
sessions, bills by filing year") mirrors Iowa: its journals name each year as its own regular
session ("Ninety-first General Assembly of Iowa, 2025 Regular Session", House journal of
2025-01-13; "2026 Regular Session", House journal of 2026-01-12), so each year is a session.

Each end date below is the day the legislature itself declared that year's regular session
adjourned sine die, read 2026-11-21 in the FINAL ADJOURNMENT paragraph of the daily journals on
legis.iowa.gov (docs/publications/HJNL/<date>_HJNL.pdf and SJNL/<date>_SJNL.pdf). Where the two
chambers' days differ, the later one is the year's last adjournment:

* 2011-06-30: House and Senate journals of June 30, 2011 ("the day of June 30, 2011");
* 2012-05-09: House and Senate journals of May 9, 2012 ("the day of May 9, 2012 having arrived");
* 2013-05-23: House journal of May 23, 2013 and Senate journal of May 22, 2013, both "the day of
  May 23, 2013";
* 2014-05-02: Senate journal of May 2, 2014 ("the day of May 2, 2014, having arrived"); the
  House adjourned earlier, at 5:54 a.m. on May 1 (House journal of April 30, 2014);
* 2015-06-05: House and Senate journals of June 5, 2015;
* 2016-04-29: House and Senate journals of April 29, 2016;
* 2017-04-22: House journal of April 21, 2017 and Senate journal of April 22, 2017, both "the day
  of (Saturday,) April 22, 2017";
* 2018-05-05: House and Senate journals of May 5, 2018;
* 2019-04-27: House and Senate journals of April 27, 2019;
* 2020-06-14: House and Senate journals of June 14, 2020 (the session resumed in June);
* 2021-05-19: House and Senate journals of May 19, 2021 ("the day of Wednesday, May 19, 2021");
* 2022-05-24: House and Senate journals of May 24, 2022;
* 2023-05-04: House and Senate journals of May 4, 2023 ("the day of Thursday, May 4, 2023");
* 2024-04-19: House and Senate journals of April 19, 2024 (the House at 4:23 a.m., after an
  overnight sitting; both chambers declare "the day of April 19, 2024");
* 2025-05-15: House journal of May 14, 2025 ("the day of Wednesday, May 14, 2025", at 6:31 a.m.)
  and Senate journal of May 14, 2025 ("the day of May 15, 2025");
* 2026-05-03: House journal of May 2, 2026 and Senate journal of May 3, 2026 ("the day of
  Sunday, May 3, 2026, having arrived"); the Governor's proclamation in the House journal of
  October 2, 2026 also says the 2026 regular session adjourned sine die on May 3, 2026.

Each start date is the day of the first House and Senate journal on that year's journal list
(legislation/journals/<chamber>?ga=<ga>&session=1|2), which is the second Monday of January every
year (Iowa Constitution Art. III, Sec. 2).

2027 and 2028 (General Assembly 92, OPEN-744) have not met. They start on the second Monday of
January. No law fixes when they end, so their end dates are placeholders until the journals
record their sine dies: the last day Iowa Code Sec. 2.10(1) pays members a per diem for, the
110th calendar day of the first regular session and the 100th of the second.

Each extraordinary session (OPEN-744) met on one day, convened by the Governor's proclamation and
adjourned sine die the same day (the House and Senate journals of that day).

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


ALL_SESSIONS = _sessions()
SESSIONS = [s for s in ALL_SESSIONS if s["classification"] == "primary"]
SPECIALS = [s for s in ALL_SESSIONS if s["classification"] == "special"]
IDS = [s["identifier"] for s in SESSIONS]
SPECIAL_IDS = [s["identifier"] for s in SPECIALS]

# The day each year's regular session adjourned sine die.
SINE_DIE = {
    "2011": "2011-06-30",
    "2012": "2012-05-09",
    "2013": "2013-05-23",
    "2014": "2014-05-02",
    "2015": "2015-06-05",
    "2016": "2016-04-29",
    "2017": "2017-04-22",
    "2018": "2018-05-05",
    "2019": "2019-04-27",
    "2020": "2020-06-14",
    "2021": "2021-05-19",
    "2022": "2022-05-24",
    "2023": "2023-05-04",
    "2024": "2024-04-19",
    "2025": "2025-05-15",
    "2026": "2026-05-03",
}
# The day each General Assembly first met, and its number (the site's ga=); its second year
# convened on the second Monday of January of the next year.
GENERAL_ASSEMBLY = {
    "2011": 84,
    "2013": 85,
    "2015": 86,
    "2017": 87,
    "2019": 88,
    "2021": 89,
    "2023": 90,
    "2025": 91,
    "2027": 92,
}
# Regular sessions that have not yet adjourned sine die (none at 2026-11-21).
STILL_SITTING = set()
# Regular sessions that have not yet met (OPEN-744); their dates follow the rules checked in
# test_a_session_not_yet_met_follows_the_rules below.
NOT_YET_MET = {"2027", "2028"}

# OPEN-745: each extraordinary session's one day, its General Assembly, and its name.
EXTRAORDINARY_DAY = {
    "2021s1": ("2021-10-05", 89, "2021 Extraordinary Session"),
    "2021s2": ("2021-10-28", 89, "2021 Second Extraordinary Session"),
    "2023s1": ("2023-07-11", 90, "2023 Extraordinary Session"),
    "2026s1": ("2026-10-02", 91, "2026 Extraordinary Session"),
}


def _second_monday_of_january(year):
    mondays = [
        date(year, 1, d) for d in range(1, 15) if date(year, 1, d).weekday() == 0
    ]
    return mondays[1]


def _year(session):
    assert session["identifier"].isdigit() and len(session["identifier"]) == 4
    return int(session["identifier"])


def _first_year(year):
    """The first year of the General Assembly `year` belongs to."""
    return year if str(year) in GENERAL_ASSEMBLY else year - 1


def test_one_regular_session_per_year():
    years = [_year(s) for s in SESSIONS]
    assert years == list(range(2011, 2029))


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_a_regular_session_is_named_and_filed_as_iowa_does(session):
    year = _year(session)
    assert session["name"] == "{} Regular Session".format(year)
    ga = GENERAL_ASSEMBLY[str(_first_year(year))]
    # filed under its General Assembly, on the site's list and in its ga=
    assert session["_scraped_name"] == "General Assembly: {}".format(ga)
    assert session["extras"]["ordinal"] == ga


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_start_is_the_second_monday_of_january_and_precedes_end(session):
    start = date.fromisoformat(session["start_date"])
    assert start == _second_monday_of_january(_year(session))
    assert start <= date.fromisoformat(session["end_date"])


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_end_falls_in_its_own_year(session):
    assert date.fromisoformat(session["end_date"]).year == _year(session)


@pytest.mark.parametrize("session", SESSIONS, ids=IDS)
def test_end_is_the_years_sine_die(session):
    # Every year needs a cited sine die above; one still sitting has none yet and is listed in
    # STILL_SITTING instead (its end year is still checked above).
    if session["identifier"] in STILL_SITTING | NOT_YET_MET:
        return
    assert session["identifier"] in SINE_DIE, "no cited sine die"
    assert session["end_date"] == SINE_DIE[session["identifier"]]


@pytest.mark.parametrize("identifier", sorted(NOT_YET_MET))
def test_a_session_not_yet_met_follows_the_rules(identifier):
    (session,) = [s for s in SESSIONS if s["identifier"] == identifier]
    year = _year(session)
    start = _second_monday_of_january(year)
    assert session["start_date"] == start.isoformat()
    # placeholder end: the last day Iowa Code Sec. 2.10(1) pays a per diem for, 110 calendar
    # days in the first regular session and 100 in the second (no law fixes the end)
    days = 110 if _first_year(year) == year else 100
    assert session["end_date"] == (start + timedelta(days=days - 1)).isoformat()
    # not scraped until its bills appear on the site
    assert session["active"] is False


def test_the_sitting_general_assemblys_two_years_are_switched_on():
    # 2025 bills carried over get their 2026 actions only while 2025 is scraped too
    active = {s["identifier"] for s in ALL_SESSIONS if s.get("active")}
    assert active == {"2025", "2026"}


def test_every_extraordinary_session_has_its_own_entry():
    assert sorted(SPECIAL_IDS) == sorted(EXTRAORDINARY_DAY)


@pytest.mark.parametrize("session", SPECIALS, ids=SPECIAL_IDS)
def test_an_extraordinary_session_spans_only_its_own_day(session):
    day, ga, name = EXTRAORDINARY_DAY[session["identifier"]]
    assert (session["start_date"], session["end_date"]) == (day, day)
    assert session["name"] == name
    assert session["active"] is False
    assert session["extras"]["ordinal"] == ga
    # the house pattern: <year>s<n>
    assert session["identifier"].startswith(day[:4] + "s")


@pytest.mark.parametrize("session", SPECIALS, ids=SPECIAL_IDS)
def test_no_regular_session_holds_an_extraordinary_day(session):
    # literal: no regular session's stored dates include the extraordinary day, and the
    # extraordinary session's stored dates include no regular day
    first = date.fromisoformat(session["start_date"])
    last = date.fromisoformat(session["end_date"])
    for regular in SESSIONS:
        start = date.fromisoformat(regular["start_date"])
        end = date.fromisoformat(regular["end_date"])
        assert end < first or start > last, regular["identifier"]


@pytest.mark.parametrize("session", SPECIALS, ids=SPECIAL_IDS)
def test_bills_are_taken_from_the_day_after_the_legislature_last_sat(session):
    # the scrapers give an extraordinary session the bills first acted on from this day to its
    # end: the day after the legislature's previous sitting, whether that was the regular
    # session (its cited sine die) or an earlier extraordinary session
    day = date.fromisoformat(session["start_date"])
    last_sat = max(
        [
            date.fromisoformat(d)
            for d in SINE_DIE.values()
            if date.fromisoformat(d) < day
        ]
        + [
            date.fromisoformat(d)
            for d, _, _ in EXTRAORDINARY_DAY.values()
            if date.fromisoformat(d) < day
        ]
    )
    assert (
        session["extras"]["bills_filed_from"]
        == (last_sat + timedelta(days=1)).isoformat()
    )
