from pathlib import Path

import lxml.html
import pytest
from spatula import URL

from nv.bills import UTF8_PARSER, BillStub, BillTabDetail

# OPEN-829: bill Overview tabs saved from NELIS on 2026-11-23
# (Bill/FillSelectedBillTab?selectedTab=Overview&billKey=...).
FIXTURES = Path(__file__).parent / "fixtures" / "nv_open829"


def _sponsors(fixture, identifier, session, slug, bill_key):
    stub = BillStub(
        f"https://www.leg.state.nv.us/App/NELIS/REL/{slug}/Bill/{bill_key}/Overview",
        identifier,
        session,
        slug,
        [],
    )
    url = (
        f"https://www.leg.state.nv.us/App/NELIS/REL/{slug}/Bill/"
        f"FillSelectedBillTab?selectedTab=Overview&billKey={bill_key}"
    )
    page = BillTabDetail(stub, source=URL(url))
    page.root = lxml.html.fromstring(
        (FIXTURES / fixture).read_bytes(), parser=UTF8_PARSER
    )
    page.root.make_links_absolute(url)
    bill = next(iter(page.process_page())).input
    return [(s["name"], s["entity_type"], s["primary"]) for s in bill.sponsorships]


@pytest.mark.parametrize(
    "fixture,identifier,session,slug,bill_key,expected",
    [
        # special session: the committee is named without the word "Committee"
        (
            "ab1_2025special36_overview.html",
            "AB1",
            "2025Special36",
            "36th2025Special",
            12988,
            [("Assembly Health and Wellness", "organization", True)],
        ),
        # special session: two senators
        (
            "sr1_2025special36_overview.html",
            "SR1",
            "2025Special36",
            "36th2025Special",
            12982,
            [
                ("Nicole Cannizzaro", "person", True),
                ("Robin Titus", "person", True),
            ],
        ),
        # regular session: "Assembly Committee on ..."
        (
            "ab1_84_overview.html",
            "AB1",
            "84",
            "84th2027",
            13014,
            [
                (
                    "Assembly Committee on Growth and Infrastructure",
                    "organization",
                    True,
                )
            ],
        ),
        # regular session: an Assembly member
        (
            "ab42_84_overview.html",
            "AB42",
            "84",
            "84th2027",
            13094,
            [("Bert Gurr", "person", True)],
        ),
    ],
)
def test_committee_sponsors_are_organizations_and_legislators_people(
    fixture, identifier, session, slug, bill_key, expected
):
    assert _sponsors(fixture, identifier, session, slug, bill_key) == expected
