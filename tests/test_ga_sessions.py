"""OPEN-605: Georgia's 2027-2028 Regular Session is listed and becomes the active session on its start date
(2027-01-11, the second Monday of January), as Arizona's 2027 (OPEN-632); the 2026 Special Session gets its real
dates (2026-06-17 to 06-23, the legislature's last actions, on the replica).

Georgia does not list 2027-2028 yet: its own session list (webservices.legis.ga.gov, GetSessions, read 2026-11-23,
saved unchanged as the fixture) stops at the 2026 Special Session, id 1034. So the bill scraper reads a session's site
id from that list when SESSION_SITE_IDS has none, and while Georgia does not list it there is nothing to read: the run
says so and ends empty (EmptyScrape) instead of failing. No request leaves the test.
"""
import datetime
import importlib
import os
import sys
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

# the scraper builds its SOAP clients (a WSDL fetch) when the module loads
with mock.patch("suds.client.Client"):
    import ga  # noqa: E402
    from ga import bills as ga_bills, util as ga_util  # noqa: E402

from openstates.cli.update import check_session_list  # noqa: E402
from openstates.exceptions import EmptyScrape  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "ga_open605", "GetSessions_20261123.xml"
)
DATA = "{http://www.legis.ga.gov/2009/01/01/data/}"


def georgia_sessions(extra=()):
    """Georgia's GetSessions answer of 2026-11-23, as suds hands it over, plus any `extra` sessions."""
    sessions = [
        {
            "Id": int(s.find(DATA + "Id").text),
            "Description": s.find(DATA + "Description").text,
        }
        for s in ET.parse(FIXTURE).getroot().iter(DATA + "Session")
    ]
    return {"Session": sessions + list(extra)}


def fake_session_client(answer, calls):
    def get_sessions():
        calls.append("GetSessions")
        return answer

    return SimpleNamespace(service=SimpleNamespace(GetSessions=get_sessions))


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch):
    monkeypatch.setattr(ga_util.time, "sleep", lambda s: None)


def _ga_on(monkeypatch, day):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(datetime, "date", FrozenDate)
    return importlib.reload(ga)


@pytest.fixture
def _reload_with_real_date(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(ga)


def _active_on(monkeypatch, day):
    module = _ga_on(monkeypatch, day)
    return {
        s["identifier"] for s in module.Georgia.legislative_sessions if s.get("active")
    }


@pytest.mark.parametrize(
    "day", [datetime.date(2026, 11, 23), datetime.date(2027, 1, 10)]
)
def test_before_2027_28_starts_only_2026_ss_is_active(
    monkeypatch, _reload_with_real_date, day
):
    assert _active_on(monkeypatch, day) == {"2026_ss"}


@pytest.mark.parametrize("day", [datetime.date(2027, 1, 11), datetime.date(2028, 3, 1)])
def test_2027_28_is_active_from_its_start(monkeypatch, _reload_with_real_date, day):
    assert _active_on(monkeypatch, day) == {"2027_28"}


def _session(identifier):
    return next(
        s for s in ga.Georgia.legislative_sessions if s["identifier"] == identifier
    )


def test_2027_28_is_listed_under_georgias_own_naming():
    session = _session("2027_28")
    assert session["classification"] == "primary"
    assert session["start_date"] == "2027-01-11"
    # Georgia names every two-year session this way in its own list ("2025-2026 Regular Session", ...)
    regular = [
        s["Description"]
        for s in georgia_sessions()["Session"]
        if "Regular" in s["Description"]
    ]
    assert "2025-2026 Regular Session" in regular
    assert session["_scraped_name"] == "2027-2028 Regular Session"
    assert session["start_date"] > _session("2026_ss")["end_date"]


def test_2026_ss_has_its_real_dates():
    session = _session("2026_ss")
    assert (session["start_date"], session["end_date"]) == ("2026-06-17", "2026-06-23")


def test_the_site_id_comes_from_georgias_own_list(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ga_util,
        "get_client",
        lambda name: fake_session_client(georgia_sessions(), calls),
    )
    # the ids already in SESSION_SITE_IDS are what Georgia's list says
    assert ga_util.published_session_id("2025-2026 Regular Session") == 1033
    assert ga_util.published_session_id("2026 Special Session") == 1034
    assert ga_util.published_session_id("2027-2028 Regular Session") is None


class _Stop(Exception):
    pass


def _scrape(monkeypatch, session, answer):
    calls, read = [], []
    monkeypatch.setattr(
        ga_util, "get_client", lambda name: fake_session_client(answer, calls)
    )

    def get_legislation_for_session(sid):
        read.append(sid)
        raise _Stop  # the id is all this test needs

    monkeypatch.setattr(
        ga_bills.GABillScraper,
        "lservice",
        SimpleNamespace(GetLegislationForSession=get_legislation_for_session),
    )
    scraper = ga_bills.GABillScraper(ga.Georgia(), "/tmp/")
    with pytest.raises((EmptyScrape, _Stop)) as raised:
        list(scraper.scrape(session=session))
    return raised.type, read, calls


def test_while_georgia_does_not_list_2027_28_the_run_ends_empty(monkeypatch):
    raised, read, calls = _scrape(monkeypatch, "2027_28", georgia_sessions())
    assert (raised, read, calls) == (EmptyScrape, [], ["GetSessions"])


def test_once_georgia_lists_2027_28_its_bills_are_read_by_that_id(monkeypatch):
    published = georgia_sessions(
        [{"Id": 1035, "Description": "2027-2028 Regular Session"}]
    )
    raised, read, calls = _scrape(monkeypatch, "2027_28", published)
    assert (raised, read) == (_Stop, [1035])


def test_a_session_with_a_known_id_does_not_ask_georgias_list(monkeypatch):
    raised, read, calls = _scrape(monkeypatch, "2026_ss", georgia_sessions())
    assert (raised, read, calls) == (_Stop, [1034], [])


@pytest.mark.parametrize(
    "day,active",
    [
        (datetime.date(2026, 11, 23), {"2026_ss"}),
        (datetime.date(2027, 1, 11), {"2027_28"}),
    ],
)
def test_session_list_check_passes_with_georgias_real_list(
    monkeypatch, _reload_with_real_date, day, active
):
    module = _ga_on(monkeypatch, day)
    monkeypatch.setattr(
        module, "get_client", lambda name: fake_session_client(georgia_sessions(), [])
    )
    # openstates-core's own check: every session Georgia lists is ours or ignored; returns the active ones
    assert check_session_list(module.Georgia()) == active
