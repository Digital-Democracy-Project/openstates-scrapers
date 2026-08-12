"""Tests for OPEN-63: HouseSearchPage.accept_response() had no retry on the one
failure mode that matters -- a transient flhouse.gov WAF "Request Rejected" page,
or a search page that (rarely) comes back with no matching results -- unrelated to
the systemic stale-cookie case PR #5/_FLHouseWAFSource already fixed. Both
branches unconditionally returned True, so a single one-off WAF challenge or
search miss permanently and silently zeroed that bill's House committee votes,
with zero retries at any level.

accept_response's return value feeds spatula's own retry loop (Page._fetch_data):
False triggers a real re-fetch (re-invoking _FLHouseWAFSource.get_response, which
drops flhouse.gov cookies) up to the source's `retries` budget before spatula
itself would raise RejectedResponse and crash the scrape. These tests call
accept_response directly, simulating what spatula would feed it across retries,
and prove: (1) a genuine "bill not found" page still accepts immediately with no
retry -- real absence, not a failure; (2) a WAF-rejected or empty-results page
retries and succeeds if a later attempt returns real content; (3) either failure
mode exhausts HOUSE_SEARCH_MAX_ATTEMPTS and falls back to today's accept+skip
behavior, never letting spatula's own budget run out.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from fl.bills import HouseSearchPage  # noqa: E402


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


class FakeResponse:
    def __init__(self, content, url="https://flhouse.gov/Sections/Bills/bills.aspx?x=1"):
        self.content = content
        self.url = url


def make_page():
    return HouseSearchPage(None)


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
