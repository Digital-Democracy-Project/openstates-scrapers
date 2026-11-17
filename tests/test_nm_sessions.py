"""OPEN-619: New Mexico's 2027 Regular session becomes the active session on its start date.

Until 2027-01-19 (the third Tuesday of January) the 2026 Regular session stays the only active
session. openstates-core scrapes the sessions marked active when no session= is given, which is
how our runs call it (session_arg: null), so the active flags below are exactly what a run would
scrape on that day.
"""
import datetime
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import nm  # noqa: E402
from nm.bills import session_slug  # noqa: E402


def _active_on(monkeypatch, day):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(datetime, "date", FrozenDate)
    module = importlib.reload(nm)
    return {
        s["identifier"]
        for s in module.NewMexico.legislative_sessions
        if s.get("active")
    }


@pytest.fixture(autouse=True)
def _reload_with_real_date(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(nm)


@pytest.mark.parametrize(
    "day", [datetime.date(2026, 11, 17), datetime.date(2027, 1, 18)]
)
def test_before_2027_starts_only_2026_is_active(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"2026"}


@pytest.mark.parametrize("day", [datetime.date(2027, 1, 19), datetime.date(2027, 3, 1)])
def test_2027_is_active_from_its_start(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"2027"}


def test_2027_is_listed_with_its_own_start_date_and_site_folder():
    session_2027 = next(
        s for s in nm.NewMexico.legislative_sessions if s["identifier"] == "2027"
    )
    assert session_2027["_scraped_name"] == "2027 Regular"
    assert session_2027["start_date"] == "2027-01-19"
    # Inferred from every earlier year; re-check once nmlegis.gov publishes the folder.
    assert session_slug("2027") == "27%20Regular"
