"""Shared WAF-block circuit breaker for MI scrapers.

OPEN-18 established the pattern in MIBillScraper.scrape_bill(): count
consecutive WafBlockDetected occurrences (even after mi_waf_get's own
one-time cookie re-warm) and abort the whole scrape with ScrapeError once
MAX_CONSECUTIVE_WAF_BLOCKS is reached, rather than silently skipping item
after item forever. OPEN-22 (AC7) extends the same mechanism to
MIEventScraper so the two scrapers don't drift into two different
abort conventions -- see mi_waf_get's own docstring in bills.py for the
precedent on keeping this kind of shared contract in exactly one place.

OPEN-30 extends registration to MIBillScraper.parse_roll_call(), which
(unlike the two call sites above) catches both scrapelib.HTTPError and
WafBlockDetected in one except block -- so _register_waf_block_or_abort()
below accepts either exception type.

OPEN-54: the actual threshold-check/abort decision now lives in
openstates.utils.waf_circuit_breaker (shared with the archiver's own circuit
breaker, OPEN-52), and the threshold value itself comes from MI's resilience
profile rather than being hardcoded here -- this module is now a thin,
MI-specific wrapper kept for its existing call sites (bills.py/events.py's
self._register_waf_block_or_abort()/self._register_waf_success()) and its
existing per-instance `_consecutive_waf_blocks` attribute, both left
unchanged so nothing calling into this mixin needed to change.
"""

from openstates.utils.resilience_profiles import RESILIENCE_PROFILES
from openstates.utils.waf_circuit_breaker import raise_if_waf_block_threshold_reached

MAX_CONSECUTIVE_WAF_BLOCKS = RESILIENCE_PROFILES["mi"].circuit_breaker_max_consecutive_blocks


class MIWafCircuitBreakerMixin:
    """Gives a Scraper subclass a per-instance consecutive-WAF-block counter.

    Call _register_waf_block_or_abort() from a WafBlockDetected (or, for
    parse_roll_call(), scrapelib.HTTPError) except-block -- for a call site
    that runs in a per-item loop -- e.g. one bill, one event, or one vote
    document per call -- and _register_waf_success() after a fetch succeeds.
    Raises ScrapeError once MAX_CONSECUTIVE_WAF_BLOCKS consecutive blocks
    have been registered without an intervening success.
    """

    _consecutive_waf_blocks = 0

    def _register_waf_block_or_abort(
        self,
        exc: Exception,
        item_label: str,
        scrape_label: str,
        fetch_description: str,
    ) -> None:
        self._consecutive_waf_blocks += 1
        self.warning(
            f"Skipping {item_label}: WAF block detected even after cookie "
            f"re-warm ({exc}) -- consecutive blocks: {self._consecutive_waf_blocks}"
        )
        raise_if_waf_block_threshold_reached(
            self._consecutive_waf_blocks,
            MAX_CONSECUTIVE_WAF_BLOCKS,
            exc,
            scrape_label=scrape_label,
            fetch_description=fetch_description,
        )

    def _register_waf_success(self) -> None:
        self._consecutive_waf_blocks = 0
