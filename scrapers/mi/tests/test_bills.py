import tempfile

import lxml.html
import pytest
import scrapelib

from mi._waf_circuit_breaker import MAX_CONSECUTIVE_WAF_BLOCKS
from mi.bills import MIBillScraper
from openstates.exceptions import ScrapeError
from openstates.scrape import Bill
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


# --- OPEN-30: parse_roll_call()/scrape_votes() failure-path coverage ---
#
# Before OPEN-30, parse_roll_call()'s except block just logged and returned
# None on scrapelib.HTTPError/WafBlockDetected -- invisible to
# _consecutive_waf_blocks, the abort threshold, and OPEN-22's escalation
# history. These tests mirror the scrape_bill()/scrape_event_page() shape
# above, applied to the per-vote-document fetch.

ROLL_CALL_URL = (
    "https://legislature.mi.gov/documents/2025-2026/Journal/House/htm/2025-HJ-07-03-300.htm"
)

# Minimal valid roll-call journal document -- just enough <p> structure for
# parse_roll_call() to find "Roll Call No. 1", collect a Yeas and a Nays
# piece, then stop at the next "In The Chair:" marker.
VALID_ROLL_CALL_HTML = """
<html><body>
<p>In The Chair: Speaker Someone</p>
<p>Roll Call No. 1</p>
<p>Yeas</p>
<p>  Smith    Jones  </p>
<p>Nays</p>
<p>  Doe  </p>
<p>In The Chair: Someone Else</p>
</body></html>
"""

# scrape_votes()'s History-table page with a single roll-call row, wired to
# ROLL_CALL_URL's objectname via the journal link's ObjectName param.
HISTORY_PAGE_WITH_ONE_VOTE_HTML = b"""
<html><body>
<div id="History"><table><tbody>
<tr>
<td>07/03/2026</td>
<td><a href="https://legislature.mi.gov/mileg.aspx?page=getObject&objectName=2025-HJ-07-03-300">HJ 123</a></td>
<td>Roll Call #300 YEAS 55 NAYS 45</td>
</tr>
</tbody></table></div>
</body></html>
"""


class FakeVoteResponse:
    def __init__(self, text):
        self.text = text


def test_parse_roll_call_registers_waf_block_on_waf_block_detected(monkeypatch):
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    result = scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")

    assert result is None
    assert scraper._consecutive_waf_blocks == 1


def test_parse_roll_call_registers_waf_block_on_http_error(monkeypatch):
    scraper = _make_scraper()

    class FakeHTTPResponse:
        status_code = 503
        url = ROLL_CALL_URL
        text = "Service Unavailable"

    http_error = scrapelib.HTTPError(FakeHTTPResponse())
    monkeypatch.setattr(
        "mi.bills.mi_waf_get",
        lambda request_func: (_ for _ in ()).throw(http_error),
    )

    result = scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")

    assert result is None
    assert scraper._consecutive_waf_blocks == 1


def test_parse_roll_call_aborts_after_max_consecutive_blocks(monkeypatch):
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    for _ in range(MAX_CONSECUTIVE_WAF_BLOCKS - 1):
        result = scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")
        assert result is None

    with pytest.raises(ScrapeError):
        scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")

    assert scraper._consecutive_waf_blocks == MAX_CONSECUTIVE_WAF_BLOCKS


def test_parse_roll_call_resets_counter_after_successful_fetch(monkeypatch):
    scraper = _make_scraper()
    calls = {"count": 0}

    def flaky_then_success(request_func):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise WafBlockDetected("blocked")
        return FakeVoteResponse(VALID_ROLL_CALL_HTML)

    monkeypatch.setattr("mi.bills.mi_waf_get", flaky_then_success)

    # Two blocks (below threshold), then a successful fetch -- must parse the
    # vote and reset the counter, not carry the near-threshold count forward.
    scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")
    scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")
    results = scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")

    assert results["yes"] == ["Smith", "Jones"]
    assert results["no"] == ["Doe"]
    assert scraper._consecutive_waf_blocks == 0

    # Confirms the reset actually took effect: a single subsequent block must
    # not abort (only 1 of MAX_CONSECUTIVE_WAF_BLOCKS since the reset).
    _always_blocked(monkeypatch)
    result = scraper.parse_roll_call(ROLL_CALL_URL, "1", "2025-2026")
    assert result is None
    assert scraper._consecutive_waf_blocks == 1


def test_scrape_votes_skips_vote_on_persistent_fetch_failure_but_continues(monkeypatch):
    # End-to-end through scrape_votes() (not just parse_roll_call() in
    # isolation) -- proves a persistently-blocked per-vote fetch yields no
    # VoteEvent (not a crash) while making the failure visible via the shared
    # circuit-breaker counter, instead of silently disappearing (OPEN-30 AC2).
    scraper = _make_scraper()
    _always_blocked(monkeypatch)

    bill = Bill(
        "HB 0001", "2025-2026", "A bill about testing", chamber="lower", classification="bill"
    )
    page = lxml.html.fromstring(HISTORY_PAGE_WITH_ONE_VOTE_HTML)

    votes = list(scraper.scrape_votes(bill, page))

    assert votes == []
    assert scraper._consecutive_waf_blocks == 1


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-81: bill_no= targeting -- scopes scrape() to just the requested bill(s)
# within the one search-results fetch, instead of every matching bill.
# ═══════════════════════════════════════════════════════════════════════════

# Real search-result link text is short form ("HB 0001 of 2025"), confirmed live against
# legislature.mi.gov -- distinct from the bill *detail* page's <h1 id="BillHeading"> long-form
# heading ("House Bill No. 1") used elsewhere in this file. Conflating the two was a real bug
# caught by a live test (OPEN-81): the original version of this fixture used the long form,
# which made _mi_bill_id_to_no() match nothing against a real search page and yielded zero bills.
SEARCH_RESULTS_HTML = b"""
<html><body>
<div class="tableScrollWrapper">
<table><tbody>
<tr><td><a href="/Bills/Bill?objectName=2025-HB-4023">HB 4023 of 2025</a></td></tr>
<tr><td><a href="/Bills/Bill?objectName=2025-SB-0205">SB 0205 of 2025</a></td></tr>
<tr><td><a href="/Bills/Bill?objectName=2025-HB-9999">HB 9999 of 2025</a></td></tr>
</tbody></table>
</div>
</body></html>
"""


def _mock_search_page(monkeypatch):
    class FakeResponse:
        content = SEARCH_RESULTS_HTML

    monkeypatch.setattr("mi.bills.mi_waf_get", lambda request_func: FakeResponse())


def test_mi_bill_id_to_no_normalizes_search_result_text():
    from mi.bills import _mi_bill_id_to_no

    assert _mi_bill_id_to_no("HB 4023") == "HB4023"
    assert _mi_bill_id_to_no("SB 0205") == "SB205"
    assert _mi_bill_id_to_no("HB 0001") == "HB1"
    assert _mi_bill_id_to_no("HJR A") == "HJRA"
    assert _mi_bill_id_to_no("SCR 0003") == "SCR3"


def test_scrape_with_bill_no_only_scrapes_the_matching_bill(monkeypatch):
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)

    scraped_ids = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda session, bill_id, url: scraped_ids.append(bill_id) or iter(()),
    )

    list(scraper.scrape("2025-2026", bill_no="HB4023"))

    assert scraped_ids == ["HB 4023"]


def test_scrape_with_multi_bill_no_scrapes_all_requested_bills_only(monkeypatch):
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)

    scraped_ids = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda session, bill_id, url: scraped_ids.append(bill_id) or iter(()),
    )

    list(scraper.scrape("2025-2026", bill_no="HB4023,SB205"))

    assert scraped_ids == ["HB 4023", "SB 0205"]


def test_scrape_without_bill_no_scrapes_every_bill_unchanged(monkeypatch):
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)

    scraped_ids = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda session, bill_id, url: scraped_ids.append(bill_id) or iter(()),
    )

    list(scraper.scrape("2025-2026"))

    assert scraped_ids == [
        "HB 4023",
        "SB 0205",
        "HB 9999",
    ]
