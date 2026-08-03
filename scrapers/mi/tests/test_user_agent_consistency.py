"""Tests for OPEN-23: within a single MI scrape, every cookie-authenticated request must
present the same real User-Agent that minted the currently-cached cookie pair -- never the
old hardcoded USER_AGENT constant, and never a value clobbered by http_resilience_mode's
get_random_user_agent() rotation (base.py's circuit breaker, connection-error handling, or
periodic fresh-session reset, all opted out for MI via
MIResilientScraperMixin._resilience_user_agent_rotation_enabled = False).
"""
import tempfile
from http.client import RemoteDisconnected

import scrapelib

from mi import bills as mi_bills
from mi.bills import MIBillScraper
from mi.events import MIEventScraper
from mi import Michigan
from openstates.scrape import base as core_base
from openstates.utils.mi_cookies import MI_COOKIE_PROVIDER

# A deterministic stand-in for get_random_user_agent()'s real random pool -- lets tests
# assert MI's self.headers never becomes this sentinel, instead of a flaky probabilistic
# "isn't one of the 7 pool entries" check.
ROTATED_SENTINEL_USER_AGENT = "Mozilla/5.0 (Rotated-By-Resilience-Mode Sentinel)"


CAPTURED_USER_AGENT = "Mozilla/5.0 (Real Warm-Up Chromium) HeadlessChrome/999.0"
STUBBED_COOKIES = {"x-bni-fpc": "abc", "x-bni-rncf": "def"}

SEARCH_RESULTS_HTML = b"""
<html><body>
<div class="tableScrollWrapper">
<table><tbody>
<tr><td><a href="/mileg.aspx?page=getObject&objectName=2025-HB-0001">HB 0001 of 2025</a></td></tr>
<tr><td><a href="/mileg.aspx?page=getObject&objectName=2025-HB-0002">HB 0002 of 2025</a></td></tr>
</tbody></table>
</div>
</body></html>
"""

VALID_BILL_HTML = b"""
<html><body>
<div id="ObjectSubject">A bill about testing</div>
<h1 id="BillHeading">House Bill No. 1</h1>
<div id="History"><table><tbody></tbody></table></div>
</body></html>
"""

CALENDAR_HTML = b"""
<html><body>
<table class="calendar">
<a href="/Committees/Meeting?meetingID=1">Meeting 1</a>
<a href="/Committees/Meeting?meetingID=2">Meeting 2</a>
</table>
</body></html>
"""

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


def _stub_cookie_provider(monkeypatch, user_agent=CAPTURED_USER_AGENT):
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_cookies", lambda: dict(STUBBED_COOKIES))
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_user_agent", lambda: user_agent)
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "invalidate", lambda: None)


class FakeResponse:
    def __init__(self, content):
        self.content = content
        self.text = content.decode()


def _install_transport_recorder(monkeypatch, content_for_url):
    """Patch the ultimate scrapelib transport .get() (below Scraper.get()'s
    http_resilience_mode wrapper, so request_resiliently/circuit-breaker/fresh-session
    logic still runs for real) to record every actually-sent User-Agent header and return
    canned content keyed by URL."""
    seen_user_agents = []

    def fake_get(self, url, **kwargs):
        headers = kwargs.get("headers") or {}
        seen_user_agents.append(headers.get("User-Agent"))
        return FakeResponse(content_for_url(url))

    monkeypatch.setattr(scrapelib.Scraper, "get", fake_get)
    return seen_user_agents


def _content_for_bill_scrape(url):
    if "ExecuteSearch" in url:
        return SEARCH_RESULTS_HTML
    return VALID_BILL_HTML


def _content_for_event_scrape(url):
    if "Meetings" in url:
        return CALENDAR_HTML
    return VALID_EVENT_HTML


def test_full_bill_scrape_uses_captured_user_agent_for_every_request(monkeypatch):
    monkeypatch.setattr(core_base.time, "sleep", lambda *_a, **_k: None)
    _stub_cookie_provider(monkeypatch)
    seen_user_agents = _install_transport_recorder(monkeypatch, _content_for_bill_scrape)

    scraper = MIBillScraper(Michigan(), tempfile.mkdtemp())
    list(scraper.scrape("2025-2026"))

    # search page + 2 bill pages = 3 real requests, every one presenting the same UA that
    # minted the currently-cached cookie pair -- never the removed hardcoded constant.
    assert len(seen_user_agents) == 3
    assert all(ua == CAPTURED_USER_AGENT for ua in seen_user_agents)


def test_full_event_scrape_uses_captured_user_agent_for_every_request(monkeypatch):
    monkeypatch.setattr(core_base.time, "sleep", lambda *_a, **_k: None)
    _stub_cookie_provider(monkeypatch)
    seen_user_agents = _install_transport_recorder(monkeypatch, _content_for_event_scrape)

    scraper = MIEventScraper(Michigan(), tempfile.mkdtemp())
    list(scraper.scrape())

    # calendar page + 2 event pages = 3 real requests -- events.py previously sent no
    # explicit User-Agent at all, silently inheriting whatever resilience-mode rotation
    # last set; confirms that's fixed too.
    assert len(seen_user_agents) == 3
    assert all(ua == CAPTURED_USER_AGENT for ua in seen_user_agents)


def test_circuit_breaker_trip_does_not_change_mi_request_user_agent(monkeypatch):
    """A circuit breaker trip (base.py's request_resiliently, ~3 consecutive failures)
    rotates self.headers["User-Agent"] for a normal http_resilience_mode consumer -- for
    MI it must not, and the next real request must still present the captured UA."""
    monkeypatch.setattr(
        core_base, "get_random_user_agent", lambda: ROTATED_SENTINEL_USER_AGENT
    )
    _stub_cookie_provider(monkeypatch)
    seen_user_agents = _install_transport_recorder(monkeypatch, _content_for_bill_scrape)
    monkeypatch.setattr(core_base.time, "sleep", lambda *_a, **_k: None)

    scraper = MIBillScraper(Michigan(), tempfile.mkdtemp())
    # Force the circuit breaker to trip on the very next request_resiliently() call.
    scraper._consecutive_failures = scraper._max_consecutive_failures

    list(scraper.scrape_bill("2025-2026", "HB 0001", "https://legislature.mi.gov/Bills/Bill?ObjectName=2025-HB-0001"))

    assert seen_user_agents == [CAPTURED_USER_AGENT]
    # Rotation opt-out (AC3): self.headers itself must also stay untouched by the circuit
    # breaker's rotation, not just the actual outgoing request.
    assert scraper.headers.get("User-Agent") != ROTATED_SENTINEL_USER_AGENT


def test_periodic_fresh_session_reset_does_not_change_mi_request_user_agent(monkeypatch):
    """_create_fresh_session() (base.py, fired every _reset_interval seconds) rotates the
    User-Agent for a normal http_resilience_mode consumer -- for MI it must not."""
    monkeypatch.setattr(
        core_base, "get_random_user_agent", lambda: ROTATED_SENTINEL_USER_AGENT
    )
    monkeypatch.setattr(core_base.time, "sleep", lambda *_a, **_k: None)
    _stub_cookie_provider(monkeypatch)
    seen_user_agents = _install_transport_recorder(monkeypatch, _content_for_bill_scrape)

    scraper = MIBillScraper(Michigan(), tempfile.mkdtemp())
    # Force the periodic connection-pool reset to fire on the next request.
    scraper._last_reset_time = 0

    list(scraper.scrape_bill("2025-2026", "HB 0001", "https://legislature.mi.gov/Bills/Bill?ObjectName=2025-HB-0001"))

    assert seen_user_agents == [CAPTURED_USER_AGENT]
    assert scraper.headers.get("User-Agent") != ROTATED_SENTINEL_USER_AGENT


def test_connection_error_rotation_does_not_change_mi_request_user_agent(monkeypatch):
    """Once request_resiliently's own retry-with-backoff is exhausted by a real
    connection-level failure (RemoteDisconnected -- a genuine subclass of the builtin
    ConnectionError base.py checks for), it rotates self.headers["User-Agent"] for a
    normal http_resilience_mode consumer -- for MI it must not."""
    monkeypatch.setattr(
        core_base, "get_random_user_agent", lambda: ROTATED_SENTINEL_USER_AGENT
    )
    monkeypatch.setattr(core_base.time, "sleep", lambda *_a, **_k: None)

    def always_disconnects(self, url, **kwargs):
        raise RemoteDisconnected("connection reset")

    monkeypatch.setattr(scrapelib.Scraper, "get", always_disconnects)

    scraper = MIBillScraper(Michigan(), tempfile.mkdtemp())
    scraper.headers["User-Agent"] = CAPTURED_USER_AGENT

    # request_resiliently swallows a connection error once its own retries are exhausted
    # (returns None rather than raising) -- that's pre-existing behavior, not this
    # ticket's concern; what matters here is whether it rotated the UA on the way out.
    result = scraper.get(
        "https://legislature.mi.gov/some-url",
        headers={"User-Agent": CAPTURED_USER_AGENT},
        cookies={},
        verify=False,
    )

    assert result is None
    assert scraper.headers.get("User-Agent") == CAPTURED_USER_AGENT
