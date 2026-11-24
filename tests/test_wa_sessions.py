"""OPEN-819: Washington's 2027-28 biennium is listed; OPEN-853: it is active now, for its
pre-filed bills, beside 2025-2026 until it convenes.

leg.wa.gov added "2027-28" to its biennium menu, and Washington's nightly failed in
openstates-core's check_session_list before reading a bill (prod run wa-69bec06e89b6,
2026-11-24). The legislature says "The 2027 Regular Session convenes on January 11". OPEN-853
(Ramon, 2026-11-24): scrape 2027-2028 now for pre-filed bills, as Nevada's 84th (OPEN-659);
2025-2026 stays active beside it until 2027-01-11, then drops. openstates-core scrapes the
sessions marked active when no session= is given, which is how our runs call it, so the active
flags below are exactly what a run would scrape on that day. The fixture is the biennium menu leg.wa.gov served on 2026-11-23;
no request leaves the test.
"""
import datetime
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import wa  # noqa: E402
from utils import checked_requests  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "wa_open819",
    "leg_wa_gov_biennium_select.html",
)


def _wa_on(monkeypatch, day):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(datetime, "date", FrozenDate)
    return importlib.reload(wa)


def _active_on(monkeypatch, day):
    module = _wa_on(monkeypatch, day)
    return {
        s["identifier"]
        for s in module.Washington.legislative_sessions
        if s.get("active")
    }


@pytest.fixture(autouse=True)
def _reload_with_real_date(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(wa)


@pytest.mark.parametrize(
    "day", [datetime.date(2026, 11, 24), datetime.date(2027, 1, 10)]
)
def test_before_2027_28_convenes_both_sessions_are_active(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"2025-2026", "2027-2028"}


# the whole biennium: still the active session after the 2027 sine die and in the 2028 session,
# as 2025-2026 is active today past its 2026-03-06 end_date
@pytest.mark.parametrize(
    "day",
    [
        datetime.date(2027, 1, 11),
        datetime.date(2027, 3, 1),
        datetime.date(2027, 6, 1),
        datetime.date(2028, 2, 1),
    ],
)
def test_2027_28_is_active_from_the_day_it_convenes(monkeypatch, day):
    assert _active_on(monkeypatch, day) == {"2027-2028"}


def test_2027_28_entry_matches_the_legislature():
    by_id = {s["identifier"]: s for s in wa.Washington.legislative_sessions}
    s = by_id["2027-2028"]
    assert s["_scraped_name"] == "2027-28"
    assert s["classification"] == "primary"
    assert s["name"] == "2027-2028 Regular Session"
    assert s["start_date"] == "2027-01-11"
    assert s["end_date"] == "2027-04-25"
    # 2025-2026 is otherwise as it was
    assert {k: v for k, v in by_id["2025-2026"].items() if k != "active"} == {
        "_scraped_name": "2025-26",
        "classification": "primary",
        "identifier": "2025-2026",
        "name": "2025-2026 Regular Session",
        "start_date": "2025-01-13",
        "end_date": "2026-03-06",
    }


class _FakeResponse:
    status_code = 200

    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        pass


@pytest.mark.parametrize(
    "day,active",
    [
        (datetime.date(2026, 11, 24), {"2025-2026", "2027-2028"}),
        (datetime.date(2027, 1, 11), {"2027-2028"}),
    ],
)
def test_session_list_check_passes_with_leg_wa_govs_real_list(monkeypatch, day, active):
    with open(FIXTURE, encoding="utf-8") as f:
        page = f.read()
    module = _wa_on(monkeypatch, day)
    urls = []

    def fake_get(self, url, **kw):
        urls.append(url)
        return _FakeResponse(page)

    monkeypatch.setattr(checked_requests.Session, "get", fake_get)
    jurisdiction = module.Washington()
    scraped = jurisdiction.get_session_list()
    assert urls == ["https://leg.wa.gov/"]
    assert scraped[:2] == ["2027-28", "2025-26"]
    # openstates-core's own check, the one that raised the CommandError; it returns the active
    # session identifiers when every listed session is known.
    assert check_session_list(jurisdiction) == active
