"""Tests for OPEN-83: AZBillScraper's bill_no= targeting.

AZ's scrape() parses every bill_id straight out of the single, already-fetched
bill-list page (https://www.azleg.gov/bills/'s HBTable/SBTable rows) with no
extra request -- the real cost is scrape_bill(), which fires ~5 per-bill API
calls (BillStatusAction, DocType, BillSponsor, Keyword, BillStatusFloorAction).
bill_no= must filter rows *before* scrape_bill() is called, so untargeted bills
never pay that cost, while everything stays inside the single scrape() call
(no per-bill subprocess).

These tests mock scrape_bill and the two network fetches scrape() makes before
it ever reaches the per-bill loop (the initial cookie-priming GET and the
session-select POST) -- no real HTTP request is made.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from az import Arizona  # noqa: E402
from az.bills import AZBillScraper  # noqa: E402


SESSION = "57th-2nd-regular"
SESSION_ID = 130

BILL_LIST_HTML = """
<html><body>
<select>
<option value="{session_id}" selected="selected">57th Legislature - 2nd Regular</option>
</select>
<div name="HBTable"><tbody>
<tr><th><a href="#">HB2001</a></th></tr>
<tr><th><a href="#">HB2002</a></th></tr>
</tbody></div>
<div name="SBTable"><tbody>
<tr><th><a href="#">SB1075</a></th></tr>
<tr><th><a href="#">SB1076</a></th></tr>
</tbody></div>
</body></html>
""".format(session_id=SESSION_ID).encode("utf-8")


def make_scraper() -> AZBillScraper:
    scraper = AZBillScraper(Arizona(), "/tmp/")

    fake_response = mock.Mock()
    fake_response.content = BILL_LIST_HTML
    fake_response.cookies = {}

    scraper.get = mock.Mock(return_value=fake_response)
    scraper.post = mock.Mock(return_value=fake_response)
    scraper.scrape_bill = mock.Mock(side_effect=lambda *a, **kw: iter([]))

    return scraper


def scraped_bill_ids(scraper) -> list:
    # scrape_bill(chamber, session, bill_id, session_id, start_dt=start_dt)
    return [call.args[2] for call in scraper.scrape_bill.call_args_list]


# ── single-bill form ─────────────────────────────────────────────────────────

def test_scrape_single_bill_no_only_scrapes_matching_bill():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION, bill_no="HB2001"))

    assert scraped_bill_ids(scraper) == ["HB2001"]


# ── multi-bill, comma-separated, across chambers ────────────────────────────

def test_scrape_multi_bill_no_scrapes_both_matching_bills_across_chambers():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION, bill_no="HB2001,SB1075"))

    assert sorted(scraped_bill_ids(scraper)) == ["HB2001", "SB1075"]


# ── normalization: whitespace and case in the requested bill_no ────────────

def test_scrape_bill_no_normalizes_whitespace_and_case():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION, bill_no=" hb 2001 , sb1075"))

    assert sorted(scraped_bill_ids(scraper)) == ["HB2001", "SB1075"]


# ── regression guard: bill_no=None (full scrape) is unaffected ─────────────

def test_scrape_without_bill_no_scrapes_every_row():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION))

    assert sorted(scraped_bill_ids(scraper)) == [
        "HB2001",
        "HB2002",
        "SB1075",
        "SB1076",
    ]


# ── OPEN-123: warn when a requested bill_no matched nothing ─────────────────
#
# Before this, a typo or stale number in a targeted backfill scraped zero bills
# and exited cleanly -- indistinguishable from "that bill had nothing to
# recover". The matched set is accumulated across BOTH chamber tables before
# the diff, since a requested number only ever appears in one of them.


def capture_warnings(scraper) -> list:
    warnings = []
    scraper.warning = lambda msg: warnings.append(msg)
    return warnings


def test_scrape_warns_on_unmatched_bill_no():
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no="HB2001,HB4040"))

    assert any("HB4040" in msg for msg in warnings)
    assert not any("HB2001" in msg for msg in warnings)
    # VA's wording names the session, which is what makes the warning actionable
    # when a number is valid in one session but not the one being scraped.
    assert any(SESSION in msg for msg in warnings)


def test_scrape_does_not_warn_when_every_requested_bill_no_matched():
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no="HB2001,SB1075"))

    assert warnings == []


def test_scrape_does_not_warn_for_a_match_in_the_other_chamber_table():
    # A Senate target is only found while walking SBTable -- diffing per chamber
    # would warn about it during the House pass. Guards that regression.
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no="SB1075"))

    assert warnings == []


def test_scrape_does_not_warn_on_whitespace_or_case_difference():
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no=" hb 2001 "))

    assert warnings == []


def test_scrape_without_bill_no_never_warns():
    # bill_no is unset on every scheduled production run -- that path must not
    # gain any new warning behaviour.
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION))

    assert warnings == []
