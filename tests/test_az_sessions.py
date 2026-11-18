"""OPEN-632: Arizona's 2027 session (58th Legislature, First Regular) is listed and becomes the
active session on its start date.

azleg added "2027 - Fifty-eighth Legislature - First Regular Session" (session id 131) to its
session dropdown, and every Arizona run failed in openstates-core's check_session_list before
reading a bill. Until 2027-01-11 (the second Monday of January) the 2026 session stays the only
active session. openstates-core scrapes the sessions marked active when no session= is given,
which is how our runs call it (session_arg: null), so the active flags below are exactly what a
run would scrape on that day.
"""
import datetime
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import az  # noqa: E402
from az import session_metadata  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "az_open632", "azleg_session_select.html"
)


def _az_on(monkeypatch, day):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(datetime, "date", FrozenDate)
    return importlib.reload(az)


def _active_on(monkeypatch, day):
    module = _az_on(monkeypatch, day)
    return {
        s["identifier"] for s in module.Arizona.legislative_sessions if s.get("active")
    }


@pytest.fixture(autouse=True)
def _reload_with_real_date(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(az)


@pytest.mark.parametrize(
    "day", [datetime.date(2026, 11, 18), datetime.date(2027, 1, 10)]
)
def test_before_2027_starts_only_2026_is_active(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"57th-2nd-regular"}


@pytest.mark.parametrize("day", [datetime.date(2027, 1, 11), datetime.date(2027, 4, 1)])
def test_2027_is_active_from_its_start(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"58th-1st-regular"}


def test_2027_carries_azlegs_name_and_session_id():
    session_2027 = next(
        s
        for s in az.Arizona.legislative_sessions
        if s["identifier"] == "58th-1st-regular"
    )
    assert (
        session_2027["_scraped_name"]
        == "2027 - Fifty-eighth Legislature - First Regular Session"
    )
    assert session_2027["start_date"] == "2027-01-11"
    # The value of azleg's <option> for 2027; bills.py posts it to setsession.php.
    assert session_2027["extras"]["session_id"] == 131
    # events.py reads the id from session_metadata only.
    assert session_metadata.session_id_meta_data["58th-1st-regular"] == 131


class _FakeResponse:
    def __init__(self, text):
        self.text = text


@pytest.mark.parametrize(
    "day,active",
    [
        (datetime.date(2026, 11, 18), {"57th-2nd-regular"}),
        (datetime.date(2027, 1, 11), {"58th-1st-regular"}),
    ],
)
def test_session_list_check_passes_with_azlegs_real_list(monkeypatch, day, active):
    # The dropdown azleg served on 2026-11-18, the day the live run failed.
    with open(FIXTURE, encoding="utf-8") as f:
        page = f.read()
    module = _az_on(monkeypatch, day)
    monkeypatch.setattr(
        module.requests.Session, "get", lambda self, url, **kw: _FakeResponse(page)
    )
    jurisdiction = module.Arizona()
    scraped = jurisdiction.get_session_list()
    assert "2027 - Fifty-eighth Legislature - First Regular Session" in scraped
    # openstates-core's own check, the one that raised the CommandError; it returns the
    # active session identifiers when every listed session is known.
    assert check_session_list(jurisdiction) == active
