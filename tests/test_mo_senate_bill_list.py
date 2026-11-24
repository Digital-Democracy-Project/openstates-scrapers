"""OPEN-848: every bill on the Missouri Senate bill list is collected, or the run stops.

A 2026 run stored 1,032 of the list's 1,060 bills that have a bill page: 28 bills in three runs
of consecutive list positions (SB 1010-1018, SB 1039-1048, SB 1470-1477 and SB 1479) were
dropped because a failed fetch of a bill page was logged and skipped. Now a failed fetch is tried
again after waits that outlast an outage, and a bill that still cannot be read stops the run.

Every file under tests/fixtures/mo_open848/ is a real senate.mo.gov page saved on 2026-11-23:
the 2026 Regular Session bill list (gzipped) and the bill, Actions, BillText and Amendments
pages of SB 1010 (billid=166) and SB 1470 (billid=51370). No test makes a live call.
"""
import gzip
import os
import re
import sys
from unittest import mock

import pytest
from requests.exceptions import ConnectionError, SSLError
from scrapelib import HTTPError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import mo.bills  # noqa: E402
from mo.bills import MOBillScraper, SenateBillNotCollected  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mo_open848")
BILL_URL = (
    "https://www.senate.mo.gov/BillTracking/Bills/BillInformation?year=2026&billid="
)
BILLIDS = {"166": "SB1010", "51370": "SB1470"}

THE_28 = (
    [f"SB {n}" for n in range(1010, 1019)]
    + [f"SB {n}" for n in range(1039, 1049)]
    + [f"SB {n}" for n in range(1470, 1478)]
    + ["SB 1479"]
)


def list_page():
    with gzip.open(os.path.join(FIXTURES, "billlist_2026_R.html.gz"), "rb") as f:
        return f.read()


def page_for(url):
    """The saved page for a Senate URL, as the scraper's get() returns it."""
    if "BillList" in url:
        data = list_page()
    else:
        m = re.search(r"billid=(\d+)(?:&handler=(\w+))?", url)
        name = BILLIDS[m.group(1)] + (f"_{m.group(2)}" if m.group(2) else "")
        with open(os.path.join(FIXTURES, f"{name}.html"), "rb") as f:
            data = f.read()
    return mock.Mock(content=data, text=data.decode("utf-8"))


def http_error(status):
    return HTTPError(mock.Mock(status_code=status, url="u"))


def scraper():
    s = MOBillScraper(jurisdiction="x", datadir="/tmp")
    s._session_id = "2026"
    return s


def walk(s):
    """The bill-list walk; every bill page it asks for is recorded, not fetched."""
    asked = []

    def record(url, identifier, sponsor_link, year):
        asked.append(identifier)
        return iter(())

    with mock.patch.object(s, "get", side_effect=page_for), mock.patch.object(
        s, "_parse_senate_billpage", side_effect=record
    ):
        list(s._scrape_upper_chamber("2026"))
    return asked


def test_the_list_walk_asks_for_every_bill_page_including_the_28():
    asked = walk(scraper())
    assert len(asked) == len(set(asked)) == 1060
    assert set(THE_28) <= set(asked)


def test_the_whole_list_replayed_yields_one_bill_for_every_linked_card():
    """Every bill page answers (SB 1010's saved pages stand in for each; the identifier comes
    from the list), so the walk yields all 1,060 bills, the 28 included."""

    def any_bill(url, **kwargs):
        return page_for(re.sub(r"billid=\d+", "billid=166", url))

    s = scraper()
    with mock.patch.object(s, "get", side_effect=any_bill):
        got = [b.identifier for b in s._scrape_upper_chamber("2026")]
    assert len(got) == len(set(got)) == 1060
    assert set(THE_28) <= set(got)


def test_withdrawn_cards_have_no_bill_page_and_are_the_only_ones_skipped():
    asked = walk(scraper())
    assert {"SB 1348", "SB 1390", "SB 1478"}.isdisjoint(asked)


def test_a_card_without_a_link_that_is_not_withdrawn_stops_the_run():
    """SB 1010's card as the list prints a withdrawn bill's (number, no link), minus WITHDRAWN."""
    linked = (
        b'<a href="https://www.senate.mo.gov/BillTracking/Bills/BillInformation?year=2026'
        b'&amp;billid=166" target="_blank" class="fs-6">SB 1010</a>'
    )
    page = list_page()
    assert page.count(linked) == 1
    page = page.replace(linked, b'<span class="fs-6">SB 1010</span>')
    s = scraper()
    with mock.patch.object(
        s, "get", return_value=mock.Mock(content=page, text=page.decode())
    ), mock.patch.object(s, "_parse_senate_billpage", return_value=iter(())):
        with pytest.raises(SenateBillNotCollected, match="SB 1010"):
            list(s._scrape_upper_chamber("2026"))


@pytest.mark.parametrize(
    "billid,identifier,actions,last",
    [
        ("166", "SB 1010", 3, "Second Read and Referred"),
        ("51370", "SB 1470", 35, "Signed by Governor"),
    ],
)
def test_the_saved_bill_pages_make_a_bill(billid, identifier, actions, last):
    s = scraper()
    with mock.patch.object(s, "get", side_effect=page_for):
        bills = list(
            s._parse_senate_billpage(BILL_URL + billid, identifier, "", "2026")
        )
    assert [b.identifier for b in bills] == [identifier]
    assert len(bills[0].actions) == actions
    assert bills[0].actions[-1]["description"].startswith(last)
    assert len(bills[0].versions) >= 1


def test_sb1470_ends_on_the_governors_signature():
    s = scraper()
    with mock.patch.object(s, "get", side_effect=page_for):
        (bill,) = s._parse_senate_billpage(BILL_URL + "51370", "SB 1470", "", "2026")
    assert bill.actions[-1]["date"].date().isoformat() == "2026-07-13"


def flaky(failures, on="billid=166", error=None):
    """get() that fails `failures` times for URLs containing `on`, then serves the page."""
    left = {"n": failures}

    def get(url, **kwargs):
        if on in url and left["n"]:
            left["n"] -= 1
            raise error or http_error(503)
        return page_for(url)

    return get


def test_a_bill_page_that_fails_for_a_while_is_tried_again_and_collected():
    s = scraper()
    with mock.patch.object(s, "get", side_effect=flaky(3)), mock.patch.object(
        mo.bills.time, "sleep"
    ) as sleep:
        bills = list(s._parse_senate_billpage(BILL_URL + "166", "SB 1010", "", "2026"))
    assert [b.identifier for b in bills] == ["SB 1010"]
    assert [c.args[0] for c in sleep.call_args_list] == [60, 180, 600]


def test_a_connection_error_is_tried_again_too():
    s = scraper()
    with mock.patch.object(
        s, "get", side_effect=flaky(1, error=ConnectionError("reset"))
    ), mock.patch.object(mo.bills.time, "sleep"):
        bills = list(s._parse_senate_billpage(BILL_URL + "166", "SB 1010", "", "2026"))
    assert len(bills) == 1


def test_a_bill_page_that_keeps_failing_stops_the_run_naming_the_bill():
    """Before OPEN-848 this bill was logged and skipped, and the run finished without it."""
    s = scraper()
    bill_list = page_for("BillList")

    def get(url, **kwargs):
        if "BillList" in url:
            return bill_list
        raise http_error(503)

    with mock.patch.object(s, "get", side_effect=get), mock.patch.object(
        mo.bills.time, "sleep"
    ) as sleep:
        with pytest.raises(SenateBillNotCollected, match=r"SB 834 .*billid=416"):
            list(s._scrape_upper_chamber("2026"))
    assert sleep.call_count == len(mo.bills.SENATE_OUTAGE_WAITS)


@pytest.mark.parametrize("handler", ["Actions", "BillText", "Amendments"])
def test_a_bill_is_never_stored_without_one_of_its_pages(handler):
    s = scraper()
    with mock.patch.object(
        s, "get", side_effect=flaky(99, on=f"billid=166&handler={handler}")
    ), mock.patch.object(mo.bills.time, "sleep"):
        with pytest.raises(HTTPError):
            list(s._parse_senate_billpage(BILL_URL + "166", "SB 1010", "", "2026"))


def test_a_certificate_failure_is_not_waited_on():
    s = scraper()
    with mock.patch.object(
        s, "get", side_effect=flaky(1, error=SSLError("bad cert"))
    ), mock.patch.object(mo.bills.time, "sleep") as sleep:
        with pytest.raises(SSLError):
            list(s._parse_senate_billpage(BILL_URL + "166", "SB 1010", "", "2026"))
    assert sleep.call_count == 0
