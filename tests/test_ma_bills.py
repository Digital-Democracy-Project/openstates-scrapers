"""Tests for OPEN-42: scrape_senate_vote's self.urlretrieve() and get_as_ajax's
s.get() had no try/except guard, unlike scrape_bill (~200 lines above them in the
same file), which already catches requests.exceptions.RequestException and skips
the bill. A single transient ReadTimeout/ConnectionError at either call site
propagated all the way up through do_scrape() and killed the entire multi-hour MA
scrape (PLAN-coverage-completeness-check.md §13). This also covers get_house_pdf,
which had the identical unguarded urlretrieve() pattern.

These tests only prove the guard swallows the exception and signals failure to the
caller (None/False) instead of raising -- not full end-to-end bill scraping.
"""
import os
import sys
from unittest import mock

import lxml.html
import requests
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402


def make_scraper() -> MABillScraper:
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    # class-level cache dict is shared across instances -- keep tests isolated
    scraper.house_pdf_cache = {}
    return scraper


# ── get_as_ajax ──────────────────────────────────────────────────────────────

def test_get_as_ajax_returns_none_on_request_exception(monkeypatch):
    scraper = make_scraper()
    fake_session = mock.Mock()
    fake_session.get.side_effect = requests.exceptions.ConnectionError("boom")
    monkeypatch.setattr(
        "ma.bills.requests.Session", mock.Mock(return_value=fake_session)
    )

    result = scraper.get_as_ajax("https://malegislature.gov/Bills/194/S1/CoSponsor")

    assert result is None


def test_get_as_ajax_returns_response_on_success(monkeypatch):
    scraper = make_scraper()
    fake_response = mock.Mock()
    fake_session = mock.Mock()
    fake_session.get.return_value = fake_response
    monkeypatch.setattr(
        "ma.bills.requests.Session", mock.Mock(return_value=fake_session)
    )

    result = scraper.get_as_ajax("https://malegislature.gov/Bills/194/S1/CoSponsor")

    assert result is fake_response


# ── scrape_cosponsors (get_as_ajax caller) ──────────────────────────────────

def test_scrape_cosponsors_skips_without_raising_when_fetch_fails(monkeypatch):
    scraper = make_scraper()
    monkeypatch.setattr(scraper, "get_as_ajax", mock.Mock(return_value=None))
    bill = mock.Mock(sponsorships=[])

    scraper.scrape_cosponsors(bill, "https://malegislature.gov/Bills/194/S1")

    bill.add_sponsorship.assert_not_called()


# ── get_action_page / scrape_actions (get_as_ajax callers) ─────────────────

def test_get_action_page_returns_none_when_fetch_fails(monkeypatch):
    scraper = make_scraper()
    monkeypatch.setattr(scraper, "get_as_ajax", mock.Mock(return_value=None))

    result = scraper.get_action_page("https://malegislature.gov/Bills/194/S1", 1)

    assert result is None


def test_scrape_actions_skips_without_raising_when_first_page_fetch_fails(
    monkeypatch,
):
    scraper = make_scraper()
    monkeypatch.setattr(scraper, "get_action_page", mock.Mock(return_value=None))

    actions = list(
        scraper.scrape_actions(
            mock.Mock(), "https://malegislature.gov/Bills/194/S1", "194th"
        )
    )

    assert actions == []


def test_scrape_actions_continues_past_a_failed_later_page(monkeypatch):
    scraper = make_scraper()
    page_one = mock.Mock()
    page_one.xpath.return_value = ["2"]  # pretend there's a page 2 in the paginator

    def fake_get_action_page(bill_url, page_number):
        return page_one if page_number == 1 else None

    monkeypatch.setattr(scraper, "get_action_page", mock.Mock(side_effect=fake_get_action_page))
    monkeypatch.setattr(scraper, "scrape_action_page", mock.Mock(return_value=iter(["action-1"])))

    actions = list(
        scraper.scrape_actions(
            mock.Mock(), "https://malegislature.gov/Bills/194/S1", "194th"
        )
    )

    # page 1 yields, page 2's fetch failure is skipped rather than raising
    assert actions == ["action-1"]


# ── scrape_senate_vote ───────────────────────────────────────────────────────

def test_scrape_senate_vote_returns_false_on_request_exception(monkeypatch):
    scraper = make_scraper()
    monkeypatch.setattr(
        scraper,
        "urlretrieve",
        mock.Mock(side_effect=requests.exceptions.ReadTimeout("boom")),
    )

    result = scraper.scrape_senate_vote(
        mock.Mock(), "http://malegislature.gov/Journal/Senate/194/RollCalls/1.pdf"
    )

    assert result is False


# ── get_house_pdf / scrape_house_vote ───────────────────────────────────────

def test_get_house_pdf_returns_none_on_request_exception(monkeypatch):
    scraper = make_scraper()
    monkeypatch.setattr(
        scraper,
        "urlretrieve",
        mock.Mock(side_effect=requests.exceptions.ConnectionError("boom")),
    )

    result = scraper.get_house_pdf(
        "https://malegislature.gov/Journal/House/194/2026/RollCalls"
    )

    assert result is None
    assert scraper.house_pdf_cache == {}


def test_scrape_house_vote_returns_false_when_pdf_fetch_fails(monkeypatch):
    scraper = make_scraper()
    monkeypatch.setattr(scraper, "get_house_pdf", mock.Mock(return_value=None))

    result = scraper.scrape_house_vote(
        mock.Mock(),
        "https://malegislature.gov/Journal/House/194/2026/RollCalls",
        1,
    )

    assert result is False


# ── scrape_action_page (OPEN-69: Chapter-of-the-Acts + stage cross-refs) ────
#
# Real malegislature.gov BillHistory markup (fetched directly during planning,
# 2026-08-13/14) for H4889 (session 193, enacted Chapter 139 of 2024), H5620
# (session 194, enacted Chapter 163 of 2026), and S2584 (session 192, whose
# history cross-references S2572/H4879/H4891/S3097 as stage documents):
#
#   <td>Executive</td>
#   <td>Signed by the Governor, <a href='/Laws/SessionLaws/Acts/2024/Chapter139'>
#   Chapter 139 of the Acts of 2024</a></td>
#
#   <td>House</td>
#   <td>...the amendment (<a href='/Bills/192/H4879'>H4879</a>) pending</td>
#
# Note the single-quoted href attributes -- lxml parses it the same either
# way, but fixtures below mirror the real markup rather than double-quoting
# it. Fixtures use a real Bill object (not a bare Mock) because the Tier 2
# cross-reference logic reads bill.identifier/bill.related_bills, which a
# Mock doesn't populate realistically.

def _action_page(row_html):
    return lxml.html.fromstring("<table><tbody>{}</tbody></table>".format(row_html))


def _bill(identifier="S2584", legislative_session="192nd"):
    return Bill(
        identifier,
        legislative_session=legislative_session,
        title="test bill",
        classification="bill",
    )


def test_scrape_action_page_captures_chapter_of_the_acts_citation():
    scraper = make_scraper()
    bill = _bill("H4889", "193rd")
    page = _action_page(
        "<tr><td>7/29/2024</td><td>Executive</td>"
        "<td>Signed by the Governor, "
        "<a href='/Laws/SessionLaws/Acts/2024/Chapter139'>"
        "Chapter 139 of the Acts of 2024</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.citations == [
        {
            "publication": "Acts of Massachusetts",
            "citation": "Chapter 139 of the Acts of 2024",
            "citation_type": "chapter",
            "effective": "2024-07-29",
            "expires": None,
            "url": "https://malegislature.gov/Laws/SessionLaws/Acts/2024/Chapter139",
        }
    ]


def test_scrape_action_page_captures_chapter_of_the_acts_citation_h5620_example():
    scraper = make_scraper()
    bill = _bill("H5620", "194th")
    page = _action_page(
        "<tr><td>1/5/2026</td><td>Executive</td>"
        "<td>Signed by the Governor, "
        "<a href='/Laws/SessionLaws/Acts/2026/Chapter163'>"
        "Chapter 163 of the Acts of 2026</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.citations == [
        {
            "publication": "Acts of Massachusetts",
            "citation": "Chapter 163 of the Acts of 2026",
            "citation_type": "chapter",
            "effective": "2026-01-05",
            "expires": None,
            "url": "https://malegislature.gov/Laws/SessionLaws/Acts/2026/Chapter163",
        }
    ]


def test_scrape_action_page_skips_citation_for_governor_row_without_chapter_link():
    scraper = make_scraper()
    bill = _bill()
    page = _action_page(
        "<tr><td>7/29/2024</td><td>Executive</td>"
        "<td>Signed by the Governor</td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.citations == []


def test_scrape_action_page_skips_citation_for_ordinary_action_row():
    scraper = make_scraper()
    bill = _bill()
    page = _action_page(
        "<tr><td>6/15/2022</td><td>House</td>"
        "<td>Referred to the committee on Ways and Means</td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.citations == []


def test_scrape_action_page_skips_citation_for_non_chapter_bill_cross_reference():
    # A stage cross-reference link (/Bills/{session}/{id}) must not be
    # mistaken for a /Laws/SessionLaws/Acts/ enacted-chapter link.
    scraper = make_scraper()
    bill = _bill()
    page = _action_page(
        "<tr><td>6/16/2022</td><td>House</td>"
        "<td>For text of amendment, see "
        "<a href='/Bills/192/H4891'>H4891</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.citations == []


# ── scrape_action_page (OPEN-69: stage cross-reference related_bill edges) ──

def test_scrape_action_page_adds_related_bill_for_stage_cross_reference():
    scraper = make_scraper()
    bill = _bill("S2584", "192nd")
    page = _action_page(
        "<tr><td>6/16/2022</td><td>House</td>"
        "<td>For text of amendment, see "
        "<a href='/Bills/192/H4891'>H4891</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.related_bills == [
        {
            "identifier": "H 4891",
            "legislative_session": "192nd",
            "relation_type": "related",
        }
    ]


def test_scrape_action_page_dedupes_repeated_stage_cross_reference():
    # The same referenced bill-id can appear across multiple action rows
    # (e.g. a pending amendment mentioned more than once) -- must only add
    # one related_bill edge.
    scraper = make_scraper()
    bill = _bill("S2584", "192nd")
    page = _action_page(
        "<tr><td>6/15/2022</td><td>House</td>"
        "<td>Amendment (<a href='/Bills/192/H4879'>H4879</a>) pending</td></tr>"
        "<tr><td>6/16/2022</td><td>House</td>"
        "<td>Reconsideration of <a href='/Bills/192/H4879'>H4879</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.related_bills == [
        {
            "identifier": "H 4879",
            "legislative_session": "192nd",
            "relation_type": "related",
        }
    ]


def test_scrape_action_page_skips_self_reference_for_stage_cross_reference():
    scraper = make_scraper()
    bill = _bill("H4879", "192nd")
    page = _action_page(
        "<tr><td>6/15/2022</td><td>House</td>"
        "<td>Text of <a href='/Bills/192/H4879'>H4879</a>, printed as amended"
        "</td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.related_bills == []


def test_scrape_action_page_ignores_rollcall_and_committee_links():
    # RollCall PDF hrefs and Committee-detail hrefs are already handled
    # elsewhere in the file (Senate vote scraping, categorizer committees)
    # and must not be misidentified as bill cross-references.
    scraper = make_scraper()
    bill = _bill("S3097", "192nd")
    page = _action_page(
        "<tr><td>8/1/2022</td><td>Senate</td>"
        "<td>Committee of conference report accepted -see "
        "<a href='/RollCall/192/SenateRollCall260.pdf'>Roll Call #260</a>"
        " (Yeas 39 to Nays 0)</td></tr>"
        "<tr><td>8/1/2022</td><td>House</td>"
        "<td>Referred to the committee on "
        "<a href='/Committees/Detail/H52'>House Steering</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.related_bills == []


def test_scrape_action_page_adds_related_bill_for_conference_report_backreference():
    # Real S3097 markup: a conference-report bill's own history links back
    # to the bill it reconciles ("Reported on S2584").
    scraper = make_scraper()
    bill = _bill("S3097", "192nd")
    page = _action_page(
        "<tr><td>8/1/2022</td><td>Senate</td>"
        "<td>Reported on <a href='/Bills/192/S2584'>S2584</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.related_bills == [
        {
            "identifier": "S 2584",
            "legislative_session": "192nd",
            "relation_type": "related",
        }
    ]
