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


# ── scrape_action_page (OPEN-37: enacted Chapter-of-the-Acts version link) ──
#
# Real malegislature.gov BillHistory markup (fetched 2026-08-14) for H972 (session 194,
# enacted Chapter 15 of the Acts of 2025 -- one of the exact bills OPEN-37 names):
#
#   <td>Executive</td>
#   <td>Signed by the Governor, <a href='/Laws/SessionLaws/Acts/2025/Chapter15'>
#   Chapter 15 of the Acts of 2025</a></td>
#
# Fixtures use a real Bill object (not a bare Mock) because add_version_link populates
# bill.versions, which a Mock doesn't do realistically.

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
