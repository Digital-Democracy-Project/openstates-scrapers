"""OPEN-695: Missouri bill actions are stored oldest first.

The Senate's Actions page lists a bill's actions newest first, a day's actions included; the
House's bill XML lists them oldest first (ActivitySequence). Every file under
tests/fixtures/mo_2026/ is a real 2026 Regular Session source page saved on 2026-11-20:
the Senate Actions pages of SB 835 and SB 841 and the House bill XML of HB 2885.
No test makes a live call.
"""
import os
import sys
from unittest import mock

import lxml.etree
import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from mo.bills import MOBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mo_2026")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def site_rows(identifier):
    """The Senate page's own rows, top to bottom, as (date, action)."""
    page = lxml.html.fromstring(fixture(f"{identifier.replace(' ', '')}_actions.html"))
    return [
        tuple(td.text_content().strip() for td in row.cssselect("td")[:2])
        for row in page.cssselect("table tbody tr")
    ]


def scrape_senate(identifier):
    scraper = MOBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill(identifier, "2026", "A bill", chamber="upper")
    page = mock.Mock(content=fixture(f"{identifier.replace(' ', '')}_actions.html"))
    with mock.patch.object(scraper, "get", return_value=page):
        scraper._parse_senate_actions(bill, "u")
    return bill


def scrape_house(identifier):
    scraper = MOBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill(identifier, "2026", "A bill", chamber="lower")
    xml = lxml.etree.fromstring(fixture(f"{identifier.replace(' ', '')}.xml"))
    votes = scraper.parse_house_actions(xml, bill)
    return bill, votes, xml


def latest(actions):
    """openstates-core's rule (update_bill_fields): the last action, by order, on the latest date."""
    best = None
    for a in actions:
        if best is None or a["date"] >= best["date"]:
            best = a
    return best["description"]


def day(actions, date):
    return [a["description"] for a in actions if a["date"].date().isoformat() == date]


@pytest.mark.parametrize("identifier", ["SB 835", "SB 841"])
def test_senate_stored_order_is_the_page_reversed_and_dates_never_go_down(identifier):
    actions = scrape_senate(identifier).actions
    rows = site_rows(identifier)
    assert len(actions) == len(rows) > 0
    assert [a["description"] for a in actions] == [t for _, t in reversed(rows)]
    dates = [a["date"] for a in actions]
    assert dates == sorted(dates)
    assert actions[0]["description"] == "Prefiled"


def test_sb835_ends_on_the_governors_signature():
    actions = scrape_senate("SB 835").actions
    assert actions[-1]["description"] == "Signed by Governor"
    assert actions[-1]["date"].date().isoformat() == "2026-07-13"
    assert latest(actions) == "Signed by Governor"


def test_sb835_same_day_actions_run_in_the_order_they_happened():
    """05-28-2026: enrolled, signed by both presiding officers, then delivered to the
    Governor; the page lists the delivery at the top of the day."""
    actions = scrape_senate("SB 835").actions
    assert day(actions, "2026-05-28") == [
        "Reported Duly Enrolled Rules, Joint Rules, Resolutions & Ethics Committee",
        "Signed by Senate President Pro Tem",
        "Signed by House Speaker",
        "Delivered to Governor",
    ]


def test_sb841_same_day_floor_amendments_run_in_journal_order():
    """04-28-2026: the substitute is offered, then amendments to it, journal page S1170 to
    S1184; the page lists them the other way round."""
    actions = scrape_senate("SB 841").actions
    on_the_day = day(actions, "2026-04-28")
    assert len(on_the_day) == 14
    assert on_the_day[0] == "SS for SCS S offered (Bernskoetter)--(4822S.07F)"
    assert on_the_day[1] == "SA 1 to SS for SCS S offered (Lewis)--(4822S07.21S)"
    assert on_the_day[-1] == "Bill Placed on Informal Calendar"
    assert latest(actions) == "Informal Calendar S Bills for Perfection"


def test_house_xml_order_is_kept():
    """The House XML is already oldest first (ActivitySequence 100, 200, ...): it must not be
    reversed too."""
    bill, votes, xml = scrape_house("HB 2885")
    sequence = [
        int(a.findtext("ActivitySequence"))
        for a in xml.xpath("//BillInformation/Action")
    ]
    assert sequence == sorted(sequence)
    actions = bill.actions
    assert len(actions) == len(sequence) == 42
    assert actions[0]["description"] == "Introduced and Read First Time (H)"
    assert actions[-1]["description"] == "Delivered to Secretary of State (G)"
    assert latest(actions) == "Delivered to Secretary of State (G)"
    dates = [a["date"] for a in actions]
    assert dates == sorted(dates)
    assert [d[:30] for d in day(actions, "2026-04-09")] == [
        "Executive Session Completed (H",
        "Voted Do Pass (H)",
        "Reported Do Pass (H) - AYES: 7",
        "Taken Up for Third Reading (H)",
        "Third Read and Passed (H) - AY",
    ]
    assert len(votes) == len(xml.xpath("//BillInformation/Action/RollCall")) == 5
