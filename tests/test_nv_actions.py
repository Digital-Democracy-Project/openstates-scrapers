import json
from pathlib import Path

import lxml.html
from spatula import URL

from nv.bills import UTF8_PARSER, BillStub, BillTabDetail

# OPEN-840: bill Overview tabs (with the history table) saved from NELIS on 2026-11-24
# (Bill/FillSelectedBillTab?selectedTab=Overview&billKey=...), 2025 special session.
FIXTURES = Path(__file__).parent / "fixtures" / "nv_open840"


def _actions(fixture, identifier, bill_key, day=None):
    url = (
        "https://www.leg.state.nv.us/App/NELIS/REL/36th2025Special/Bill/"
        f"FillSelectedBillTab?selectedTab=Overview&billKey={bill_key}"
    )
    stub = BillStub(url, identifier, "2025Special36", "36th2025Special", [])
    page = BillTabDetail(stub, source=URL(url))
    page.root = lxml.html.fromstring(
        (FIXTURES / fixture).read_bytes(), parser=UTF8_PARSER
    )
    bill = next(iter(page.process_page())).input
    return [
        (
            a["description"],
            json.loads(a["organization_id"][1:])["classification"],
            sorted(a["classification"]),
        )
        for a in bill.actions
        if day is None or a["date"].strftime("%m-%d") == day
    ]


def test_sb1_one_action_per_printed_line():
    assert _actions("sb1_2025special36_overview.html", "SB1", 12990) == [
        # Nov 12: "Prefiled." and the referral are two printed lines
        ("Prefiled.", "upper", ["introduction"]),
        (
            "Referred to Select Committee on Public Safety and Security. To printer.",
            "upper",
            ["referral-committee"],
        ),
        # Nov 13: was one action tagged committee-passage, passage, reading-1, reading-3
        ("From printer.", "upper", []),
        ("Read first time. To committee.", "upper", ["reading-1"]),
        ("From committee: Do pass.", "upper", ["committee-passage"]),
        ("Declared an emergency measure under the Constitution.", "upper", []),
        (
            "Read third time. Passed. Title approved. (Yeas:\xa021, Nays:\xa0None.) "
            "To Assembly.",
            "upper",
            ["passage", "reading-3"],
        ),
        # Nov 14: "In Assembly." moves the chamber for itself and the lines after it
        ("In Assembly.", "lower", []),
        ("Read first time.", "lower", ["reading-1"]),
        (
            "Referred to Select Committee on Public Safety and Security.",
            "lower",
            ["referral-committee"],
        ),
        ("To committee.", "lower", []),
        ("From committee: Do pass.", "lower", ["committee-passage"]),
        ("Placed on Second Reading File.", "lower", []),
        ("Read second time.", "lower", ["reading-2"]),
        (
            "Read third time. Passed. Title approved. "
            "(Yeas:\xa039, Nays:\xa0None, Excused:\xa03.)",
            "lower",
            ["passage", "reading-3"],
        ),
        ("To Senate.", "lower", []),
        ("In Senate. To enrollment.", "upper", ["passage"]),
        (
            "Enrolled and delivered to Governor.",
            "executive",
            ["enrolled", "executive-receipt"],
        ),
        ("Approved by the Governor. Chapter 5.", "executive", ["executive-signature"]),
    ]


def test_ab1_both_chambers_on_one_day_are_split():
    # Nov 15: Assembly passage, then "In Senate." and the Senate's steps, one cell on NELIS
    assert _actions("ab1_2025special36_overview.html", "AB1", 12988, "11-15") == [
        (
            "From committee: Amend, and do pass as amended.",
            "lower",
            ["committee-passage"],
        ),
        ("Declared an emergency measure under the Constitution.", "lower", []),
        ("Read third time. Amended. (Amend. No. 11.)", "lower", ["reading-3"]),
        ("Dispensed with reprinting.", "lower", []),
        (
            "Read third time. Passed, as amended. Title approved, as amended. "
            "(Yeas:\xa042, Nays:\xa0None.)",
            "lower",
            ["passage", "reading-3"],
        ),
        ("To printer.", "lower", []),
        ("From printer. To engrossment. Engrossed. First reprint.", "lower", []),
        ("To Senate.", "lower", []),
        ("In Senate.", "upper", []),
        (
            "Read first time. Referred to Select Committee on Public Safety and "
            "Security. To committee.",
            "upper",
            ["reading-1", "referral-committee"],
        ),
        (
            "From committee: Amend, and do pass as amended.",
            "upper",
            ["committee-passage"],
        ),
        ("Declared an emergency measure under the Constitution.", "upper", []),
        ("Read third time. Amended. (Amend. No. 14.)", "upper", ["reading-3"]),
        ("Reprinting dispensed with.", "upper", []),
        (
            "Read third time. Passed, as amended. Title approved. "
            "(Yeas:\xa019, Nays:\xa0None, Excused:\xa02.) To printer.",
            "upper",
            ["passage", "reading-3"],
        ),
    ]


def test_ab4_concurrence_day_moves_chamber_four_times():
    # Nov 19: returned to the Senate, passage rescinded, passed again, then the
    # Assembly concurs; NELIS prints all of it in one cell
    assert _actions("ab4_2025special36_overview.html", "AB4", 12994, "11-19") == [
        (
            "From printer. To re-engrossment. Re-engrossed. Third reprint. "
            "To Assembly.",
            "upper",
            [],
        ),
        ("In Assembly.", "lower", []),
        ("Returned from Assembly in accordance with motion of the body.", "lower", []),
        ("Returned to Senate.", "lower", []),
        ("In Senate.", "upper", []),
        ("Action of passage rescinded.", "upper", []),
        ("Placed on General File.", "upper", []),
        ("Read third time. Amended. (Amend. No. 34.)", "upper", ["reading-3"]),
        ("Reprinting dispensed with.", "upper", []),
        (
            "Read third time. Passed, as amended. Title approved, as amended. "
            "(Yeas:\xa016, Nays:\xa02, Excused:\xa03.) To printer.",
            "upper",
            ["passage", "reading-3"],
        ),
        (
            "From printer. To re-engrossment. Re-engrossed. Fourth reprint. "
            "To Assembly.",
            "upper",
            [],
        ),
        ("In Assembly.", "lower", []),
        (
            "Senate Amendment Nos. 31 and 34 concurred in. To enrollment.",
            "lower",
            ["passage"],
        ),
    ]
