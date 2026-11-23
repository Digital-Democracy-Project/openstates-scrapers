"""OPEN-793: every Hawaii regular session starts on its journals' first day and ends on the day
both chambers adjourned sine die (Ramon: the end is the official close).

Hawaii convenes on the third Wednesday of January (Constitution, Article III, Section 10). The
dates below are the date lines of the Senate journals, read 2026-11-23 from
data.capitol.hawaii.gov/sessions/journal/Senate/<year>/: the first day's journal
(SJ_<mm-dd-yyyy>_Day_01.pdf; 2026: ADVANCE_01-21-26_Day_01.pdf) and the last day's, which records
"declared the Senate ... adjourned Sine Die" (Day 60; 2020: Day 53; 2021: Day 55; 2026:
ADVANCE_05-08-26_Day_58.pdf).

Five stored dates differed and were corrected, each also read in the House Journal
(data.capitol.hawaii.gov/sessions/journal/House/<year>/):

* 2018 start 01-18 -> 01-17: "FIRST DAY, Wednesday, January 17, 2018" (SJ_01-17-2018_Day_01.pdf;
  2018 HJournal Final 2 Days 1-60 Gov.pdf, page 1);
* 2025 start 01-17 -> 01-15: "FIRST DAY, Wednesday, January 15, 2025" (SJ_01-15-2025_Day_01.pdf;
  2 2025 HJournal Days.pdf, page 1);
* 2013 end 05-03 -> 05-02: "SIXTIETH DAY, Thursday, May 2, 2013", adjourned Sine Die
  (SJ_05-02-2013_Day_60.pdf; the House file is named "HJournal Final 05-01-13 Day 60 p842.pdf"
  but its date line reads Thursday, May 2, 2013);
* 2014 end 05-02 -> 05-01: "SIXTIETH DAY, Thursday, May 1, 2014", adjourned Sine Die
  (SJ_05-01-2014_Day_60.pdf; HJournal Final 05-01-14 Day 60 p812.pdf);
* 2024 end 05-02 -> 05-03: "SIXTIETH DAY, Friday, May 3, 2024", adjourned Sine Die
  (SJ_05-03-2024_Day_60.pdf; 2024 HJournal Final 05-03-24 Day 60 p638.pdf).

The session list is read from the package's source, as test_ms_session_dates.py does.
"""
import ast
import os
from datetime import date

import pytest

INIT = os.path.join(os.path.dirname(__file__), "..", "scrapers", "hi", "__init__.py")

# identifier: (first day, sine die), from the journals
JOURNAL_DATES = {
    "2011 Regular Session": ("2011-01-19", "2011-05-05"),
    "2012 Regular Session": ("2012-01-18", "2012-05-03"),
    "2013 Regular Session": ("2013-01-16", "2013-05-02"),
    "2014 Regular Session": ("2014-01-15", "2014-05-01"),
    "2015 Regular Session": ("2015-01-21", "2015-05-07"),
    "2016 Regular Session": ("2016-01-20", "2016-05-05"),
    "2017 Regular Session": ("2017-01-18", "2017-05-04"),
    "2018 Regular Session": ("2018-01-17", "2018-05-03"),
    "2019 Regular Session": ("2019-01-16", "2019-05-02"),
    "2020 Regular Session": ("2020-01-15", "2020-07-10"),
    "2021 Regular Session": ("2021-01-20", "2021-04-29"),
    "2022 Regular Session": ("2022-01-19", "2022-05-05"),
    "2023 Regular Session": ("2023-01-18", "2023-05-04"),
    "2024": ("2024-01-17", "2024-05-03"),
    "2025": ("2025-01-15", "2025-05-02"),
    "2026": ("2026-01-21", "2026-05-08"),
}


def _regular_sessions():
    tree = ast.parse(open(INIT).read())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "legislative_sessions"
        ):
            sessions = ast.literal_eval(node.value)
            return {
                s["identifier"]: s
                for s in sessions
                if s.get("classification") == "primary"
            }
    raise AssertionError("hi has no legislative_sessions")


REGULAR = _regular_sessions()


def test_every_regular_session_is_pinned():
    assert sorted(REGULAR) == sorted(JOURNAL_DATES)


@pytest.mark.parametrize("identifier", sorted(JOURNAL_DATES))
def test_regular_session_dates_are_the_journals(identifier):
    session = REGULAR[identifier]
    assert (session["start_date"], session["end_date"]) == JOURNAL_DATES[identifier]


@pytest.mark.parametrize("identifier", sorted(JOURNAL_DATES))
def test_regular_session_starts_on_the_third_wednesday_of_january(identifier):
    start = date.fromisoformat(JOURNAL_DATES[identifier][0])
    assert (start.month, start.weekday(), (start.day - 1) // 7) == (1, 2, 2)
