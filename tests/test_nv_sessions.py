"""OPEN-606: Nevada's 84th (2027) session becomes the active session on its start date.

Until 2027-02-01 the 2025 special session (2025Special36) stays the only active session
(Ramon, 2026-11-16: "Special session only now"). openstates-core scrapes the sessions marked
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
def test_before_84_starts_only_the_2025_special_is_active(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"2025Special36"}


@pytest.mark.parametrize("day", [datetime.date(2027, 2, 1), datetime.date(2027, 3, 15)])
def test_84_is_active_from_its_start(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"84"}


def test_the_switch_date_is_84s_own_start_date():
    session_84 = next(
        s for s in nv.Nevada.legislative_sessions if s["identifier"] == "84"
    )
    assert session_84["start_date"] == "2027-02-01"
    assert session_84["extras"]["session_slug"] == "84th2027"
