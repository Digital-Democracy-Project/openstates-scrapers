"""Tests for OPEN-63 and OPEN-66: flhouse.gov's House-vote chain is 3 sequential
fetches -- HouseSearchPage (search by bill number) -> HouseBillPage (bill detail
page, extracts "See Votes" links) -> HouseComVote (the vote tally page). Each hop
is exposed to the same transient F5 WAF "Request Rejected" page (or, rarely, a
genuine 404), which can be served with an HTTP 200 status.

OPEN-63 gave HouseSearchPage (hop 1) a bounded-retry accept_response(). OPEN-66
found the exact same failure mode still hits hops 2 and 3 completely unprotected
and completely silently: HouseBillPage's selector has min_items=0 (zero "See
Votes" links just silently yields nothing) and HouseComVote's process_page only
acts inside an `if lblTotal spans found` guard with no else -- so a WAF block at
either hop produced a missing bill vote with no retry and no log line anywhere,
indistinguishable from a bill that legitimately had no House committee action.

accept_response's return value feeds spatula's own retry loop (Page._fetch_data):
False triggers a real re-fetch (re-invoking _FLHouseWAFSource.get_response, which
drops flhouse.gov cookies) up to the source's `retries` budget before spatula
itself would raise RejectedResponse and crash the scrape. These tests call
accept_response directly, simulating what spatula would feed it across retries.
"""
import os
import sys
from types import SimpleNamespace

import lxml.html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from fl.bills import (  # noqa: E402
    HouseSearchPage,
    HouseBillPage,
    HouseComVote,
    FLHOUSE_WAF_MAX_ATTEMPTS,
    _FLHouseWAFSource,
)


NOT_FOUND_HTML = b"""
<html><body>
<div class="page-404">
We're Sorry, the page you requested can not <br/> be located within FLHouse.gov
</div>
</body></html>
"""

WAF_REJECTED_HTML = b"""
<html><head><title>Request Rejected</title></head><body></body></html>
"""

EMPTY_RESULTS_HTML = b"""
<html><body><div class="no-results">No records found</div></body></html>
"""

REAL_RESULTS_HTML = b"""
<html><body>
<a href="/Bills/billsdetail.aspx?BillId=12345">HB 1295</a>
</body></html>
"""

# HouseBillPage fixtures -- a clean page with zero "See Votes" links is a normal,
# common state (a bill with no House committee action), distinct from a WAF block.
NO_VOTE_LINKS_HTML = b"""
<html><body><p>No committee action recorded.</p></body></html>
"""

REAL_VOTE_LINK_HTML = b"""
<html><body>
<a href="/Sections/Committees/billvote.aspx?VoteId=1&IsPCB=0&BillId=1">See Votes</a>
</body></html>
"""

# HouseComVote fixtures.
NO_VOTE_TOTALS_HTML = b"""
<html><body><p>Nothing here.</p></body></html>
"""

REAL_VOTE_TOTALS_HTML = b"""
<html><body>
<span id="ctl00_MainContent_lblTotal">14</span>
</body></html>
"""


class FakeResponse:
    def __init__(self, content, url="https://flhouse.gov/Sections/Bills/bills.aspx?x=1"):
        self.content = content
        self.url = url


def make_page():
    return HouseSearchPage(None)


def make_bill_page():
    return HouseBillPage(None)


def make_com_vote_page():
    return HouseComVote(None)


# ── genuine "bill not found" -- never retries ───────────────────────────────

def test_accept_response_bill_not_found_accepts_immediately_with_no_retry():
    page = make_page()

    accepted = page.accept_response(FakeResponse(NOT_FOUND_HTML))

    assert accepted is True
    # Doesn't count against the retry budget -- a genuinely absent bill isn't a
    # failure to recover from.
    assert getattr(page, "_house_search_attempts", 0) == 0


# ── WAF "Request Rejected" -- retries, then succeeds or gives up ───────────

def test_accept_response_waf_rejected_retries_then_succeeds_on_real_content():
    page = make_page()

    first = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    second = page.accept_response(FakeResponse(REAL_RESULTS_HTML))

    assert first is False
    assert second is True


def test_accept_response_waf_rejected_exhausts_retries_and_falls_back_to_skip():
    page = make_page()
    assert page.HOUSE_SEARCH_MAX_ATTEMPTS == 3

    first = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    second = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    third = page.accept_response(FakeResponse(WAF_REJECTED_HTML))

    assert [first, second, third] == [False, False, True]


# ── empty results, no recognized marker -- same bounded retry treatment ────

def test_accept_response_empty_results_retries_then_succeeds_on_real_content():
    page = make_page()

    first = page.accept_response(FakeResponse(EMPTY_RESULTS_HTML))
    second = page.accept_response(FakeResponse(REAL_RESULTS_HTML))

    assert first is False
    assert second is True


def test_accept_response_empty_results_exhausts_retries_and_falls_back_to_skip():
    page = make_page()

    first = page.accept_response(FakeResponse(EMPTY_RESULTS_HTML))
    second = page.accept_response(FakeResponse(EMPTY_RESULTS_HTML))
    third = page.accept_response(FakeResponse(EMPTY_RESULTS_HTML))

    assert [first, second, third] == [False, False, True]


# ── real content on the first try -- accepted immediately, no retry needed ─

def test_accept_response_real_content_accepts_immediately():
    page = make_page()

    accepted = page.accept_response(FakeResponse(REAL_RESULTS_HTML))

    assert accepted is True
    assert page._house_search_attempts == 1


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-66: HouseBillPage (hop 2) -- previously had no accept_response at all.
# ═══════════════════════════════════════════════════════════════════════════

def test_house_bill_page_not_found_accepts_immediately_with_no_retry():
    page = make_bill_page()

    accepted = page.accept_response(FakeResponse(NOT_FOUND_HTML))

    assert accepted is True
    assert getattr(page, "_house_bill_attempts", 0) == 0


def test_house_bill_page_waf_rejected_retries_then_succeeds_on_real_content():
    page = make_bill_page()

    first = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    second = page.accept_response(FakeResponse(REAL_VOTE_LINK_HTML))

    assert first is False
    assert second is True


def test_house_bill_page_waf_rejected_exhausts_retries_and_falls_back_to_skip():
    page = make_bill_page()
    assert FLHOUSE_WAF_MAX_ATTEMPTS == 3

    first = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    second = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    third = page.accept_response(FakeResponse(WAF_REJECTED_HTML))

    assert [first, second, third] == [False, False, True]


def test_house_bill_page_real_vote_link_accepts_immediately():
    page = make_bill_page()

    accepted = page.accept_response(FakeResponse(REAL_VOTE_LINK_HTML))

    assert accepted is True
    assert page._house_bill_attempts == 1


def test_house_bill_page_zero_vote_links_accepts_without_retry():
    # Distinct from HouseSearchPage's empty-results case: a clean page with no
    # "See Votes" link is a normal, common state (no committee action), not a
    # failure to recover from -- it must NOT be retried.
    page = make_bill_page()

    accepted = page.accept_response(FakeResponse(NO_VOTE_LINKS_HTML))

    assert accepted is True
    assert page._house_bill_attempts == 1


def test_house_bill_page_zero_vote_links_logs_info(caplog):
    page = make_bill_page()

    with caplog.at_level("INFO"):
        page.accept_response(FakeResponse(NO_VOTE_LINKS_HTML))

    assert any("No 'See Votes' links found" in record.message for record in caplog.records)


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-66: HouseComVote (hop 3) -- previously had no accept_response at all.
# ═══════════════════════════════════════════════════════════════════════════

def test_house_com_vote_not_found_accepts_immediately_with_no_retry():
    page = make_com_vote_page()

    accepted = page.accept_response(FakeResponse(NOT_FOUND_HTML))

    assert accepted is True
    assert getattr(page, "_house_com_vote_attempts", 0) == 0


def test_house_com_vote_waf_rejected_retries_then_succeeds_on_real_content():
    page = make_com_vote_page()

    first = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    second = page.accept_response(FakeResponse(REAL_VOTE_TOTALS_HTML))

    assert first is False
    assert second is True


def test_house_com_vote_waf_rejected_exhausts_retries_and_falls_back_to_skip():
    page = make_com_vote_page()

    first = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    second = page.accept_response(FakeResponse(WAF_REJECTED_HTML))
    third = page.accept_response(FakeResponse(WAF_REJECTED_HTML))

    assert [first, second, third] == [False, False, True]


def test_house_com_vote_real_totals_accepts_immediately():
    page = make_com_vote_page()

    accepted = page.accept_response(FakeResponse(REAL_VOTE_TOTALS_HTML))

    assert accepted is True
    assert page._house_com_vote_attempts == 1


def test_house_com_vote_missing_totals_logs_warning_via_process_page(caplog):
    # accept_response doesn't retry on a missing lblTotal span (unlike a WAF
    # block) -- process_page's own else branch is what surfaces this, since
    # reaching this page at all means a real "See Votes" link was followed,
    # making an empty result here more suspicious than HouseBillPage's case.
    page = HouseComVote(SimpleNamespace(identifier="HB 53"))
    page.source = SimpleNamespace(url="https://flhouse.gov/billvote.aspx?VoteId=1")
    page.root = lxml.html.fromstring(NO_VOTE_TOTALS_HTML)

    with caplog.at_level("WARNING"):
        result = page.process_page()

    assert result is None
    assert any(
        "No vote totals found on House committee vote page" in record.message
        for record in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-66: regression guard -- hop 2 and hop 3 must construct their sources via
# _FLHouseWAFSource, not plain URL, or the exact asymmetry that caused this
# ticket (fix landing on hop 1 only) will silently reappear.
# ═══════════════════════════════════════════════════════════════════════════

def test_house_search_page_builds_house_bill_page_source_via_waf_source():
    page = make_page()

    bill_page = page.process_item("https://flhouse.gov/Sections/Bills/billsdetail.aspx?BillId=1")

    assert isinstance(bill_page, HouseBillPage)
    assert isinstance(bill_page.source, _FLHouseWAFSource)
    assert bill_page.source.retries == FLHOUSE_WAF_MAX_ATTEMPTS


def test_house_bill_page_builds_house_com_vote_source_via_waf_source():
    page = make_bill_page()

    vote_page = page.process_item(
        "https://flhouse.gov/Sections/Committees/billvote.aspx?VoteId=1"
    )

    assert isinstance(vote_page, HouseComVote)
    assert isinstance(vote_page.source, _FLHouseWAFSource)
    assert vote_page.source.retries == FLHOUSE_WAF_MAX_ATTEMPTS
