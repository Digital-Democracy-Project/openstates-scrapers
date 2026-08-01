import requests
import pytest

from mi.bills import mi_waf_get
from openstates.utils.cookie_provider import WafBlockDetected
from openstates.utils.mi_cookies import MI_COOKIE_PROVIDER


class FakeResponse:
    def __init__(self, content=b"<html>real content</html>"):
        self.content = content


def _stub_cookie_provider(monkeypatch, cookies=None):
    warm_up_calls = {"count": 0}

    def fake_get_cookies():
        warm_up_calls["count"] += 1
        return cookies or {"x-bni-fpc": "abc", "x-bni-rncf": "def"}

    monkeypatch.setattr(MI_COOKIE_PROVIDER, "get_cookies", fake_get_cookies)
    monkeypatch.setattr(MI_COOKIE_PROVIDER, "invalidate", lambda: None)
    return warm_up_calls


def test_mi_waf_get_attaches_cached_cookies(monkeypatch):
    _stub_cookie_provider(monkeypatch, cookies={"x-bni-fpc": "abc", "x-bni-rncf": "def"})
    seen = {}

    def request_func(cookies):
        seen.update(cookies)
        return FakeResponse()

    resp = mi_waf_get(request_func)

    assert resp.content == b"<html>real content</html>"
    assert seen == {"x-bni-fpc": "abc", "x-bni-rncf": "def"}


def test_mi_waf_get_retries_once_on_connection_error_then_succeeds(monkeypatch):
    calls = _stub_cookie_provider(monkeypatch)
    attempts = {"count": 0}

    def request_func(cookies):
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

    def request_func(cookies):
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

    def always_blocked(cookies):
        attempts["count"] += 1
        raise requests.exceptions.ConnectionError("connection reset")

    with pytest.raises(WafBlockDetected):
        mi_waf_get(always_blocked)

    assert attempts["count"] == 2  # no third attempt
    assert calls["count"] == 2  # no second re-warm
