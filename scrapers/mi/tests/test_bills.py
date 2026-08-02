import tempfile

import pytest

from mi._waf_circuit_breaker import MAX_CONSECUTIVE_WAF_BLOCKS
from mi.bills import MIBillScraper
from openstates.exceptions import ScrapeError
from openstates.utils.cookie_provider import WafBlockDetected

# Minimal valid bill page -- just enough structure for scrape_bill() to parse
# a Bill successfully once the WAF-block circuit breaker lets it through.
VALID_BILL_HTML = b"""
<html><body>
<div id="ObjectSubject">A bill about testing</div>
<h1 id="BillHeading">House Bill No. 1</h1>
<div id="History"><table><tbody></tbody></table></div>
</body></html>
"""

BILL_URL = "https://legislature.mi.gov/Bills/Bill?ObjectName=2025-HB-0001"


def _make_scraper():
    return MIBillScraper(None, tempfile.mkdtemp())


def _always_blocked(monkeypatch):
    monkeypatch.setattr(
        "mi.bills.mi_waf_get",
        lambda request_func: (_ for _ in ()).throw(WafBlockDetected("blocked")),
    )


def test_scrape_bill_skips_and_continues_below_threshold(monkeypatch):
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    result = list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))

    assert result == []
    assert scraper._consecutive_waf_blocks == 1


def test_scrape_bill_aborts_after_max_consecutive_blocks(monkeypatch):
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    for _ in range(MAX_CONSECUTIVE_WAF_BLOCKS - 1):
        result = list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))
        assert result == []

    with pytest.raises(ScrapeError):
        list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))

    assert scraper._consecutive_waf_blocks == MAX_CONSECUTIVE_WAF_BLOCKS


def test_scrape_bill_resets_counter_after_successful_fetch(monkeypatch):
    scraper = _make_scraper()

    class FakeResponse:
        content = VALID_BILL_HTML

    calls = {"count": 0}

    def flaky_then_success(request_func):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise WafBlockDetected("blocked")
        return FakeResponse()

    monkeypatch.setattr("mi.bills.mi_waf_get", flaky_then_success)

    # Two blocks (below threshold), then a successful fetch -- must yield the
    # bill and reset the counter, not carry the near-threshold count forward.
    list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))
    list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))
    bills = list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))

    assert len(bills) == 1
    assert bills[0].identifier == "HB 0001"
    assert scraper._consecutive_waf_blocks == 0

    # Confirms the reset actually took effect: a single subsequent block must
    # not abort (only 1 of MAX_CONSECUTIVE_WAF_BLOCKS since the reset).
    monkeypatch.setattr(
        "mi.bills.mi_waf_get",
        lambda request_func: (_ for _ in ()).throw(WafBlockDetected("blocked")),
    )
    result = list(scraper.scrape_bill("2025-2026", "HB 0001", BILL_URL))
    assert result == []
    assert scraper._consecutive_waf_blocks == 1
