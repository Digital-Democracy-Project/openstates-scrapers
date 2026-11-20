"""Nevada's sessions: the 84th (2027) is active now for its pre-filed bills (OPEN-659, Ramon
2026-11-20), and the 2025 special session (2025Special36) stays active beside it until the 84th
starts on 2027-02-01 (OPEN-606), then drops. openstates-core scrapes the sessions marked
active when no session= is given, which is how our runs call it (session_arg: null), so the
active flags below are exactly what a run would scrape on that day.
"""
import datetime
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import nv  # noqa: E402


def _active_on(monkeypatch, day):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(datetime, "date", FrozenDate)
    module = importlib.reload(nv)
    return {
        s["identifier"] for s in module.Nevada.legislative_sessions if s.get("active")
    }


@pytest.fixture(autouse=True)
def _reload_with_real_date(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(nv)


@pytest.mark.parametrize(
    "day", [datetime.date(2026, 11, 17), datetime.date(2027, 1, 31)]
)
def test_before_84_starts_84_and_the_2025_special_are_active(monkeypatch, day):
    # OPEN-659: 84's pre-filed bills are scraped now; the special session is not dropped yet
    assert _active_on(monkeypatch, day) == {"84", "2025Special36"}


@pytest.mark.parametrize("day", [datetime.date(2027, 2, 1), datetime.date(2027, 3, 15)])
def test_from_84s_start_only_84_is_active(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"84"}


def test_the_switch_date_is_84s_own_start_date():
    session_84 = next(
        s for s in nv.Nevada.legislative_sessions if s["identifier"] == "84"
    )
    assert session_84["start_date"] == "2027-02-01"
    assert session_84["extras"]["session_slug"] == "84th2027"
