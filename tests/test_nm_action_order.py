"""OPEN-620: New Mexico bill actions are stored in the legislature's own order.

The scraper reads actions from the Actions table of the LegInfo Access file. The table's row
order is neither date order nor the bill's history. tests/fixtures/nm_2026/Actions.csv is a real
slice of that table (LegInfo26.zip, 2026 Regular Session, as published on nmlegis.gov): every
row of HB 103, HB 10 and HB 88, in the table's own row order. TblLocations.csv holds the
committees those rows name. The test feeds them to the scraper's own reader in place of
mdb-export. No test makes a live call.
"""
import csv
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from nm.bills import NMBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nm_2026")


def table(name):
    with open(os.path.join(FIXTURES, name + ".csv"), newline="") as f:
        return list(csv.DictReader(f))


def scrape():
    scraper = NMBillScraper(jurisdiction="x", datadir="/tmp")
    bills = {
        key: Bill(key, "2026", "A bill", chamber="lower")
        for key in ("H103", "H10", "H88")
    }
    with mock.patch.object(
        scraper, "access_to_csv", side_effect=lambda name: iter(table(name))
    ):
        scraper.scrape_actions("H", bills)
    return {key: bill.actions for key, bill in bills.items()}


def descriptions(actions):
    return [a["description"] for a in actions]


def latest(actions):
    """openstates-core's rule (update_bill_fields): the last action, by order, on the latest date."""
    best = None
    for a in actions:
        if best is None or a["date"] >= best["date"]:
            best = a
    return best["description"]


def test_the_fixture_rows_are_out_of_order_in_the_table():
    """Guards the fixture: the table's row order is wrong for HB 103 and HB 10."""
    rows = table("Actions")
    for bill_id in ("H   103", "H    10"):
        seq = [int(r["Sequence"]) for r in rows if r["BillID"] == bill_id]
        assert seq != sorted(seq)


def test_hb103_runs_in_the_order_the_legislature_shows():
    """nmlegis.gov's own history for HB 103 (fetched 2026-11-17): prefile, House committees,
    passed House, Senate Tax committee, failed in the Senate, recalled, postponed indefinitely."""
    actions = scrape()["H103"]
    assert descriptions(actions) == [
        "Sent to House Pre-file",
        "Sent to House Commerce & Economic Development Committee & House Taxation & Revenue Committee",
        "DO PASS committee report adopted",
        "DO PASS committee report adopted",
        "passed House",
        "Sent to Senate Tax, Business and Transportation Committee",
        "DO PASS committee report adopted",
        "failed passage in Senate",
        "bill recalled from the House for further consideration by the Senate.",
        "action postponed indefinitely",
    ]
    assert [a["date"] for a in actions] == [
        "2026-01-16",
        "2026-01-22",
        "2026-01-29",
        "2026-02-06",
        "2026-02-11",
        "2026-02-12",
        "2026-02-15",
        "2026-02-17",
        "2026-02-17",
        "2026-03-24",
    ]
    assert latest(actions) == "action postponed indefinitely"


def test_hb10_senate_referral_comes_before_the_senate_committee_report():
    actions = scrape()["H10"]
    d = descriptions(actions)
    referral = d.index(
        "Sent to Senate Health and Public Affairs Committee & Senate Judiciary Committee"
    )
    report = d.index("DO PASS, as amended, committee report adopted")
    assert d.index("passed House") < referral < report
    assert actions[referral]["date"] == "2026-01-29"
    assert actions[report]["date"] == "2026-02-14"
    assert d[-1] == "action postponed indefinitely"


@pytest.mark.parametrize("key", ["H103", "H10", "H88"])
def test_dates_never_go_back_and_no_action_is_lost(key):
    actions = scrape()[key]
    assert [a["date"] for a in actions] == sorted(a["date"] for a in actions)
    bill_id = "H" + " " * (7 - 1 - len(key[1:])) + key[1:]
    assert len(actions) == sum(1 for r in table("Actions") if r["BillID"] == bill_id)


def test_hb88_already_in_order_is_unchanged():
    """A bill whose rows were already in order keeps them (as the govbot copy of the current
    scraper's output has them)."""
    rows = [r for r in table("Actions") if r["BillID"] == "H    88"]
    assert [int(r["Sequence"]) for r in rows] == sorted(
        int(r["Sequence"]) for r in rows
    )
    actions = scrape()["H88"]
    assert [(a["date"], a["description"]) for a in actions] == [
        ("2026-01-15", "Sent to House Pre-file"),
        (
            "2026-01-22",
            "Sent to House Rural Development, Land Grants and Cultural Affairs Committee"
            " & House Appropriations & Finance Committee",
        ),
        ("2026-01-27", "DO PASS committee report adopted"),
        ("2026-02-11", "DO PASS committee report adopted"),
        ("2026-02-12", "passed House"),
        ("2026-02-13", "Sent to Senate Finance Committee"),
        ("2026-03-24", "action postponed indefinitely"),
    ]


def test_sequence_wins_over_the_row_id():
    """On real 2026 data Sequence and KeyID agree, so this one case changes HB 103's real rows:
    the House passage gets the newest row id. Its Sequence (5) still puts it fifth."""
    rows = table("Actions")
    passed = next(
        r for r in rows if r["BillID"] == "H   103" and r["ActionCode"] == "7660"
    )
    passed["KeyID"] = str(max(int(r["KeyID"]) for r in rows) + 1)
    scraper = NMBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill("H103", "2026", "A bill", chamber="lower")
    tables = {"Actions": rows, "TblLocations": table("TblLocations")}
    with mock.patch.object(
        scraper, "access_to_csv", side_effect=lambda name: iter(tables[name])
    ):
        scraper.scrape_actions("H", {"H103": bill})
    assert descriptions(bill.actions).index("passed House") == 4
