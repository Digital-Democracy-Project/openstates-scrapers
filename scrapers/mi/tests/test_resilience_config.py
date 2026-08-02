"""Tests for OPEN-21: MI gets its own conservative rate limit and opts into
http_resilience_mode unconditionally, and the resulting retry-stacking interaction with
mi_waf_get()'s own invalidate-and-retry-once dance is resolved (not just left as a risk).
"""
import importlib
from unittest import mock

import requests
import scrapelib

from mi import Michigan
from mi.bills import MIBillScraper, MIResilientScraperMixin
import mi.bills as mi_bills
from mi.events import MIEventScraper
from openstates import settings
from openstates.scrape import Scraper, State
from openstates.scrape import base as core_base
from openstates.utils.cookie_provider import WafBlockDetected


BILL_URL = "https://legislature.mi.gov/Bills/Bill?ObjectName=2026-SB-1141"


def make_http_error(
    status_code=404,
    body_text="<html><body>The specified URL cannot be found.</body></html>",
    url=BILL_URL,
) -> scrapelib.HTTPError:
    resp = requests.models.Response()
    resp.status_code = status_code
    resp.url = url
    resp._content = body_text.encode()
    return scrapelib.HTTPError(resp)


def test_mi_bill_scraper_forces_http_resilience_mode_true_even_if_false_requested():
    # The CLI/State scraper-instantiation path always passes http_resilience_mode
    # explicitly (defaults to False for every other jurisdiction) -- MI must force it
    # to True regardless of what's passed in.
    scraper = MIBillScraper(Michigan(), "/tmp/", http_resilience_mode=False)
    assert scraper.http_resilience_mode is True


def test_mi_event_scraper_forces_http_resilience_mode_true_even_if_false_requested():
    scraper = MIEventScraper(Michigan(), "/tmp/", http_resilience_mode=False)
    assert scraper.http_resilience_mode is True


def test_mi_bill_scraper_uses_conservative_rate_below_platform_default():
    scraper = MIBillScraper(Michigan(), "/tmp/")
    assert scraper.requests_per_minute == mi_bills.MI_SCRAPELIB_RPM
    assert scraper.requests_per_minute < settings.SCRAPELIB_RPM


def test_mi_event_scraper_uses_conservative_rate_below_platform_default():
    scraper = MIEventScraper(Michigan(), "/tmp/")
    assert scraper.requests_per_minute == mi_bills.MI_SCRAPELIB_RPM
    assert scraper.requests_per_minute < settings.SCRAPELIB_RPM


def test_mi_scrapelib_rpm_env_var_is_tunable_without_redeploy(monkeypatch):
    monkeypatch.setenv("MI_SCRAPELIB_RPM", "5")
    importlib.reload(mi_bills)
    try:
        scraper = mi_bills.MIBillScraper(Michigan(), "/tmp/")
        assert scraper.requests_per_minute == 5
    finally:
        # Restore real env state before reloading back to the default, so later tests
        # (in this file or others) see MI_SCRAPELIB_RPM's normal default again.
        monkeypatch.undo()
        importlib.reload(mi_bills)


def test_other_jurisdiction_scraper_unaffected():
    """MI's changes are scoped to MI's own classes -- a plain Scraper (standing in for
    any other jurisdiction) keeps the platform defaults untouched."""

    class NewJersey(State):
        pass

    scraper = Scraper(NewJersey(), "/tmp/")
    assert scraper.http_resilience_mode is False
    assert scraper.requests_per_minute == settings.SCRAPELIB_RPM
    assert scraper._resilience_retry_excluded_exceptions == ()


def test_retry_stacking_resolution_does_not_double_retry_waf_block(monkeypatch):
    """OPEN-21 AC2: with http_resilience_mode forced on, a WAF block (here: a disguised
    404) must NOT be retried by request_resiliently's own 3x/backoff loop before
    mi_waf_get()'s cookie-invalidate-and-retry-once dance ever sees it. Without the
    MIResilientScraperMixin's _resilience_retry_excluded_exceptions opt-out, each of the
    2 do_request() attempts below would itself retry the HTTPError 3 additional times
    with real 10s/20s/40s backoff (8 total calls instead of 2, plus 10s/20s/40s-scale
    sleep durations instead of only the 1-3s jittered pre-request delay). time.sleep is
    mocked so a regression fails fast on the assertions below instead of actually
    sleeping for ~140s.
    """
    scraper = MIBillScraper(Michigan(), "/tmp/")
    call_count = {"n": 0}

    def raising_get(self, url, **kwargs):
        call_count["n"] += 1
        raise make_http_error()

    monkeypatch.setattr(scrapelib.Scraper, "get", raising_get)
    monkeypatch.setattr(core_base.time, "sleep", mock.Mock())

    def fake_fetch_with_retry_matching_real_contract(do_request):
        # Mirrors CookieProvider.fetch_with_retry's real invalidate-and-retry-once
        # contract without touching disk/Playwright (same convention as
        # test_waf_get.py's own stubbing).
        try:
            return do_request({})
        except WafBlockDetected:
            return do_request({})

    monkeypatch.setattr(
        mi_bills.MI_COOKIE_PROVIDER,
        "fetch_with_retry",
        fake_fetch_with_retry_matching_real_contract,
    )

    result = list(scraper.scrape_bill("2025-2026", "SB 1141", BILL_URL))

    assert result == []
    assert scraper._consecutive_waf_blocks == 1
    # Exactly 2 physical HTTP attempts: one per do_request() call, zero extra retries
    # injected by request_resiliently.
    assert call_count["n"] == 2
    # request_resiliently's own jittered 1-3s pre-request delay (add_random_delay) still
    # fires once per get() call -- that's expected/desired http_resilience_mode behavior,
    # not the bug. What must NOT appear is retry_on_connection_error's exponential
    # backoff (10s/20s/40s, uncapped by the 1-3s jitter range) -- so assert every sleep
    # call stayed within the jitter bound instead of asserting zero sleeps.
    sleep_calls = [c.args[0] for c in core_base.time.sleep.call_args_list]
    assert len(sleep_calls) == 2
    assert all(0 <= duration <= 3 for duration in sleep_calls)


def test_mixin_sets_excluded_exceptions_used_by_retry_stacking_fix():
    scraper = MIBillScraper(Michigan(), "/tmp/")
    assert scraper._resilience_retry_excluded_exceptions == (
        scrapelib.HTTPError,
        requests.exceptions.ConnectionError,
    )
    assert isinstance(scraper, MIResilientScraperMixin)
