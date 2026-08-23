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
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from fl.bills import (  # noqa: E402
    HouseSearchPage,
    HouseBillPage,
    HouseComVote,
    FLHOUSE_WAF_MAX_ATTEMPTS,
    _FLHouseWAFSource,
    _FLHouseCookieProviderSource,
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
# a WAF-aware source, not plain URL, or the exact asymmetry that caused this
# ticket (fix landing on hop 1 only) will silently reappear.
#
# OPEN-84: that WAF-aware source is now _FLHouseCookieProviderSource (FL's real
# resilience profile, OPEN-54) rather than _FLHouseWAFSource's blind
# cookie-drop-and-retry -- these tests were updated in place rather than left
# asserting the superseded class, since the whole point of OPEN-84 is that
# _FLHouseWAFSource is no longer what any of the 3 hops actually fetch through.
# ═══════════════════════════════════════════════════════════════════════════

def test_house_search_page_builds_house_bill_page_source_via_waf_source():
    page = make_page()

    bill_page = page.process_item("https://flhouse.gov/Sections/Bills/billsdetail.aspx?BillId=1")

    assert isinstance(bill_page, HouseBillPage)
    assert isinstance(bill_page.source, _FLHouseCookieProviderSource)
    assert bill_page.source.retries == FLHOUSE_WAF_MAX_ATTEMPTS


def test_house_bill_page_builds_house_com_vote_source_via_waf_source():
    page = make_bill_page()

    vote_page = page.process_item(
        "https://flhouse.gov/Sections/Committees/billvote.aspx?VoteId=1"
    )

    assert isinstance(vote_page, HouseComVote)
    assert isinstance(vote_page.source, _FLHouseCookieProviderSource)
    assert vote_page.source.retries == FLHOUSE_WAF_MAX_ATTEMPTS


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-84: _FLHouseCookieProviderSource itself -- fetches via FL's resilience
# profile (RESILIENCE_PROFILES["fl"]/FL_COOKIE_PROVIDER) instead of blindly
# dropping/retrying cookies.
# ═══════════════════════════════════════════════════════════════════════════

def test_house_search_page_builds_its_own_source_via_cookie_provider():
    page = HouseSearchPage(
        SimpleNamespace(
            identifier="HB 1",
            legislative_session="2026",
            _fl_house_session_number="113",
        )
    )
    source = page.get_source_from_input()
    assert isinstance(source, _FLHouseCookieProviderSource)
    assert source.retries == HouseSearchPage.HOUSE_SEARCH_MAX_ATTEMPTS


def test_cookie_provider_source_attaches_cached_cookies_and_real_user_agent():
    from unittest import mock

    source = _FLHouseCookieProviderSource(
        "https://flhouse.gov/Sections/Bills/billsdetail.aspx?BillId=1", verify=False
    )
    fake_scraper = mock.Mock()
    fake_scraper.request.return_value = mock.Mock(content=b"real content, no block markers")

    with mock.patch(
        "fl.bills.RESILIENCE_PROFILES"
    ) as fake_profiles:
        fake_profile = fake_profiles.__getitem__.return_value
        fake_profile.cookie_provider.fetch_with_retry.side_effect = (
            lambda do_request: do_request(
                {"session_cookie_mfhp": "real-cookie-value"}, "Real Chrome UA"
            )
        )
        response = source.get_response(fake_scraper)

    assert response.content == b"real content, no block markers"
    fake_scraper.request.assert_called_once()
    call_kwargs = fake_scraper.request.call_args.kwargs
    assert call_kwargs["cookies"] == {"session_cookie_mfhp": "real-cookie-value"}
    assert call_kwargs["headers"]["User-Agent"] == "Real Chrome UA"


def test_cookie_provider_source_raises_wafblockdetected_on_block_page():
    from unittest import mock
    from openstates.utils.cookie_provider import WafBlockDetected

    source = _FLHouseCookieProviderSource(
        "https://flhouse.gov/Sections/Bills/billsdetail.aspx?BillId=1", verify=False
    )
    fake_scraper = mock.Mock()
    fake_scraper.request.return_value = mock.Mock(content=b"Request Rejected")

    with mock.patch("fl.bills.RESILIENCE_PROFILES") as fake_profiles:
        fake_profile = fake_profiles.__getitem__.return_value
        fake_profile.cookie_provider.fetch_with_retry.side_effect = (
            lambda do_request: do_request({"session_cookie_mfhp": "stale"}, "Some UA")
        )

        with pytest.raises(WafBlockDetected):
            source.get_response(fake_scraper)


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-123: warn when a requested bill_no matched nothing.
#
# FL is the awkward one of the five this ticket covers: it is a spatula
# page-based scraper, so the bill_no comparison lives in
# BillList.process_item() (which raises SkipItem per non-matching row), not in
# FlBillScraper.scrape(). The matched set therefore has to travel back out to
# scrape() to be diffed. It does so via the BillList input dict, which spatula
# hands to every paginated page *by reference* (Page._paginate does
# `type(self)(self.input, source=next_source)`), so one shared set collects
# matches from every list page. test_matched_bill_nos_accumulates_across_
# paginated_list_pages below pins that reference-sharing property, since the
# whole approach depends on it.
# ═══════════════════════════════════════════════════════════════════════════

import collections  # noqa: E402

from fl.bills import BillList, FlBillScraper  # noqa: E402
from fl import Florida  # noqa: E402
from spatula.pages import SkipItem  # noqa: E402
from spatula import URL  # noqa: E402


BILL_LIST_ROW_HTML = """
<table><tbody>
<tr>
  <th><a href="/Session/Bill/2026/53">{bill_id}</a></th>
  <td>A bill about testing</td>
  <td>Some committee</td>
  <td>3/1/2026</td>
</tr>
</tbody></table>
"""


def _bill_list_anchor(bill_id):
    root = lxml.html.fromstring(BILL_LIST_ROW_HTML.format(bill_id=bill_id))
    return root.xpath("//th/a")[0]


def _make_bill_list(bill_nos, matched_bill_nos):
    page = BillList(
        {
            "session": "2026",
            "house_session_number": "104",
            "start": None,
            "bill_nos": bill_nos,
            "matched_bill_nos": matched_bill_nos,
        }
    )
    # Normally injected by spatula's `dependencies` machinery (SubjectPDF);
    # process_item() reads it after the bill_no check to set bill.subject.
    page.subjects = collections.defaultdict(set)
    return page


def test_process_item_records_a_matching_bill_no_as_matched():
    matched = set()
    page = _make_bill_list({"HB53"}, matched)

    page.process_item(_bill_list_anchor("HB 53"))

    assert matched == {"HB53"}


def test_process_item_skips_and_does_not_record_a_non_matching_bill_no():
    matched = set()
    page = _make_bill_list({"HB53"}, matched)

    with pytest.raises(SkipItem):
        page.process_item(_bill_list_anchor("HB 999"))

    assert matched == set()


def test_process_item_records_match_despite_spacing_and_case_difference():
    # The list page's own "HB 53" must satisfy a requested "hb53" -- the matched
    # set has to be keyed the same way the comparison is, or the diff in scrape()
    # would warn about a bill it actually just scraped.
    matched = set()
    page = _make_bill_list({"HB53"}, matched)

    page.process_item(_bill_list_anchor("HB   53"))

    assert matched == {"HB53"}


def test_matched_bill_nos_accumulates_across_paginated_list_pages():
    # Reproduces what spatula's Page._paginate does between list pages, to prove
    # matches found on page 2 land in the same set FlBillScraper.scrape() holds.
    matched = set()
    page_one = _make_bill_list({"HB53", "SB99"}, matched)
    page_two = type(page_one)(page_one.input, source=URL("https://example.invalid/2"))
    page_two.subjects = collections.defaultdict(set)

    page_one.process_item(_bill_list_anchor("HB 53"))
    page_two.process_item(_bill_list_anchor("SB 99"))

    assert matched == {"HB53", "SB99"}


def _make_scraper_for_scrape(monkeypatch, walk):
    """FlBillScraper.scrape() with everything before/around the list walk stubbed.

    `walk` receives the BillList and stands in for _process_bill_list, letting a
    test say exactly which requested numbers the walk managed to match.
    """
    scraper = FlBillScraper(Florida(), "/tmp/")
    monkeypatch.setattr(scraper, "get_house_session_number", lambda session: "104")
    monkeypatch.setattr(scraper, "_create_fresh_session", lambda: None)
    monkeypatch.setattr(scraper, "_process_bill_list", walk)

    warnings = []
    monkeypatch.setattr(scraper, "warning", lambda msg: warnings.append(msg))
    return scraper, warnings


def test_scrape_warns_on_unmatched_bill_no(monkeypatch):
    def walk(bill_list):
        bill_list.input["matched_bill_nos"].add("HB53")
        return iter(())

    scraper, warnings = _make_scraper_for_scrape(monkeypatch, walk)

    list(scraper.scrape(session="2026", bill_no="HB53,HB404"))

    assert any("HB404" in msg for msg in warnings)
    assert not any("HB53" in msg for msg in warnings)
    assert any("2026" in msg for msg in warnings)


def test_scrape_does_not_warn_when_every_requested_bill_no_matched(monkeypatch):
    def walk(bill_list):
        bill_list.input["matched_bill_nos"].update({"HB53", "SB99"})
        return iter(())

    scraper, warnings = _make_scraper_for_scrape(monkeypatch, walk)

    list(scraper.scrape(session="2026", bill_no="HB53,SB99"))

    assert warnings == []


def test_scrape_without_bill_no_never_warns(monkeypatch):
    # bill_no is unset on every scheduled production run -- that path must not
    # gain any new warning behaviour.
    def walk(bill_list):
        return iter(())

    scraper, warnings = _make_scraper_for_scrape(monkeypatch, walk)

    list(scraper.scrape(session="2026"))

    assert warnings == []
