import requests

from mi import Michigan
from openstates.utils.mi_cookies import MI_COOKIE_PROVIDER


SUCCESS_HTML = """
<html><body>
<select name="sessions" id="session_B">
<option value="All">All</option>
<option value="2025-2026" selected="selected">2025-2026</option>
<option value="2023-2024">2023-2024</option>
<option value="2011-2012">2011-2012</option>
</select>
</body></html>
"""

# legislature.mi.gov's WAF returns a page like this (no <option> elements)
# instead of the real search page when it challenges a request.
CAPTCHA_HTML = """
<html><body style="font-family:times;color:white;font-size:15px;" bgcolor="#405f8d">
<title>Validation request</title>
<h3 align="center">User validation required to continue..</h3>
</body></html>
"""


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")


def _stub_cookie_provider(monkeypatch, cookies=None):
    """Bypass the real disk cache / Playwright warm-up entirely -- get_session_list's own
    logic is what's under test here, not CookieProvider (see test_cookie_provider.py for
    that)."""
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_cookies", lambda: cookies or {})
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "invalidate", lambda: None)


def test_get_session_list_returns_scraped_sessions_on_success(monkeypatch):
    _stub_cookie_provider(monkeypatch)
    monkeypatch.setattr(
        "mi.requests.get",
        lambda url, headers=None, cookies=None, verify=None: FakeResponse(SUCCESS_HTML),
    )

    sessions = Michigan().get_session_list()

    assert sessions
    assert "2025-2026" in sessions


def test_get_session_list_attaches_cached_waf_cookies(monkeypatch):
    seen_cookies = {}

    def fake_get(url, headers=None, cookies=None, verify=None):
        seen_cookies.update(cookies or {})
        return FakeResponse(SUCCESS_HTML)

    _stub_cookie_provider(monkeypatch, cookies={"x-bni-fpc": "abc", "x-bni-rncf": "def"})
    monkeypatch.setattr("mi.requests.get", fake_get)

    sessions = Michigan().get_session_list()

    assert sessions
    assert seen_cookies == {"x-bni-fpc": "abc", "x-bni-rncf": "def"}


def test_get_session_list_falls_back_when_request_fails(monkeypatch):
    def raise_connection_error(url, headers=None, cookies=None, verify=None):
        raise requests.exceptions.ConnectionError("could not connect")

    _stub_cookie_provider(monkeypatch)
    monkeypatch.setattr("mi.requests.get", raise_connection_error)

    sessions = Michigan().get_session_list()

    assert sessions
    assert "2025-2026" in sessions


def test_get_session_list_falls_back_when_waf_challenge_page_returned(monkeypatch):
    # Reproduces the actual OPEN-17 failure: a 200 response whose body is a
    # CAPTCHA challenge page with zero <option> elements. OPEN-19's block-detection
    # heuristic now catches this on the response body itself (before it's even parsed for
    # <option> elements), triggering one cookie re-warm-and-retry; since the fake always
    # returns the same challenge page, the retry fails too and this falls through to the
    # same known-sessions safety net as before.
    _stub_cookie_provider(monkeypatch)
    monkeypatch.setattr(
        "mi.requests.get",
        lambda url, headers=None, cookies=None, verify=None: FakeResponse(CAPTCHA_HTML),
    )

    sessions = Michigan().get_session_list()

    assert sessions
    assert "2025-2026" in sessions
