"""OPEN-869: a Missouri House bill XML action is filed under the chamber whose journal records it
(<HouseJournalStartPage> / <SenateJournalStartPage>), not the (H)/(S) in its text or the bill's own chamber.

Fixtures are real 2026 files from documents.house.mo.gov/xml (tests/fixtures/mo_open869/): HCR 21 (saved
2026-11-24), whose "Adopted (H)" of 01-08 with 31 ayes is the Senate's adoption (Senate Journal p. 118), and
HB 1786 (saved 2026-11-20), whose "Truly Agreed To and Finally Passed" with 26 ayes is the Senate's final vote.
"""
import json
import os
import sys

import lxml.etree
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from mo.bills import MOBillScraper, journal_chamber  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mo_open869")


def actions(name, bill_id):
    root = lxml.etree.parse(os.path.join(FIXTURES, name)).getroot()
    bill = Bill(bill_id, "2026", "t", chamber="lower")
    MOBillScraper(jurisdiction="x", datadir="/tmp").parse_house_actions(root, bill)
    return [
        (
            str(a["date"])[:10],
            json.loads(a["organization_id"][1:])["classification"],
            a["description"],
            a["classification"],
        )
        for a in bill.actions
    ]


def test_hcr21_senate_adoption_is_the_senates():
    assert [(d, ch, text) for d, ch, text, _ in actions("HCR21.xml", "HCR 21")] == [
        ("2026-01-07", "lower", "Offered (H)"),
        (
            "2026-01-07",
            "lower",
            "Adopted (H)",
        ),  # the House's own adoption (House Journal p. 4)
        ("2026-01-07", "upper", "Reported to the Senate"),
        ("2026-01-08", "upper", "Taken Up"),
        ("2026-01-08", "upper", "Adopted (H) - AYES: 31 NOES: 0 PRESENT: 0"),
        (
            "2026-01-08",
            "upper",
            "Escort Committee - Senators:  Luetkemeyer, Brown (16), Cierpiot, Crawford, Bean, Beck, "
            "May, McCreery, Lewis and Williams.",
        ),
        # a message is read into the receiving chamber's journal
        ("2026-01-08", "lower", "Senate Message (S)"),
        (
            "2026-01-12",
            "lower",
            "Escort Committee - Representatives: Anderson, Hein, Proudie, Mosley, Kelley, Coleman, "
            "Durnell, Farnan, Roberts and Taylor (48).",
        ),
        ("2026-01-12", "upper", "House Message (H)"),
    ]


def test_hb1786_senate_final_passage_is_the_senates_and_the_rest_keep_theirs():
    got = actions("HB1786.xml", "HB 1786")
    by_text = {}
    for d, ch, text, labels in got:
        by_text.setdefault(text, []).append(ch)
    assert by_text["Third Read and Passed (H) - AYES: 139 NOES: 4 PRESENT: 3"] == [
        "lower"
    ]
    assert by_text[
        "Truly Agreed To and Finally Passed - AYES: 26 NOES: 0 PRESENT: 0"
    ] == ["upper"]
    assert by_text["Taken Up for Third Reading (S)"] == ["upper"]
    # no journal cited: the text's marker, as before
    assert by_text["Prefiled (H)"] == ["lower"]
    assert [
        ch for _, ch, t, _ in got if t.startswith("Public Hearing Scheduled (S)")
    ] == ["upper"]
    assert by_text["Voted Do Pass (S)"] == ["upper"]
    # the Governor's actions stay the executive's where the text names the Governor
    assert by_text["Delivered to Governor"] == ["executive"]
    # each chamber's passage is filed under that chamber
    passages = [
        (ch, text[:20]) for _, ch, text, labels in got if "passage" in (labels or [])
    ]
    assert passages == [
        ("lower", "Third Read and Passe"),
        ("upper", "Truly Agreed To and "),
    ]


def _action(xml):
    return lxml.etree.fromstring(f"<Action>{xml}</Action>")


@pytest.mark.parametrize(
    "xml,expected",
    [
        ("<HouseJournalStartPage>4</HouseJournalStartPage>", "lower"),
        ("<SenateJournalStartPage>118</SenateJournalStartPage>", "upper"),
        ("<Description>Prefiled (H)</Description>", None),
        # none stored: both journals name no single chamber
        (
            "<HouseJournalStartPage>1</HouseJournalStartPage><SenateJournalStartPage>2</SenateJournalStartPage>",
            None,
        ),
    ],
)
def test_journal_chamber(xml, expected):
    assert journal_chamber(_action(xml)) == expected
