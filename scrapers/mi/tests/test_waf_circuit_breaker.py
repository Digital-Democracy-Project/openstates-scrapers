import pytest

from mi._waf_circuit_breaker import MAX_CONSECUTIVE_WAF_BLOCKS, MIWafCircuitBreakerMixin
from openstates.exceptions import ScrapeError
from openstates.utils.cookie_provider import WafBlockDetected


class _FakeWafScraper(MIWafCircuitBreakerMixin):
    """Minimal stand-in for a Scraper subclass -- exercises the mixin directly
    without needing a real Scraper's scrapelib/cache-dir setup, matching the
    style test_waf_get.py already uses to test mi_waf_get() in isolation."""

    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


def _block(scraper, item_label="item"):
    scraper._register_waf_block_or_abort(
        WafBlockDetected("blocked"),
        item_label=item_label,
        scrape_label="MI test scrape",
        fetch_description="fetching test pages",
    )


def test_single_block_does_not_raise_and_increments_counter():
    scraper = _FakeWafScraper()

    _block(scraper)

    assert scraper._consecutive_waf_blocks == 1
    assert len(scraper.warnings) == 1


def test_reaching_threshold_raises_scrape_error():
    scraper = _FakeWafScraper()

    for _ in range(MAX_CONSECUTIVE_WAF_BLOCKS - 1):
        _block(scraper)

    with pytest.raises(ScrapeError):
        _block(scraper)

    assert scraper._consecutive_waf_blocks == MAX_CONSECUTIVE_WAF_BLOCKS


def test_success_resets_counter_so_a_fresh_run_of_blocks_is_needed_to_trip_again():
    scraper = _FakeWafScraper()

    _block(scraper)
    assert scraper._consecutive_waf_blocks == 1

    scraper._register_waf_success()
    assert scraper._consecutive_waf_blocks == 0

    # Only one block since the reset -- must not raise even though two blocks
    # happened across the scraper's lifetime.
    _block(scraper)
    assert scraper._consecutive_waf_blocks == 1
