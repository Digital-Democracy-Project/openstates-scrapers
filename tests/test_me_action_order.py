"""OPEN-839: Maine bill actions are stored oldest first, with plain dates.

A Maine bill's actions come from three pages: the floor history (LawMakerWeb dockets.asp), the
governor's action (the bill summary) and the committee docket (the CDtab table on the bill-text page,
display_ps.asp). The committee docket used to be added last, with localized datetimes, so 2,232 of the
2,450 bills of Maine's first scrape (Mac replica) had a backward date step.

The fixtures (tests/fixtures/me_open839/) are real 132nd pages, saved 2026-11-23: the summary and docket
pages of LD 144 (SP 80) and LD 819, and the bill-text page of LD 819 (LD 144's is
tests/fixtures/me_open811/display_ps_132_SP0080.html). LD 819 has a day (6/17/2025) with both floor and
committee actions: the committee's "Reported Out" precedes the floor's reading of that report. No test
makes a live call.
"""
import datetime
import os
import sys
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from me.bills import MEBillScraper, gettext  # noqa: E402

TESTS = os.path.dirname(__file__)
FIX = os.path.join(TESTS, "fixtures", "me_open839")
LMW = "https://legislature.maine.gov/LawMakerWeb/"
BILLS = {
    "LD 144": (
        "summary_132_LD144.html",
        "dockets_132_LD144_280095734.html",
        os.path.join(TESTS, "fixtures", "me_open811", "display_ps_132_SP0080.html"),
        "280095734",
    ),
    "LD 819": (
        "summary_132_LD819.html",
        "dockets_132_LD819_280097019.html",
        os.path.join(FIX, "display_ps_132_LD819.html"),
        "280097019",
    ),
}
EMPTY = "<html><body></body></html>"


def read(path):
    with open(os.path.join(FIX, path), encoding="latin-1") as f:
        return f.read()


def scrape(bill_id):
    summary, docket, display_ps, pid = BILLS[bill_id]
    scraper = MEBillScraper(jurisdiction="x", datadir="/tmp")
    scraper.dockets = {f"{LMW}dockets.asp?ID={pid}": read(docket)}
    bill = Bill(bill_id, "132R1", "", chamber="upper")
    bill.add_source(f"{LMW}summary.asp?ID={pid}")

    def get(url, **kwargs):
        if "summary.asp" in url:
            return mock.Mock(text=read(summary))
        if "display_ps.asp" in url:
            return mock.Mock(text=read(display_ps))
        assert "sponsors.asp" in url or "subjects.asp" in url, url
        return mock.Mock(text=EMPTY)

    with mock.patch.object(scraper, "get", side_effect=get), mock.patch.object(
        scraper, "scrape_votes", return_value=iter(())
    ):
        list(scraper.scrape_bill(bill, "upper"))
    return bill


def floor_rows(bill_id):
    """The docket page's own action lines, top to bottom, as (date, action)."""
    page = lxml.html.fromstring(read(BILLS[bill_id][1]))
    rows = []
    for row in page.xpath("//b[. = 'Date']/../../../following-sibling::tr"):
        date = datetime.datetime.strptime(row.xpath("string(td[1])"), "%m/%d/%Y")
        for line in gettext(row[2]).splitlines():
            line = " ".join(line.split())
            if line and "Unfinished Business" not in line:
                rows.append((date.date().isoformat(), line))
    return rows


def committee_rows(bill_id):
    """The committee docket's own rows, top to bottom, as (date, action)."""
    with open(BILLS[bill_id][2], encoding="latin-1") as f:
        page = lxml.html.fromstring(f.read())
    rows = []
    for row in page.xpath('//table[@name="CDtab"]/tr')[2:]:
        date = datetime.datetime.strptime(
            row.xpath("string(td[1])").strip(), "%b %d, %Y"
        )
        action = row.xpath("string(td[2])").strip()
        result = row.xpath("string(td[3])").strip()
        rows.append(
            (date.date().isoformat(), f"{action} - {result}" if result else action)
        )
    return rows


def stored(bill):
    return [(str(a["date"]), a["description"]) for a in bill.actions]


@pytest.mark.parametrize("bill_id", BILLS)
def test_dates_never_go_down_and_are_plain_dates(bill_id):
    actions = stored(scrape(bill_id))
    dates = [d for d, _ in actions]
    assert all(len(d) == 10 for d in dates), dates
    assert dates == sorted(dates)


@pytest.mark.parametrize("bill_id", BILLS)
def test_no_action_is_added_or_lost_and_each_page_keeps_its_order(bill_id):
    actions = stored(scrape(bill_id))
    floor, committee = floor_rows(bill_id), committee_rows(bill_id)
    assert floor and committee
    # the summary adds one governor action (both bills were signed)
    assert len(actions) == len(floor) + len(committee) + 1
    assert [a for a in actions if a in floor] == floor
    assert [a for a in actions if a in committee] == committee
    assert "Signed by Governor" in [t for _, t in actions]


def test_a_days_committee_report_comes_before_the_floor_reading():
    actions = stored(scrape("LD 819"))
    day = [t for d, t in actions if d == "2025-06-17"]
    committee = [t for d, t in committee_rows("LD 819") if d == "2025-06-17"]
    floor = [t for d, t in floor_rows("LD 819") if d == "2025-06-17"]
    assert committee and floor
    assert day == committee + floor
