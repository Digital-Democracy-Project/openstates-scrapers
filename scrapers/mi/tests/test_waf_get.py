import requests
import pytest

from mi.bills import mi_waf_get
from openstates.utils.cookie_provider import WafBlockDetected
from openstates.utils.mi_cookies import MI_COOKIE_PROVIDER


class FakeResponse:
    def __init__(self, content=b"<html>real content</html>", url=None, status_code=None):
        self.content = content
        if url is not None:
            self.url = url
        if status_code is not None:
            self.status_code = status_code


DEFAULT_USER_AGENT = "Mozilla/5.0 (Real Warm-Up Chromium)"


def _stub_cookie_provider(monkeypatch, cookies=None, user_agent=DEFAULT_USER_AGENT):
    warm_up_calls = {"count": 0}

    def fake_get_cookies():
        warm_up_calls["count"] += 1
        return cookies or {"x-bni-fpc": "abc", "x-bni-rncf": "def"}

    def fake_get_user_agent():
        return user_agent

    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_cookies", fake_get_cookies)
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_user_agent", fake_get_user_agent)
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "invalidate", lambda: None)
    return warm_up_calls


def test_mi_waf_get_attaches_cached_cookies_and_user_agent(monkeypatch):
    _stub_cookie_provider(
        monkeypatch,
        cookies={"x-bni-fpc": "abc", "x-bni-rncf": "def"},
        user_agent=DEFAULT_USER_AGENT,
    )
    seen = {}

    def request_func(cookies, user_agent):
        seen.update(cookies)
        seen["User-Agent"] = user_agent
        return FakeResponse()

    resp = mi_waf_get(request_func)

    assert resp.content == b"<html>real content</html>"
    assert seen == {
        "x-bni-fpc": "abc",
        "x-bni-rncf": "def",
        "User-Agent": DEFAULT_USER_AGENT,
    }


def test_mi_waf_get_retries_once_on_connection_error_then_succeeds(monkeypatch):
    calls = _stub_cookie_provider(monkeypatch)
    attempts = {"count": 0}

    def request_func(cookies, user_agent):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise requests.exceptions.ConnectionError("connection reset")
        return FakeResponse()

    resp = mi_waf_get(request_func)

    assert resp.content == b"<html>real content</html>"
    assert attempts["count"] == 2
    assert calls["count"] == 2  # initial cookie fetch + one re-warm


def test_mi_waf_get_retries_once_on_block_page_marker_then_succeeds(monkeypatch):
    calls = _stub_cookie_provider(monkeypatch)
    attempts = {"count": 0}

    def request_func(cookies, user_agent):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return FakeResponse(content=b"User validation required to continue..")
        return FakeResponse()

    resp = mi_waf_get(request_func)

    assert resp.content == b"<html>real content</html>"
    assert attempts["count"] == 2
    assert calls["count"] == 2


def test_mi_waf_get_propagates_after_second_block(monkeypatch):
    calls = _stub_cookie_provider(monkeypatch)
    attempts = {"count": 0}

    def always_blocked(cookies, user_agent):
        attempts["count"] += 1
        raise requests.exceptions.ConnectionError("connection reset")

    with pytest.raises(WafBlockDetected):
        mi_waf_get(always_blocked)

    assert attempts["count"] == 2  # no third attempt
    assert calls["count"] == 2  # no second re-warm


def test_mi_waf_get_uses_fresh_user_agent_paired_with_fresh_cookies_on_retry(monkeypatch):
    """The retry after an invalidate-and-rewarm must see whatever get_user_agent() returns
    *at that point* (a fresh, possibly-different real UA), not the first attempt's value --
    mirrors the pairing guarantee CookieProvider.fetch_with_retry itself provides."""
    cookies_seq = iter([{"x-bni-fpc": "old", "x-bni-rncf": "old"}, {"x-bni-fpc": "new", "x-bni-rncf": "new"}])
    agents_seq = iter(["agent-v1", "agent-v2"])

    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_cookies", lambda: next(cookies_seq))
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_user_agent", lambda: next(agents_seq))
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "invalidate", lambda: None)

    seen = []

    def request_func(cookies, user_agent):
        seen.append((cookies, user_agent))
        if len(seen) == 1:
            raise requests.exceptions.ConnectionError("connection reset")
        return FakeResponse()

    mi_waf_get(request_func)

    assert seen == [
        ({"x-bni-fpc": "old", "x-bni-rncf": "old"}, "agent-v1"),
        ({"x-bni-fpc": "new", "x-bni-rncf": "new"}, "agent-v2"),
    ]


# --- OPEN-334: a block says which marker matched, the HTTP status and the URL path ---


def _blocked_message(monkeypatch, response):
    _stub_cookie_provider(monkeypatch)
    with pytest.raises(WafBlockDetected) as excinfo:
        mi_waf_get(lambda cookies, user_agent: response)
    return str(excinfo.value)


def test_block_message_names_the_marker_status_and_path_but_not_the_query_string(monkeypatch):
    msg = _blocked_message(monkeypatch, FakeResponse(
        content=b"<html>captcha_resp=abc</html>",
        url="https://legislature.mi.gov/Search/ExecuteSearch?sessions=2025-2026&sponsor=",
        status_code=200,
    ))
    assert msg == "response matched known WAF block-page marker 'captcha_resp' (HTTP 200) on /Search/ExecuteSearch"
    assert "sessions" not in msg


def test_block_message_survives_a_response_with_no_url_or_status(monkeypatch):
    msg = _blocked_message(monkeypatch, FakeResponse(content=b"User validation required to continue"))
    assert "marker 'user validation required' (HTTP ?) on ?" in msg


def test_block_message_never_contains_the_phrases_that_fail_a_run_on_their_own(monkeypatch):
    # import-summary.sh's _SCRAPE_UNREACHABLE_MARKERS treats these as "site unreachable" in any log line.
    msg = _blocked_message(monkeypatch, FakeResponse(
        content=b"Request Rejected", url="https://legislature.mi.gov/Bills/Bill", status_code=403,
    )).lower()
    assert "waf block detected" not in msg
    assert "consecutive waf blocks" not in msg
