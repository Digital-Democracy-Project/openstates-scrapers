"""OPEN-542: US Congress bill actions are stored oldest first.

The fixtures are real GovInfo BILLSTATUS files of the 119th Congress (HR 1, S 5, HR 4, HR 1968,
fetched from https://www.govinfo.gov/bulkdata/BILLSTATUS/119/ on 2026-11-16), cut down to the
bill's number, type, congress, origin chamber and its full <actions> list, unchanged. The feed lists
actions newest first.

stored_before_open542.json is what the scraper stored for those files before this fix (the
reader as it was on main, run over the same fixtures): the independent reference. After the fix
the stored list must be exactly that list reversed: the same count, and the same copy of every
duplicated action (same date, chamber and classification). No test makes a live call.
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from usa.bills import USBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "usa_open542")
BILLS = ["119hr1", "119s5", "119hr4", "119hr1968"]

with open(os.path.join(FIXTURES, "stored_before_open542.json")) as f:
    STORED_BEFORE = json.load(f)


def feed(name):
    return ET.parse(os.path.join(FIXTURES, f"BILLSTATUS-{name}-actions.xml")).getroot()


def scrape(name):
    scraper = USBillScraper(jurisdiction="usa", datadir="/tmp")
    bill = Bill(name, "119", "A bill", chamber="lower")
    scraper.scrape_actions(bill, feed(name))
    return bill.actions


def as_rows(actions):
    return [
        [a["description"], str(a["date"]), a["organization_id"], a["classification"]]
        for a in actions
    ]


def latest(actions):
    """openstates-core's rule (update_bill_fields): the last action, by order, on the latest date
    (dates compared as the stored ISO strings)."""
    best = None
    for a in actions:
        if best is None or str(a["date"]) >= str(best["date"]):
            best = a
    return best["description"]


@pytest.mark.parametrize("name", BILLS)
def test_stored_list_is_the_old_stored_list_reversed(name):
    """Same count, same surviving copy of each duplicate, order reversed (not re-sorted)."""
    stored = as_rows(scrape(name))
    assert len(stored) == len(STORED_BEFORE[name])
    assert stored == STORED_BEFORE[name][::-1]


@pytest.mark.parametrize(
    "name,law",
    [
        ("119hr1", "Became Public Law No: 119-21."),
        ("119s5", "Became Public Law No: 119-1."),
        ("119hr4", "Became Public Law No: 119-28."),
        ("119hr1968", "Became Public Law No: 119-4."),
    ],
)
def test_latest_action_is_the_public_law_not_the_signature(name, law):
    """Stored newest first, the latest action was "Signed by President." (the first step of the
    signing day); the feed's own latest step is the public law."""
    actions = scrape(name)
    assert latest(actions) == law
    assert actions[-1]["description"] == law
    assert actions[-2]["description"] == "Signed by President."
    # the feed's first item is the newest step
    assert feed(name).findtext("bill/actions/item/text") == law


def test_hr1_count_and_first_action():
    actions = scrape("119hr1")
    assert len(actions) == 53
    assert actions[0]["description"] == (
        "The House Committee on the Budget reported an original measure, H. Rept. 119-106, by Mr. Arrington."
    )


def test_duplicate_keeps_the_feeds_first_copy():
    """ "Presented to President." appears twice in HR 1's feed: first as a House floor action, then as
    a Library of Congress "President" step. Today the House copy is kept; deduping after reversing
    would keep the other one (an executive action)."""
    items = [
        i
        for i in feed("119hr1").findall("bill/actions/item")
        if i.findtext("text") == "Presented to President."
    ]
    assert [i.findtext("sourceSystem/name") for i in items] == [
        "House floor actions",
        "Library of Congress",
    ]
    (kept,) = [
        a for a in scrape("119hr1") if a["description"] == "Presented to President."
    ]
    assert kept["organization_id"] == '~{"classification": "lower"}'


def test_same_day_steps_keep_the_feeds_order_reversed():
    """On 2025-07-03 the House steps carry times and the LOC summary step only a date (midnight); a
    date sort would move "Resolving differences" to the start of the day. A plain reversal keeps it
    between the vote and the previous question, as the feed has it."""
    day = [
        a["description"][:40]
        for a in scrape("119hr1")
        if str(a["date"]).startswith("2025-07-03")
    ]
    assert day == [
        "Pursuant to the provisions of H. Res. 56",
        "Mr. Arrington moved that the House agree",
        "Mr. Arrington moved that the House agree",
        "DEBATE - Pursuant to the provisions of H",
        "The previous question was ordered pursua",
        "Resolving differences -- House actions: ",
        "On motion that the House agree to the Se",
        "Motion to reconsider laid on the table A",
        "Presented to President.",
    ]
