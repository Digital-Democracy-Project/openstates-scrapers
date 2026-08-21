"""Tests for OPEN-106: Utah.get_session_list() called url_xpath() with no
user_agent=, which falls back to requests' bare default "python-requests/X.Y"
User-Agent. Confirmed live: le.utah.gov's WAF sometimes returns a 200
"Request Rejected" page (i.e. zero sessions found, not an exception) for
that default UA, and le.utah.gov is separately, independently
flaky/rate-limited regardless of UA. That empty result fell straight through
to check_session_list()'s generic, undiagnostic "no sessions from
Utah.get_session_list()" CommandError, aborting the entire ut scrape before
any session was ever attempted.

get_session_list() now always sends a browser-shaped User-Agent (the actual
fix), and additionally retries a few times with backoff -- a cheap,
independent safety net for ordinary transient network failures -- raising a
specific ScrapeError naming the last underlying error if every attempt still
comes up empty.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ut  # noqa: E402
from ut import Utah  # noqa: E402
from openstates.exceptions import ScrapeError  # noqa: E402


def make_jurisdiction() -> Utah:
    return Utah()


def _no_sleep(monkeypatch):
    # keep the tests fast -- backoff timing itself isn't what's under test
    monkeypatch.setattr(ut.time, "sleep", lambda seconds: None)


def test_get_session_list_returns_immediately_on_first_success(monkeypatch):
    _no_sleep(monkeypatch)
    calls = []

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        calls.append(user_agent)
        return ["2026 General Session"]

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)

    result = make_jurisdiction().get_session_list()

    assert result == ["2026 General Session"]
    assert len(calls) == 1


def test_get_session_list_sends_a_browser_shaped_user_agent(monkeypatch):
    # The actual OPEN-106 fix: le.utah.gov's WAF blocks requests' bare
    # default UA outright, so this must never be called with none set.
    _no_sleep(monkeypatch)
    seen_user_agents = []

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        seen_user_agents.append(user_agent)
        return ["2026 General Session"]

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)

    make_jurisdiction().get_session_list()

    assert len(seen_user_agents) == 1
    (user_agent,) = seen_user_agents
    assert user_agent and "Mozilla" in user_agent


def test_get_session_list_retries_after_a_transient_empty_result(monkeypatch):
    _no_sleep(monkeypatch)
    responses = [[], ["2026 General Session", "2025 Second Special Session "]]
    seen_user_agents = []

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        seen_user_agents.append(user_agent)
        return responses.pop(0)

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)

    result = make_jurisdiction().get_session_list()

    assert result == ["2026 General Session", "2025 Second Special Session"]
    assert responses == []  # both queued responses were consumed
    # every attempt, not just the first, must send a browser-shaped UA
    assert len(seen_user_agents) == 2
    assert all(ua and "Mozilla" in ua for ua in seen_user_agents)


def test_get_session_list_retries_after_a_raised_exception(monkeypatch):
    _no_sleep(monkeypatch)
    attempts = []

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("boom")
        return ["2026 General Session"]

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)

    result = make_jurisdiction().get_session_list()

    assert result == ["2026 General Session"]
    assert len(attempts) == 2


def test_get_session_list_raises_scrape_error_after_exhausting_retries(monkeypatch):
    _no_sleep(monkeypatch)
    attempts = []

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        attempts.append(1)
        return []

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)

    with pytest.raises(ScrapeError):
        make_jurisdiction().get_session_list()

    assert len(attempts) == ut._SESSION_LIST_MAX_ATTEMPTS


def test_get_session_list_raises_scrape_error_naming_persistent_exception(monkeypatch):
    _no_sleep(monkeypatch)

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        raise TimeoutError("le.utah.gov timed out")

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)

    with pytest.raises(ScrapeError, match="le.utah.gov timed out"):
        make_jurisdiction().get_session_list()


def test_get_session_list_error_message_does_not_cite_a_stale_earlier_exception(
    monkeypatch,
):
    # attempt 1 raises, but attempts 2 and 3 fail cleanly (empty result, no
    # exception) -- the final error should not misleadingly blame attempt 1's
    # exception for a failure that, by the last attempt, had none.
    attempts = []

    def fake_url_xpath(url, path, verify=None, user_agent=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("attempt-1-only transient error")
        return []

    monkeypatch.setattr(ut, "url_xpath", fake_url_xpath)
    monkeypatch.setattr(ut.time, "sleep", lambda seconds: None)

    with pytest.raises(ScrapeError) as excinfo:
        make_jurisdiction().get_session_list()

    assert "attempt-1-only transient error" not in str(excinfo.value)
