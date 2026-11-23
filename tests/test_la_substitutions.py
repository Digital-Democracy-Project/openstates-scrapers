"""OPEN-795: a Louisiana committee substitute is stored as a link between the two bills (Ramon, 2026-11-23, "Store all
three"): the original says where it went ("Becomes HB 1257."; "Title of substitute read and adopted; becomes Senate Bill
No. 426."), the substitute names the bill it replaces ("... substitute for HB No. 123 reported by ..."; "Substitute for Senate
Bill No. 168."). The original is `replaced-by` the substitute, labelled "Becomes"; the substitute `replaces` the original,
labelled "substitute for". Never a companion.

The fixtures are legis.la.gov's own bill pages (BillInfo.aspx, the page the scraper reads), fetched 2026-11-23, unchanged:
HB 123 and HB 1257, SB 168 and SB 426, HCR 15 and HCR 86 (2026 Regular Session), and HB 42, which has no substitution. The
expected links are written out by hand from each page's history. No test makes a live call.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from la.bills import LABillScraper, substitution_links  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "la_open795")


def related(name, identifier, chamber):
    with open(os.path.join(FIXTURES, f"{name}.html"), encoding="utf-8") as f:
        page = lxml.html.fromstring(f.read())
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.start_year = "2026"
    bill = Bill(identifier, "2026", "A bill", chamber=chamber)
    scraper.scrape_actions(bill, page)
    return [
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    ]


@pytest.mark.parametrize(
    "name,identifier,chamber,expected",
    [
        ("HB123", "HB 123", "lower", [("HB 1257", "2026", "replaced-by", "Becomes")]),
        (
            "HB1257",
            "HB 1257",
            "lower",
            [("HB 123", "2026", "replaces", "substitute for")],
        ),
        ("SB168", "SB 168", "upper", [("SB 426", "2026", "replaced-by", "Becomes")]),
        (
            "SB426",
            "SB 426",
            "upper",
            [("SB 168", "2026", "replaces", "substitute for")],
        ),
        ("HCR15", "HCR 15", "lower", [("HCR 86", "2026", "replaced-by", "Becomes")]),
        (
            "HCR86",
            "HCR 86",
            "lower",
            [("HCR 15", "2026", "replaces", "substitute for")],
        ),
        ("HB42", "HB 42", "lower", []),
    ],
)
def test_each_page_links_its_substitution_once(name, identifier, chamber, expected):
    assert related(name, identifier, chamber) == expected


def test_a_law_number_and_a_committee_report_are_not_bills():
    assert substitution_links("Signed by the Governor. Becomes Act No. 5.") == []
    assert (
        substitution_links("Becomes Act No. 12 without the Governor's signature.") == []
    )
    assert substitution_links("Reported by substitute (8-2).") == []


def test_the_spelled_out_and_short_forms_read_the_same():
    assert substitution_links(
        "Title of substitute read and adopted; becomes Senate Bill No. 426."
    ) == [("SB 426", "replaced-by", "Becomes")]
    assert substitution_links("Substitute for Senate Bill No. 168. Read by title") == [
        ("SB 168", "replaces", "substitute for")
    ]
    assert substitution_links(
        "Read by title,substitute title adopted, ... substitute for HR No. 80 reported byt"
    ) == [("HR 80", "replaces", "substitute for")]


def test_a_line_naming_the_bill_itself_or_a_repeat_adds_nothing():
    page = lxml.html.fromstring(
        "<html><body><table><tr><th>Date</th><th>Chamber</th><th>Journal Page</th><th>Action</th></tr>"
        "<tr><td>3/10</td><td>H</td><td></td><td>Becomes HB 9.</td></tr>"
        "<tr><td>3/9</td><td>H</td><td></td><td>Becomes HB 9.</td></tr>"
        "<tr><td>3/8</td><td>H</td><td></td><td>Becomes HB 5.</td></tr>"
        "</table></body></html>"
    )
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.start_year = "2026"
    bill = Bill("HB 5", "2026", "A bill", chamber="lower")
    scraper.scrape_actions(bill, page)
    assert [(r["identifier"], r["relation_type"]) for r in bill.related_bills] == [
        ("HB 9", "replaced-by")
    ]
