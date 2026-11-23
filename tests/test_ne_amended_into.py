"""OPEN-794: Nebraska names another bill only in a history line like "Provisions/portions of LB890 amended into LB901 by
AM2406" (Ramon, 2026-11-23, "Store all three"). Each such pair is stored as `related` on the bill's own page, never
companion, the label saying which way: "amended into" on the bill whose provisions moved, "provisions amended in" on the
bill that took them in. A line naming the same bill twice, or two other bills, gives no link.

The fixtures are nebraskalegislature.gov's own bill pages (view_bill.php, the page the scraper reads), fetched 2026-11-23,
unchanged: 109th Legislature LB 890, LB 901, LB 958, LB 1033, LB 1038, LB 935, LB 1209 and LB 901A, and LB 48, which has
no such line. The expected links are written out by hand from each page's history. No test makes a live call.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ne.bills import NEBillScraper, amended_into_links  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ne_open794")


def related(name):
    with open(os.path.join(FIXTURES, f"{name}.html"), encoding="utf-8") as f:
        page = lxml.html.fromstring(f.read())
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill(name, "109", "A bill", classification="bill")
    scraper.scrape_actions(bill, page)
    return sorted(
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        # carried: LB 890's provisions went into LB 901
        ("LB890", [("LB 901", "109", "related", "amended into")]),
        # LB 958 took in four bills
        (
            "LB958",
            [
                ("LB 1033", "109", "related", "provisions amended in"),
                ("LB 701", "109", "related", "provisions amended in"),
                ("LB 773", "109", "related", "provisions amended in"),
                ("LB 777", "109", "related", "provisions amended in"),
            ],
        ),
        # LB 1033's own history does not carry the line LB 958's does: nothing to read on its page
        ("LB1033", []),
        # LB 1038's history names LB 1033 into LB 958 (two other bills): no link
        ("LB1038", []),
        # an appropriation bill carried "by rules suspension"
        ("LB901A", [("LB 1209", "109", "related", "amended into")]),
        ("LB48", []),
    ],
)
def test_each_page_links_its_pairs_with_the_right_direction(name, expected):
    assert related(name) == expected


def test_a_bill_both_carrying_and_carried_gets_both_labels():
    # LB 901 took in six bills and was itself amended into LB 803
    took_in = ["LB 1109", "LB 1110", "LB 1131", "LB 873", "LB 890", "LB 920"]
    assert related("LB901") == sorted(
        [(b, "109", "related", "provisions amended in") for b in took_in]
        + [("LB 803", "109", "related", "amended into")]
    )


def test_a_bill_taking_in_appropriation_bills():
    took_in = ["LB 1101A", "LB 1235A", "LB 759A", "LB 847A", "LB 867A", "LB 901A"]
    assert related("LB1209") == sorted(
        (b, "109", "related", "provisions amended in") for b in took_in
    )


def test_a_line_naming_the_bill_itself_on_both_sides_gives_no_self_link():
    assert "LB935" not in {
        identifier.replace(" ", "") for identifier, *_ in related("LB935")
    }
    assert (
        amended_into_links(
            "LB 935", "Provisions/portions of LB935 amended into LB935 by AM2927"
        )
        == []
    )


def test_the_line_forms_read_the_same():
    assert amended_into_links(
        "LB 901A",
        "Provisions/portions of LB901A amended into LB1209 by rules suspension",
    ) == [("LB1209", "amended into")]
    assert amended_into_links(
        "LB 1209",
        "Provisions/portions of LB901A amended into LB1209 by rules suspension",
    ) == [("LB901A", "provisions amended in")]
    assert amended_into_links(
        "LB 901", "Provisions/portions of LB 890 amended into LB 901 by FA12"
    ) == [("LB890", "provisions amended in")]
    assert amended_into_links("LB 901", "Placed on Final Reading") == []


def test_never_a_companion():
    for name in ("LB890", "LB901", "LB958", "LB901A", "LB1209", "LB935"):
        assert all(
            relation_type == "related" for _, _, relation_type, _ in related(name)
        )


def test_a_repeated_line_is_stored_once():
    # 16 (bill, pair) combinations repeat on the same bill's history in the 109th (Mac replica, 2026-11-23)
    row = "<tr><td>Feb 10, 2026</td><td>Provisions/portions of LB890 amended into LB901 by AM2406</td><td></td></tr>"
    page = lxml.html.fromstring(
        f'<html><body><table class="history"><tbody>{row}{row}</tbody></table></body></html>'
    )
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill("LB901", "109", "A bill", classification="bill")
    scraper.scrape_actions(bill, page)
    assert [(r["identifier"], r["ddp_relation_label"]) for r in bill.related_bills] == [
        ("LB 890", "provisions amended in")
    ]
