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
from ma.bills import (  # noqa: E402
    MABillScraper,
    _house_vote_dedupe_key,
    _senate_vote_dedupe_key,
)


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


# ── scrape_action_page (OPEN-37: enacted Chapter-of-the-Acts version link;
# OPEN-69: stage cross-reference related_bill edges) ──
#
# Real malegislature.gov BillHistory markup (fetched 2026-08-13/14) for H972 (session 194,
# enacted Chapter 15 of the Acts of 2025 -- one of the exact bills OPEN-37 names) and S2584
# (session 192, whose history cross-references S2572/H4879/H4891/S3097 as stage documents):
#
#   <td>Executive</td>
#   <td>Signed by the Governor, <a href='/Laws/SessionLaws/Acts/2025/Chapter15'>
#   Chapter 15 of the Acts of 2025</a></td>
#
#   <td>House</td>
#   <td>...the amendment (<a href='/Bills/192/H4879'>H4879</a>) pending</td>
#
# Note the single-quoted href attributes -- lxml parses it the same either way, but fixtures
# below mirror the real markup rather than double-quoting it. Fixtures use a real Bill object
# (not a bare Mock) because add_version_link populates bill.versions and the cross-reference
# logic reads bill.identifier/bill.related_bills, neither of which a Mock populates
# realistically.

def _action_page(row_html):
    return lxml.html.fromstring("<table><tbody>{}</tbody></table>".format(row_html))


def _bill(identifier="H972", legislative_session="194th"):
    return Bill(
        identifier,
        legislative_session=legislative_session,
        title="test bill",
        classification="bill",
    )


def test_scrape_action_page_captures_chapter_law_version_link():
    scraper = make_scraper()
    bill = _bill("H972", "194th")
    page = _action_page(
        "<tr><td>8/5/2025</td><td>Executive</td>"
        "<td>Signed by the Governor, "
        "<a href='/Laws/SessionLaws/Acts/2025/Chapter15'>"
        "Chapter 15 of the Acts of 2025</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    versions = [v for v in bill.versions if v["note"] == "Chapter Law Text (Enacted)"]
    assert len(versions) == 1
    assert versions[0]["links"] == [
        {
            "url": "https://malegislature.gov/Laws/SessionLaws/Acts/2025/Chapter15",
            "media_type": "text/html",
        }
    ]


def test_scrape_action_page_h4100_chapter3_example():
    scraper = make_scraper()
    bill = _bill("H4100", "194th")
    page = _action_page(
        "<tr><td>5/15/2025</td><td>Executive</td>"
        "<td>Signed by the Governor, "
        "<a href='/Laws/SessionLaws/Acts/2025/Chapter3'>"
        "Chapter 3 of the Acts of 2025</a></td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    versions = [v for v in bill.versions if v["note"] == "Chapter Law Text (Enacted)"]
    assert len(versions) == 1
    assert versions[0]["links"][0]["url"] == (
        "https://malegislature.gov/Laws/SessionLaws/Acts/2025/Chapter3"
    )


def test_scrape_action_page_skips_version_link_for_governor_row_without_chapter_link():
    scraper = make_scraper()
    bill = _bill()
    page = _action_page(
        "<tr><td>7/29/2024</td><td>Executive</td>"
        "<td>Signed by the Governor</td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert [v for v in bill.versions if v["note"] == "Chapter Law Text (Enacted)"] == []


def test_scrape_action_page_skips_version_link_for_ordinary_action_row():
    scraper = make_scraper()
    bill = _bill()
    page = _action_page(
        "<tr><td>6/15/2022</td><td>House</td>"
        "<td>Referred to the committee on Ways and Means</td></tr>"
    )

    list(scraper.scrape_action_page(bill, page))

    assert bill.versions == []


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


# ── _house_vote_dedupe_key / _senate_vote_dedupe_key (OPEN-252) ──────────────


def test_house_vote_dedupe_key_differs_for_two_bills_sharing_one_supplement():
    """The exact live collision: Supplement #29 on 2025-04-09 covers both H4005 and
    H4010's "Passed to be engrossed" actions in the 194th session -- one shared roll
    call PDF, two different bills. Before this fix both bills computed the identical
    dedupe_key ("<pdf>#29"), so the importer's get_object() resolved H4010's vote to
    H4005's already-imported row and raised DuplicateItemError (confirmed live during
    OPEN-193's canary, run ma-f08d7646b9fe)."""
    pdf = "https://malegislature.gov/Journal/House/194/2025/RollCalls"

    key_h4005 = _house_vote_dedupe_key(pdf, 29, "H4005")
    key_h4010 = _house_vote_dedupe_key(pdf, 29, "H4010")

    assert key_h4005 != key_h4010


def test_house_vote_dedupe_key_matches_for_the_same_bill_and_supplement():
    # Re-scraping the same vote for the same bill must still be idempotent --
    # this is what makes get_object() find and update the existing row rather
    # than creating a duplicate across separate runs.
    pdf = "https://malegislature.gov/Journal/House/194/2025/RollCalls"

    assert _house_vote_dedupe_key(pdf, 29, "H4005") == _house_vote_dedupe_key(
        pdf, 29, "H4005"
    )


def test_senate_vote_dedupe_key_differs_for_two_bills_sharing_one_rollcall_pdf():
    # Same class of bug as the House branch, for the common case where a real
    # rollcall_pdf was found.
    pdf = "https://malegislature.gov/Bills/194/SenateRollCall70.pdf"

    key_s1 = _senate_vote_dedupe_key(
        pdf, "fallback", "2025-04-09", "Roll Call #70", "S1"
    )
    key_s2 = _senate_vote_dedupe_key(
        pdf, "fallback", "2025-04-09", "Roll Call #70", "S2"
    )

    assert key_s1 != key_s2


def test_senate_vote_dedupe_key_fallback_branch_format_is_unchanged_by_this_fix():
    """pm-review, round 1: the no-PDF fallback branch's `fallback_source` is already the
    bill's own page URL (`bill.sources[0]["url"]`), so it was never vulnerable to the
    companion-bill collision the PDF branch has -- deliberately NOT changing its key format,
    to avoid orphaning any already-imported row under the old format for a branch that
    (per bills.py's own comment) currently never executes at all. `bill_identifier` is
    accepted but ignored in this branch; two different bills' *own* fallback_source values
    already differ, which is what actually disambiguates them, not bill_identifier."""
    key_s1 = _senate_vote_dedupe_key(
        None,
        "https://malegislature.gov/Bills/194/S1",
        "2025-04-09",
        "Roll Call #70",
        "S1",
    )
    key_s2 = _senate_vote_dedupe_key(
        None,
        "https://malegislature.gov/Bills/194/S2",
        "2025-04-09",
        "Roll Call #70",
        "S2",
    )

    assert key_s1 != key_s2
    # Exact pre-fix format, with no bill identifier folded in.
    assert (
        key_s1
        == "https://malegislature.gov/Bills/194/S1#senate-2025-04-09-roll-call-70"
    )


# ── same bill, different roll call: must still stay distinct (pm-review, round 1) ──────────


def test_house_vote_dedupe_key_differs_for_the_same_bill_on_different_supplements():
    # The fix must not introduce a NEW same-bill collision -- two real, different House
    # votes on the same bill (different supplement numbers) must keep distinct keys.
    pdf = "https://malegislature.gov/Journal/House/194/2025/RollCalls"

    assert _house_vote_dedupe_key(pdf, 29, "H4005") != _house_vote_dedupe_key(
        pdf, 30, "H4005"
    )


def test_senate_vote_dedupe_key_differs_for_the_same_bill_on_different_rollcall_pdfs():
    key_1 = _senate_vote_dedupe_key(
        "https://malegislature.gov/Bills/194/SenateRollCall70.pdf",
        "fallback",
        "2025-04-09",
        "Roll Call #70",
        "S1",
    )
    key_2 = _senate_vote_dedupe_key(
        "https://malegislature.gov/Bills/194/SenateRollCall71.pdf",
        "fallback",
        "2025-04-09",
        "Roll Call #71",
        "S1",
    )

    assert key_1 != key_2
