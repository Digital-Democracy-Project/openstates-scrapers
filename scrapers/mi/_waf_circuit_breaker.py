"""Shared WAF-block circuit breaker for MI scrapers.

OPEN-18 established the pattern in MIBillScraper.scrape_bill(): count
consecutive WafBlockDetected occurrences (even after mi_waf_get's own
one-time cookie re-warm) and abort the whole scrape with ScrapeError once
MAX_CONSECUTIVE_WAF_BLOCKS is reached, rather than silently skipping item
after item forever. OPEN-22 (AC7) extends the same mechanism to
MIEventScraper so the two scrapers don't drift into two different
abort conventions -- see mi_waf_get's own docstring in bills.py for the
precedent on keeping this kind of shared contract in exactly one place.
"""

from openstates.exceptions import ScrapeError
from openstates.utils.cookie_provider import WafBlockDetected

MAX_CONSECUTIVE_WAF_BLOCKS = 3


class MIWafCircuitBreakerMixin:
    """Gives a Scraper subclass a per-instance consecutive-WAF-block counter.

    Call _register_waf_block_or_abort() from a WafBlockDetected except-block
    (for a call site that runs in a per-item loop -- e.g. one bill or one
    event per call), and _register_waf_success() after a fetch succeeds.
    Raises ScrapeError once MAX_CONSECUTIVE_WAF_BLOCKS consecutive blocks
    have been registered without an intervening success.
    """

    _consecutive_waf_blocks = 0

    def _register_waf_block_or_abort(
        self,
        exc: WafBlockDetected,
        item_label: str,
        scrape_label: str,
        fetch_description: str,
    ) -> None:
        self._consecutive_waf_blocks += 1
        self.warning(
            f"Skipping {item_label}: WAF block detected even after cookie "
            f"re-warm ({exc}) -- consecutive blocks: {self._consecutive_waf_blocks}"
        )
        if self._consecutive_waf_blocks >= MAX_CONSECUTIVE_WAF_BLOCKS:
            raise ScrapeError(
                f"{scrape_label} aborted: {self._consecutive_waf_blocks} consecutive "
                f"WAF blocks detected {fetch_description} -- legislature.mi.gov is "
                "likely blocking this run entirely (OPEN-18)"
            ) from exc

    def _register_waf_success(self) -> None:
        self._consecutive_waf_blocks = 0
