import tempfile

import pytest

from mi._waf_circuit_breaker import MAX_CONSECUTIVE_WAF_BLOCKS
from mi.events import MIEventScraper
from openstates.exceptions import EmptyScrape, ScrapeError
from openstates.utils.cookie_provider import WafBlockDetected

# Minimal valid event page -- just enough structure for scrape_event_page()
# to build an Event successfully once the WAF-block circuit breaker lets it
# through.
VALID_EVENT_HTML = b"""
<html><body>
<div class="formLeft">Committee(s)</div><div class="formRight">Committee A</div>
<div class="formLeft">Chair</div><div class="formRight">Rep. Smith</div>
<div class="formLeft">Clerk</div><div class="formRight">Jane Doe</div>
<div class="formLeft">Location</div><div class="formRight">Room 100</div>
<div class="formLeft">Date</div><div class="formRight">01/01/2026</div>
<div class="formLeft">Time</div><div class="formRight">10:00 AM</div>
<div class="formLeft">Agenda</div><div class="formRight">Discuss HB 0001</div>
</body></html>
"""

# calendar page with a single meeting link, used by scrape()'s success paths
CALENDAR_HTML = b"""
<html><body>
<table class="calendar">
<a href="/Committees/Meeting?meetingID=12345">Meeting 1</a>
</table>
</body></html>
"""

EMPTY_CALENDAR_HTML = b"""
<html><body>
<table class="calendar"></table>
</body></html>
"""

EVENT_URL = "https://legislature.mi.gov/Committees/Meeting?meetingID=12345"


def _make_scraper():
    return MIEventScraper(None, tempfile.mkdtemp())


def _always_blocked(monkeypatch):
    monkeypatch.setattr(
        "mi.events.mi_waf_get",
        lambda request_func: (_ for _ in ()).throw(WafBlockDetected("blocked")),
    )


class FakeResponse:
    def __init__(self, content):
        self.content = content


def test_scrape_event_page_skips_and_continues_below_threshold(monkeypatch):
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    result = list(scraper.scrape_event_page(EVENT_URL))

    assert result == []
    assert scraper._consecutive_waf_blocks == 1


def test_scrape_event_page_aborts_after_max_consecutive_blocks(monkeypatch):
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    for _ in range(MAX_CONSECUTIVE_WAF_BLOCKS - 1):
        result = list(scraper.scrape_event_page(EVENT_URL))
        assert result == []

    with pytest.raises(ScrapeError):
        list(scraper.scrape_event_page(EVENT_URL))

    assert scraper._consecutive_waf_blocks == MAX_CONSECUTIVE_WAF_BLOCKS


def test_scrape_event_page_resets_counter_after_successful_fetch(monkeypatch):
    scraper = _make_scraper()
    calls = {"count": 0}

    def flaky_then_success(request_func):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise WafBlockDetected("blocked")
        return FakeResponse(VALID_EVENT_HTML)

    monkeypatch.setattr("mi.events.mi_waf_get", flaky_then_success)

    list(scraper.scrape_event_page(EVENT_URL))
    list(scraper.scrape_event_page(EVENT_URL))
    events = list(scraper.scrape_event_page(EVENT_URL))

    assert len(events) == 1
    assert scraper._consecutive_waf_blocks == 0

    # A single subsequent block must not abort -- confirms the reset held.
    _always_blocked(monkeypatch)
    result = list(scraper.scrape_event_page(EVENT_URL))
    assert result == []
    assert scraper._consecutive_waf_blocks == 1


def test_scrape_raises_scrape_error_immediately_on_calendar_page_block(monkeypatch):
    # scrape()'s calendar-page fetch happens once per run (no loop), so a
    # block here must abort right away rather than silently propagating a
    # raw WafBlockDetected (the uncounted crash OPEN-22 AC7 fixes).
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    with pytest.raises(ScrapeError):
        list(scraper.scrape())


def test_scrape_still_raises_empty_scrape_on_truly_empty_calendar(monkeypatch):
    # Unrelated to the WAF fix -- confirms scrape() still distinguishes a
    # successful-but-empty calendar fetch from a WAF block.
    scraper = _make_scraper()
    monkeypatch.setattr(
        "mi.events.mi_waf_get",
        lambda request_func: FakeResponse(EMPTY_CALENDAR_HTML),
    )

    with pytest.raises(EmptyScrape):
        list(scraper.scrape())


def test_scrape_yields_events_from_calendar_on_success(monkeypatch):
    calendar_call = {"count": 0}

    def fake_mi_waf_get(request_func):
        calendar_call["count"] += 1
        if calendar_call["count"] == 1:
            return FakeResponse(CALENDAR_HTML)
        return FakeResponse(VALID_EVENT_HTML)

    scraper = _make_scraper()
    monkeypatch.setattr("mi.events.mi_waf_get", fake_mi_waf_get)

    events = list(scraper.scrape())

    assert len(events) == 1
