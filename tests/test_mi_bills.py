"""Tests for OPEN-18: legislature.mi.gov's WAF can block a bill fetch behind a genuine HTTP
404 status, serving its own site-styled "The specified URL cannot be found" error page for a
bill that demonstrably exists. scrape_bill() must recognize that specific body signature and
skip just that bill (with a circuit breaker if the run is fully blocked) -- while a real dead
link (a 404 with some other body) must still crash exactly as before.
"""
import os
import sys
from unittest import mock

import pytest
import requests
import scrapelib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from mi import Michigan  # noqa: E402
from mi.bills import MAX_CONSECUTIVE_WAF_BLOCKS, MIBillScraper  # noqa: E402
import mi.bills as mi_bills  # noqa: E402
from openstates.exceptions import ScrapeError  # noqa: E402


BILL_URL = "https://legislature.mi.gov/Bills/Bill?ObjectName=2026-SB-1141"


def make_http_error(
    status_code: int, body_text: str, url: str = BILL_URL
) -> scrapelib.HTTPError:
    resp = requests.models.Response()
    resp.status_code = status_code
    resp.url = url
    resp._content = body_text.encode()
    return scrapelib.HTTPError(resp)


@pytest.fixture(autouse=True)
def bypass_real_cookie_provider(monkeypatch):
    """Route mi_waf_get straight through do_request({}) -- no disk cache, no Playwright, no
    retry-on-block dance. That dance is CookieProvider's own tested concern (see
    test_cookie_provider.py); these tests are only about scrape_bill()'s own
    catch/skip/circuit-breaker behavior once mi_waf_get raises or returns.
    """

    def fake_fetch_with_retry(do_request):
        return do_request({}, "test-agent")

    monkeypatch.setattr(mi_bills.MI_COOKIE_PROVIDER, "fetch_with_retry", fake_fetch_with_retry)


def make_scraper() -> MIBillScraper:
    return MIBillScraper(Michigan(), "/tmp/")


def test_scrape_bill_skips_fake_404_block_and_continues(monkeypatch, caplog):
    scraper = make_scraper()
    error = make_http_error(
        404, "<html><body>The specified URL cannot be found.</body></html>"
    )
    monkeypatch.setattr(scraper, "get", mock.Mock(side_effect=error))

    result = list(scraper.scrape_bill("2025-2026", "SB 1141", BILL_URL))

    assert result == []
    assert scraper._consecutive_waf_blocks == 1
    assert any("WAF block detected" in r.message for r in caplog.records)


def test_scrape_bill_reraises_genuine_404(monkeypatch):
    scraper = make_scraper()
    error = make_http_error(404, "<html><body>Object reference not found</body></html>")
    monkeypatch.setattr(scraper, "get", mock.Mock(side_effect=error))

    with pytest.raises(scrapelib.HTTPError):
        list(scraper.scrape_bill("2025-2026", "SB 9999", BILL_URL))

    assert scraper._consecutive_waf_blocks == 0


def test_circuit_breaker_aborts_after_max_consecutive_blocks(monkeypatch):
    scraper = make_scraper()
    error = make_http_error(
        404, "<html><body>The specified URL cannot be found.</body></html>"
    )
    monkeypatch.setattr(scraper, "get", mock.Mock(side_effect=error))

    for _ in range(MAX_CONSECUTIVE_WAF_BLOCKS - 1):
        assert list(scraper.scrape_bill("2025-2026", "SB 1141", BILL_URL)) == []

    with pytest.raises(ScrapeError):
        list(scraper.scrape_bill("2025-2026", "SB 1141", BILL_URL))

    assert scraper._consecutive_waf_blocks == MAX_CONSECUTIVE_WAF_BLOCKS


def test_successful_fetch_resets_consecutive_block_counter(monkeypatch):
    scraper = make_scraper()
    scraper._consecutive_waf_blocks = 2

    real_page = """
    <html>
      <h1 id="BillHeading">Senate Bill 1141 of 2026</h1>
      <div id="ObjectSubject">A bill title</div>
    </html>
    """
    ok_response = mock.Mock(content=real_page.encode())
    monkeypatch.setattr(scraper, "get", mock.Mock(return_value=ok_response))

    list(scraper.scrape_bill("2025-2026", "SB 1141", BILL_URL))

    assert scraper._consecutive_waf_blocks == 0
