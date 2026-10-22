import logging
import os
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

ROLL_CALL_URL = "https://legislature.mi.gov/documents/2025-2026/Journal/House/htm/2025-HJ-07-03-300.htm"

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
    def __init__(self, text, encoding="utf-8"):
        self.text = text
        # parse_roll_call() parses the bytes (upstream #5889: journals are UTF-8 but the
        # response headers do not say so), so the fake has to carry them too.
        self.content = text.encode(encoding)


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
        "HB 0001",
        "2025-2026",
        "A bill about testing",
        chamber="lower",
        classification="bill",
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
# OPEN-134: rows now carry the two further cells the real results page has -- Type in td[2] and
# the description ending in "Last Action: <text>" in td[3]. Previously each row was a bare link
# cell, which no longer models the page: the scraper reads recency off td[3] and refuses to make
# skip decisions when a page that lists bills yields no parseable last actions. Adding them keeps
# these fixtures a faithful model of the page rather than a shape the site never serves.
SEARCH_RESULTS_HTML = b"""
<html><body>
<div class="tableScrollWrapper">
<table><tbody>
<tr><td><a href="/Bills/Bill?objectName=2025-HB-4023">HB 4023 of 2025</a></td>
    <td>House Bill</td>
    <td>An act about something.<br />Last Action: referred to Committee on Rules</td></tr>
<tr><td><a href="/Bills/Bill?objectName=2025-SB-0205">SB 0205 of 2025</a></td>
    <td>Senate Bill</td>
    <td>An act about something else.<br />Last Action: adopted</td></tr>
<tr><td><a href="/Bills/Bill?objectName=2025-HB-9999">HB 9999 of 2025</a></td>
    <td>House Bill</td>
    <td>A third act.<br />Last Action: reported with recommendation</td></tr>
</tbody></table>
</div>
</body></html>
"""


def _mock_search_page(monkeypatch):
    class FakeResponse:
        content = SEARCH_RESULTS_HTML

    monkeypatch.setattr("mi.bills.mi_waf_get", lambda request_func: FakeResponse())
    # OPEN-134: a full run persists its last-action baseline under settings.CACHE_DIR. Left
    # unpatched that is the REAL cache directory, so a test run would overwrite the production
    # baseline for the live session -- a scraper-correctness landmine set by a unit test.
    # Redirect it per test; monkeypatch restores the original afterwards.
    monkeypatch.setattr("mi.bills.settings.CACHE_DIR", tempfile.mkdtemp())


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


# ---------------------------------------------------------------------------
# OPEN-132: a single-match search redirects to the bill page
#
# Both fixtures are real, unmodified response bodies lifted out of the production
# scrapelib cache (openstates-scrapers/_cache/), not hand-written approximations --
# the point of the ticket is that the live site's actual behaviour was misread, so a
# fixture that encoded our own assumption about the shape would prove nothing.
#
#   mi_search_single_match_redirect.html
#     ExecuteSearch?...&dateFrom=2026-07-19&...  cached 2026-07-25 22:00
#     This IS the response from the production run that silently dropped the bill:
#     <title>Senate Resolution 135 of 2026</title>, zero tableScrollWrapper elements.
#
#   mi_search_empty_results.html
#     ExecuteSearch?...&dateFrom=2026-08-16&...  cached 2026-08-22 22:00
#     A genuinely empty window: a real <title>Search Results</title> page with one
#     tableScrollWrapper and a header row only.
# ---------------------------------------------------------------------------

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _mock_response(monkeypatch, body):
    class FakeResponse:
        content = body

    monkeypatch.setattr("mi.bills.mi_waf_get", lambda request_func: FakeResponse())


def test_single_match_redirect_yields_the_dropped_bill(monkeypatch):
    """The 2026-07-25 response must now produce SR 0135 instead of nothing."""
    scraper = _make_scraper()
    # The search request and the follow-up bill fetch both land on this same page,
    # which is exactly what the redirect means.
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))

    bills = [obj for obj in scraper.scrape("2025-2026") if isinstance(obj, Bill)]

    assert len(bills) == 1
    # Identical to what the results-table path yields for this bill: the same window's
    # sibling searches list it as "SR 0135 of 2026" -> "SR 0135".
    assert bills[0].identifier == "SR 0135"
    assert bills[0].legislative_session == "2025-2026"


def test_single_match_redirect_resolves_identity_from_the_page():
    scraper = _make_scraper()
    page = lxml.html.fromstring(_fixture("mi_search_single_match_redirect.html"))

    assert scraper._redirected_single_bill(page) == (
        "SR 0135",
        "https://legislature.mi.gov/Bills/Bill?ObjectName=2026-SR-0135",
    )


def test_single_match_redirect_ignores_the_adjacent_bill_link():
    """SR 0135's page also links to SR 0134 and to journal ObjectNames.

    Reading identity from 'the first objectName= anywhere on the page' would pass on
    this fixture purely because of document order, so pin the real requirement: the
    bill we resolve is the page's own, never a neighbour.
    """
    scraper = _make_scraper()
    body = _fixture("mi_search_single_match_redirect.html")
    assert b"2026-SR-0134" in body, "fixture no longer exercises the neighbour hazard"

    page = lxml.html.fromstring(body)
    bill_id, bill_url = scraper._redirected_single_bill(page)

    assert "0134" not in bill_id and "0134" not in bill_url


def test_genuinely_empty_results_page_yields_nothing(monkeypatch):
    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_empty_results.html"))

    assert list(scraper.scrape("2025-2026")) == []


def test_empty_and_redirect_are_distinguishable(monkeypatch, caplog):
    """The core of the ticket: the two zero-row cases must not look alike."""
    caplog.set_level(logging.INFO)

    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_empty_results.html"))
    with caplog.at_level(logging.INFO):
        list(scraper.scrape("2025-2026"))
    empty_log = caplog.text
    caplog.clear()

    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))
    with caplog.at_level(logging.INFO):
        list(scraper.scrape("2025-2026"))
    redirect_log = caplog.text

    assert "genuine empty result" in empty_log
    assert "redirect" not in empty_log
    assert "redirected to its page" in redirect_log
    assert "SR 0135" in redirect_log
    assert empty_log != redirect_log


def test_unrecognised_response_shape_warns_instead_of_silent_no_op(monkeypatch, caplog):
    """Neither a results table nor a bill page must not pass as a clean no-op."""
    scraper = _make_scraper()
    _mock_response(
        monkeypatch, b"<html><body><p>nothing familiar here</p></body></html>"
    )

    with caplog.at_level(logging.WARNING):
        assert list(scraper.scrape("2025-2026")) == []

    assert "neither a results page nor a usable bill page" in caplog.text
    # This one really has no heading, so it must say so -- the "looks like a bill page"
    # wording is reserved for the case where h1#BillHeading is present.
    assert "no tableScrollWrapper and no h1#BillHeading" in caplog.text


# --- OPEN-132 follow-ups from review: the partial / bill-like-but-unusable shapes ---


def test_heading_confirms_bill_number_rejects_lookalikes():
    from mi.bills import _heading_confirms_bill_number

    heading = "Senate Resolution 135 of 2026"
    # the real number, padded and unpadded
    assert _heading_confirms_bill_number("0135", heading)
    assert _heading_confirms_bill_number("135", heading)
    # the adjacent bill, whose link is also present on the page
    assert not _heading_confirms_bill_number("0134", heading)
    # the year, and substrings of it -- a naive `num in heading` passes all of these
    assert not _heading_confirms_bill_number("2026", heading)
    assert not _heading_confirms_bill_number("26", heading)
    assert not _heading_confirms_bill_number("202", heading)
    # a substring of the real number
    assert not _heading_confirms_bill_number("13", heading)
    # an all-zero number must not match via the empty string
    assert not _heading_confirms_bill_number("0000", heading)


def test_heading_confirms_bill_number_accepts_real_heading_variants():
    from mi.bills import _heading_confirms_bill_number

    # Non-numeric bill numbers (joint resolutions are lettered).
    assert _heading_confirms_bill_number("AA", "House Joint Resolution AA of 2026")
    # 95 of the 3,924 cached MI bill pages carry a "(Public Act NN of YYYY)" suffix. A check
    # keyed on the heading ending in "of <year>" would reject every one of them -- a false
    # negative here is itself a silently dropped bill, which is the bug this guard exists for.
    assert _heading_confirms_bill_number(
        "4961", "House Bill 4961 of 2025 (Public Act 24 of 2025)"
    )


def test_bill_page_without_self_referential_link_is_not_scraped_silently(
    monkeypatch, caplog
):
    """A bill page we cannot identify must warn, and say that it looked like a bill page."""
    scraper = _make_scraper()
    # h1#BillHeading present, but no printerFriendly/RSS link to read ObjectName from.
    _mock_response(
        monkeypatch,
        b"<html><body><h1 id='BillHeading'>Senate Resolution 135 of 2026</h1>"
        b"<a href='/Bills/Bill?ObjectName=2026-SR-0134'>SR 134</a></body></html>",
    )

    with caplog.at_level(logging.WARNING):
        assert list(scraper.scrape("2025-2026")) == []

    # Must not be described as "no BillHeading" when the heading is right there, and must
    # not have quietly adopted the neighbouring bill's ObjectName either.
    assert "looks like a bill page" in caplog.text
    assert "no h1#BillHeading" not in caplog.text
    assert "0134" not in caplog.text


def test_bill_page_with_mismatched_object_name_is_not_scraped(monkeypatch, caplog):
    scraper = _make_scraper()
    # Self-referential link present, but pointing at a different bill than the heading.
    _mock_response(
        monkeypatch,
        b"<html><body><h1 id='BillHeading'>Senate Resolution 135 of 2026</h1>"
        b"<a href='/Home/GetRSSFile?objectName=2026-SR-0134'>rss</a></body></html>",
    )

    with caplog.at_level(logging.WARNING):
        assert list(scraper.scrape("2025-2026")) == []

    assert "disagrees with page heading" in caplog.text


def test_malformed_object_name_is_not_scraped(monkeypatch, caplog):
    scraper = _make_scraper()
    # Not the "<year>-<type>-<number>" shape at all.
    _mock_response(
        monkeypatch,
        b"<html><body><h1 id='BillHeading'>Senate Resolution 135 of 2026</h1>"
        b"<a href='/Home/GetRSSFile?objectName=nonsense'>rss</a></body></html>",
    )

    with caplog.at_level(logging.WARNING):
        assert list(scraper.scrape("2025-2026")) == []

    assert "looks like a bill page" in caplog.text


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-123: warn when a requested bill_no matched nothing. Before this, a typo
# or stale number in a targeted backfill (MI's own OPEN-30/OPEN-81 vote
# backfill was exactly this workflow) scraped zero bills and exited cleanly.
# ═══════════════════════════════════════════════════════════════════════════


def _capture_warnings(scraper, monkeypatch):
    warnings = []
    monkeypatch.setattr(scraper, "warning", lambda msg: warnings.append(msg))
    monkeypatch.setattr(scraper, "scrape_bill", lambda session, bill_id, url: iter(()))
    return warnings


def test_scrape_warns_on_unmatched_bill_no(monkeypatch):
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026", bill_no="HB4023,HB404"))

    assert any("HB404" in msg for msg in warnings)
    assert not any("HB4023" in msg for msg in warnings)
    assert any("2025-2026" in msg for msg in warnings)


def test_scrape_does_not_warn_when_every_requested_bill_no_matched(monkeypatch):
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026", bill_no="HB4023,SB205"))

    assert warnings == []


def test_scrape_does_not_warn_on_leading_zero_difference(monkeypatch):
    # The search page's "SB 0205" must satisfy a requested "SB205": the matched
    # set is keyed with the same _mi_bill_id_to_no() used to filter, so the
    # padding difference cannot produce a false "not found".
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026", bill_no="SB205"))

    assert warnings == []


def test_scrape_without_bill_no_never_warns(monkeypatch):
    # bill_no is unset on every scheduled production run -- that path must not
    # gain any new warning behaviour.
    scraper = _make_scraper()
    _mock_search_page(monkeypatch)
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026"))

    assert warnings == []


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-132 x OPEN-123 interaction. The single-match-redirect branch returns
# before scrape()'s end-of-run unmatched check, so it needs its own call to
# the same warning. Without these tests, a targeted request the redirect
# didn't land on is a silent no-op -- the very failure class both tickets
# exist to remove, reintroduced in the one path OPEN-123 predates.
# ═══════════════════════════════════════════════════════════════════════════


def test_single_match_redirect_warns_when_it_is_not_the_requested_bill(monkeypatch):
    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))
    warnings = _capture_warnings(scraper, monkeypatch)

    # The redirect lands on SR 0135; HB9999 is what the operator asked for.
    yielded = list(scraper.scrape("2025-2026", bill_no="HB9999"))

    assert yielded == []
    assert any("HB9999" in msg for msg in warnings)
    assert any("2025-2026" in msg for msg in warnings)


def test_single_match_redirect_warns_only_about_the_bills_it_did_not_land_on(
    monkeypatch,
):
    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026", bill_no="SR135,HB9999"))

    # SR135 is the bill the redirect resolved to, so it must not be reported missing.
    assert any("HB9999" in msg for msg in warnings)
    assert not any("SR135" in msg for msg in warnings)


def test_single_match_redirect_still_scrapes_the_requested_bill(monkeypatch):
    # The guard above must not cost us the bill when it IS the one requested.
    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))

    bills = [
        obj
        for obj in scraper.scrape("2025-2026", bill_no="SR135")
        if isinstance(obj, Bill)
    ]

    assert len(bills) == 1


def test_single_match_redirect_never_warns_when_no_bill_no_was_requested(monkeypatch):
    # bill_no is unset on every scheduled production run. That path must gain no
    # filtering and no new warnings from the helper the redirect branch now calls.
    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026"))

    assert warnings == []


def test_single_match_redirect_matches_across_a_leading_zero_difference(monkeypatch):
    # The redirect resolves "SR 0135"; a requested "SR135" must satisfy it. Both
    # sides go through _mi_bill_id_to_no(), so the padding difference must not
    # produce a bill that is scraped AND simultaneously reported missing.
    scraper = _make_scraper()
    _mock_response(monkeypatch, _fixture("mi_search_single_match_redirect.html"))
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape("2025-2026", bill_no="sr 0135"))

    assert warnings == []


# --- Upstream openstates-scrapers #5882 / #5830 / #5889 (OPEN-407) ---------------------------

# #5882: a bill the search results repeat at a pagination boundary is scraped once.
SEARCH_RESULTS_WITH_DUPLICATE_BILL = """
<html><body>
  <div class="tableScrollWrapper">
    <table><tbody>
      <tr><td><a href="/Home/GetObject?objectName=2025-HB-4841">HB 4841 of 2025</a></td></tr>
      <tr><td><a href="/Home/GetObject?objectName=2025-HB-4842">HB 4842 of 2025</a></td></tr>
      <tr><td><a href="/Home/GetObject?objectName=2025-HB-4841">HB 4841 of 2025</a></td></tr>
    </tbody></table>
  </div>
</body></html>
"""


def test_scrape_skips_duplicate_bill_urls_from_search_results(monkeypatch):
    scraper = _make_scraper()

    class FakeResponse:
        content = SEARCH_RESULTS_WITH_DUPLICATE_BILL

    monkeypatch.setattr("mi.bills.mi_waf_get", lambda request_func: FakeResponse())
    # A full run persists its last-action baseline under settings.CACHE_DIR (see
    # _mock_search_page); keep it off the real cache directory.
    monkeypatch.setattr("mi.bills.settings.CACHE_DIR", tempfile.mkdtemp())

    scraped_urls = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda session, bill_id, url: scraped_urls.append(url) or iter(()),
    )

    list(scraper.scrape("2025-2026"))

    assert scraped_urls == [
        "https://legislature.mi.gov/Bills/Bill?ObjectName=2025-HB-4841",
        "https://legislature.mi.gov/Bills/Bill?ObjectName=2025-HB-4842",
    ]


# #5830: Senate journals print a row of members as one line with single spaces ("Hauck
# Hoitenga Johnson"), and a few surnames contain a space ("McDonald Rivet"). The strings below
# are real voter names that were stored as ONE voter before this change (2025-2026 Senate).
SENATE_ROSTER = {
    "Albert", "Bellino", "Bumstead", "Daley", "Hauck", "Hoitenga", "Johnson", "Lindsey",
    "McBroom", "McDonald Rivet", "Nesbitt", "Runestad", "Theis", "Victory", "Webber", "Wojno",
}  # fmt: skip


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Hauck Hoitenga Johnson", ["Hauck", "Hoitenga", "Johnson"]),
        ("Runestad Theis Victory", ["Runestad", "Theis", "Victory"]),
        ("Albert Bellino Bumstead", ["Albert", "Bellino", "Bumstead"]),
        ("Webber Wojno", ["Webber", "Wojno"]),
        ("Bumstead Daley", ["Bumstead", "Daley"]),
        # a single name, and a name that itself contains a space, stay whole
        ("Lindsey", ["Lindsey"]),
        ("McDonald Rivet", ["McDonald Rivet"]),
        ("Theis McDonald Rivet Victory", ["Theis", "McDonald Rivet", "Victory"]),
    ],
)
def test_split_names_splits_a_collapsed_row_on_the_journals_roster(line, expected):
    assert MIBillScraper.split_names(line, SENATE_ROSTER) == expected


def test_split_names_leaves_a_line_that_is_not_entirely_member_names_untouched():
    # a sentence, or a name missing from the roster, must not be half-split
    assert MIBillScraper.split_names("Hauck Nobody Johnson", SENATE_ROSTER) == [
        "Hauck Nobody Johnson"
    ]
    assert MIBillScraper.split_names(
        "House Bill No. 4451, entitled", SENATE_ROSTER
    ) == ["House Bill No. 4451, entitled"]


def _journal(*pieces, charset="utf-8"):
    # The response headers do not name a charset, so the page has to: parse_roll_call() hands
    # lxml the bytes and lxml reads the declaration (see the tests at the end).
    head = f'<head><meta http-equiv="Content-Type" content="text/html; charset={charset}"></head>'
    return "<html>" + head + "<body>" + "".join(pieces) + "</body></html>"


# Synthetic journal built from the shapes upstream's change describes (no real Michigan page
# was fetched: the site is bot-protected, see OPEN-232/OPEN-333). The opening roll names every
# member; each header is a <p> or, for Excused/Not Voting, an <h4>.
SENATE_OPENING_ROLL = (
    "<p>Albert—present</p><p>Bellino—present</p><p>Hauck—present</p><p>Hoitenga—present</p>"
    "<p>Johnson—present</p><p>McDonald Rivet—present</p><p>Victory—excused</p>"
)


def _parse(monkeypatch, html, rc_num="184", session="2025-2026", encoding="utf-8"):
    scraper = _make_scraper()
    monkeypatch.setattr(
        "mi.bills.mi_waf_get", lambda request_func: FakeVoteResponse(html, encoding)
    )
    return scraper.parse_roll_call(ROLL_CALL_URL, rc_num, session)


def test_parse_roll_call_splits_fused_senate_names(monkeypatch):
    html = _journal(
        SENATE_OPENING_ROLL,
        "<p>Roll Call No. 184</p><p>Yeas—4</p>",
        "<p>Albert Bellino</p><p>Hauck Hoitenga</p>",
        "<p>Nays—1</p><p>McDonald Rivet</p>",
        "<p>In The Chair: Brinks</p>",
    )
    results = _parse(monkeypatch, html)

    assert results["yes"] == ["Albert", "Bellino", "Hauck", "Hoitenga"]
    assert results["no"] == ["McDonald Rivet"]


def test_parse_roll_call_reads_excused_header_printed_as_h4_without_adding_nays(
    monkeypatch,
):
    html = _journal(
        SENATE_OPENING_ROLL,
        "<p>Roll Call No. 184</p><p>Yeas—2</p><p>Albert Bellino</p>",
        "<p>Nays—1</p><p>Hauck</p>",
        "<h4>Excused—1</h4><p>Victory</p>",
        "<p>In The Chair: Brinks</p>",
    )
    results = _parse(monkeypatch, html)

    assert results["no"] == ["Hauck"]
    assert results["other"] == ["Victory"]


def test_parse_roll_call_handles_two_headers_on_one_line(monkeypatch):
    html = _journal(
        SENATE_OPENING_ROLL,
        "<p>Roll Call No. 184</p><p>Yeas—3</p><p>Albert Bellino Hauck</p>",
        "<p>Nays—0 Excused—1</p><p>Victory</p>",
        "<p>In The Chair: Brinks</p>",
    )
    results = _parse(monkeypatch, html)

    assert results["yes"] == ["Albert", "Bellino", "Hauck"]
    assert results["no"] == []
    assert results["other"] == ["Victory"]


def test_parse_roll_call_stops_at_the_next_roll_call_and_at_in_the_chair(monkeypatch):
    html = _journal(
        SENATE_OPENING_ROLL,
        "<p>Roll Call No. 184</p><p>Yeas—2</p><p>Albert Bellino</p>",
        # the last voters share a line with the chair marker
        "<p>Nays—1</p><p>Hauck In The Chair: Brinks</p>",
        "<p>Roll Call No. 185</p><p>Yeas—1</p><p>Johnson</p>",
    )
    results = _parse(monkeypatch, html)

    assert results["yes"] == ["Albert", "Bellino"]
    assert results["no"] == ["Hauck"]  # not Johnson from roll call 185
    assert "Johnson" not in sum(results.values(), [])


def test_parse_roll_call_decodes_a_declared_charset_in_the_bytes(monkeypatch):
    """#5889 parses the response bytes so lxml honours the charset the page declares. Word-made
    journals declare windows-1252, where the em dash is byte 0x97 and the apostrophe 0x92."""
    html = _journal(
        "<p>O’Neal—present</p><p>Roll Call No. 5</p><p>Yeas—1</p><p>O’Neal</p>",
        "<p>In The Chair: Someone</p>",
        charset="windows-1252",
    )
    results = _parse(monkeypatch, html, rc_num="5", encoding="cp1252")

    assert results["yes"] == ["O’Neal"]


def test_parse_roll_call_without_a_declared_charset_keeps_names_fused_but_does_not_crash(
    monkeypatch,
):
    """Documents the dependency in #5889/#5830: with no charset declared the em dash in the
    opening roll is not read, the roster comes out empty, and a collapsed row stays one
    string -- the pre-change result -- rather than raising."""
    html = (
        "<html><body>" + SENATE_OPENING_ROLL
        + "<p>Roll Call No. 184</p><p>Yeas—2</p><p>Albert Bellino</p>"
        + "<p>In The Chair: Brinks</p></body></html>"
    )  # fmt: skip
    results = _parse(monkeypatch, html)

    assert results["yes"] == ["Albert Bellino"]


# pm-review (OPEN-407): behaviour that must NOT change. House journals carry no "Name—present"
# opening roll, so the roster is empty and every line is passed through as it always was; the
# 2017-2018 branch still splits on whitespace. Both tests pass on the pre-change file too.


def test_parse_roll_call_house_journal_without_an_opening_roll_is_unchanged(
    monkeypatch,
):
    html = _journal(
        "<p>Roll Call No. 12</p><p>Yeas</p><p>Smith\tJones\tDoe</p>",
        "<p>Nays</p><p>Brown</p><p>Excused</p><p>Green</p>",
        "<p>In The Chair: Speaker Someone</p>",
    )
    results = _parse(monkeypatch, html, rc_num="12")

    assert results["yes"] == ["Smith", "Jones", "Doe"]
    assert results["no"] == ["Brown"]
    assert results["other"] == ["Green"]


def test_parse_roll_call_2017_2018_still_splits_on_whitespace(monkeypatch):
    html = _journal(
        "<p>Roll Call No. 7</p><p>Yeas</p><p>Smith  Jones</p><p>Nays</p><p>Brown</p>",
        "<p>In The Chair: Someone</p>",
    )
    results = _parse(monkeypatch, html, rc_num="7", session="2017-2018")

    assert results["yes"] == ["Smith", "Jones"]
    assert results["no"] == ["Brown"]
