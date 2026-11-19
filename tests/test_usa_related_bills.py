"""OPEN-638: the federal scraper keeps congress.gov's relation type; only "Identical bill" is a companion.

The fixtures are real GovInfo BILLSTATUS files (https://www.govinfo.gov/bulkdata/BILLSTATUS/, fetched 2026-11-18 for
the polled bills of the 118th and 119th Congresses), cut down to the bill's number, type and congress and ONE of its
<relatedBills> items, unchanged. There is one file per combination of types found in those files (15 combinations,
1,110 links): each item's <relationshipDetails> may carry several types, and congress.gov spells "Procedurally related"
two ways. The expected label comes from the plan's rule (PLAN-companion-lineage phase 1, D1), written out here by hand,
not from the scraper: "companion" exactly when "Identical bill" is among the item's types.
"""
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from usa.bills import USBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "usa_open638")

# fixture -> (related bill, its congress, expected relation_type)
EXPECTED = {
    "identical-bill": ("SJRES 59", "118", "companion"),
    "identical-bill-related-bill": ("HR 8811", "118", "companion"),
    "identical-bill-public-law-contains-the-text": ("S 1438", "119", "companion"),
    "identical-bill-primarycompanionbillbecamelaw-public-law-contains-the-text-secondarycompanionbillbecamelaw": (
        "S 841",
        "119",
        "companion",
    ),
    "related-bill": ("SJRES 96", "118", "related"),
    "procedurally-related": ("HRES 1173", "118", "related"),
    "procedurally-related-related-bill": ("HRES 1194", "118", "related"),
    "procedurally_hyphen_related": ("HRES 1243", "118", "related"),
    "procedurally_hyphen_related-related-bill": ("HRES 1576", "118", "related"),
    "cross-congress-related-bill": ("HJRES 1", "118", "related"),
    "public-law-contains-the-text": ("S 724", "119", "related"),
    "public-law-contains-the-text-related-bill": ("HR 3944", "119", "related"),
    "primarycompanionbillbecamelaw-public-law-contains-the-text-related-bill-secondarycompanionbillbecamelaw": (
        "HR 5169",
        "119",
        "related",
    ),
    "contained-in-public-law-related-bill": ("HR 7730", "119", "related"),
    "text-similarities": ("HR 4563", "118", "related"),
}


def scrape(name):
    root = ET.parse(os.path.join(FIXTURES, f"{name}.xml")).getroot()
    bill = Bill(
        f"{root.findtext('bill/type')} {root.findtext('bill/number')}",
        root.findtext("bill/congress"),
        "A bill",
        chamber="lower",
    )
    USBillScraper(jurisdiction="usa", datadir="/tmp").scrape_related_bills(bill, root)
    return bill.related_bills


def test_every_fixture_is_covered():
    on_disk = {f[:-4] for f in os.listdir(FIXTURES) if f.endswith(".xml")}
    assert on_disk == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_relation_type_follows_congress_gov(name):
    identifier, congress, relation_type = EXPECTED[name]
    assert scrape(name) == [
        {
            "identifier": identifier,
            "legislative_session": congress,
            "relation_type": relation_type,
        }
    ]


def test_a_rules_resolution_is_never_a_companion():
    """The plan's go/no-go check 3: no "Procedurally related" link (either spelling) is a companion."""
    for name in EXPECTED:
        if "procedurally" in name:
            assert scrape(name)[0]["relation_type"] == "related", name
