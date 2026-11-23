"""OPEN-796: New Mexico's "Succeeding entries" action (code 7798) names, in the Actions table's Succeeding column, the bill
whose committee substitute carries this one on ("Succeeding entries will record the action on the committee substitute",
nmlegis.gov Legislation/Action_Abbreviations). Ramon, 2026-11-23 ("Store all three"): stored as related, never companion,
labelled "Succeeding entries".

The fixtures are rows of the legislature's own databases, LegInfo25.accdb and LegInfo26.accdb (nmlegis.gov
Sessions/<session>/other/, read with mdb-export on 2026-11-23), unchanged: every Actions and Legislation row of HB 2, HB 3,
SB 21, SB 22 and HJR 1, and the whole TblLocations table. The expected links are written out by hand from the Succeeding
values: 2025 HB 3 -> HB 2 and SB 22 -> SB 21; 2026 HB 3 -> HB 2 (the only 7798 rows of either database). Identifiers are
as core stores them (`fix_bill_id`: "HB 2")."""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from nm import NewMexico  # noqa: E402
from nm.bills import NMBillScraper, bill_identifier  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nm_open796")


def table(year, name, edit=None):
    with open(os.path.join(FIXTURES, year, f"{name}.csv"), encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [edit(row) for row in rows] if edit else rows


def links(year, chamber_letter, edit_actions=None):
    """{bill: [(identifier, session, relation_type, label)]} after scrape_actions on the fixture rows of one chamber."""
    session = year
    scraper = NMBillScraper(NewMexico(), "/tmp/")
    scraper.access_to_csv = lambda name: table(
        year, name, edit_actions if name == "Actions" else None
    )
    bills = {
        row["BillID"].replace(" ", ""): Bill(
            bill_identifier(row),
            legislative_session=session,
            chamber="lower" if row["Chamber"] == "H" else "upper",
            title=row["Title"],
            classification="bill",
        )
        for row in table(year, "Legislation")
        if row["BillID"].startswith(chamber_letter)
    }
    scraper.scrape_actions(chamber_letter, bills)
    return {
        bill.identifier: [
            (
                r["identifier"],
                r["legislative_session"],
                r["relation_type"],
                r["ddp_relation_label"],
            )
            for r in bill.related_bills
        ]
        for bill in bills.values()
    }


def test_2025_house_hb3_is_carried_on_in_hb2():
    assert links("2025", "H") == {
        "HB2": [],
        "HB3": [("HB 2", "2025", "related", "Succeeding entries")],
        "HJR1": [],
    }


def test_2025_senate_sb22_is_carried_on_in_sb21():
    assert links("2025", "S") == {
        "SB21": [],
        "SB22": [("SB 21", "2025", "related", "Succeeding entries")],
    }


def test_2026_house_hb3_is_carried_on_in_hb2_and_the_senate_has_none():
    assert links("2026", "H")["HB3"] == [
        ("HB 2", "2026", "related", "Succeeding entries")
    ]
    assert links("2026", "S") == {"SB21": [], "SB22": []}


def test_the_action_itself_is_still_stored():
    session = "2025"
    scraper = NMBillScraper(NewMexico(), "/tmp/")
    scraper.access_to_csv = lambda name: table(session, name)
    hb3 = Bill(
        "HB3",
        legislative_session=session,
        chamber="lower",
        title="t",
        classification="bill",
    )
    scraper.scrape_actions(
        "H",
        {
            "H3": hb3,
            "H2": Bill(
                "HB2",
                legislative_session=session,
                chamber="lower",
                title="t",
                classification="bill",
            ),
        },
    )
    assert "Succeeding entries" in [a["description"] for a in hb3.actions]


def _succeeding(value):
    def edit(row):
        if row["ActionCode"] == "7798":
            row = {**row, "Succeeding": value}
        return row

    return edit


def test_an_empty_self_or_unknown_succeeding_value_gives_no_link():
    for value in ("", "  ", "H 3", "H 999"):
        assert links("2025", "H", _succeeding(value))["HB3"] == [], value


def test_never_a_companion():
    for year, letter in (("2025", "H"), ("2025", "S"), ("2026", "H"), ("2026", "S")):
        for related in links(year, letter).values():
            assert all(r[2] != "companion" for r in related)
