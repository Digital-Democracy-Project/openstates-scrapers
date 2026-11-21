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


# OPEN-643: fixture -> the label kept (congress.gov's own types, each once, "Identical bill" first, at most 100
# characters). Written out by hand from each fixture's <relationshipDetails>, not produced by the scraper.
EXPECTED_LABEL = {
    "identical-bill": "Identical bill",
    "identical-bill-related-bill": "Identical bill; Related bill",
    "identical-bill-public-law-contains-the-text": "Identical bill; Public law contains the text",
    # 108 characters in full: the last type does not fit.
    "identical-bill-primarycompanionbillbecamelaw-public-law-contains-the-text-secondarycompanionbillbecamelaw": (
        "Identical bill; PrimaryCompanionBillBecameLaw; SecondaryCompanionBillBecameLaw"
    ),
    "related-bill": "Related bill",
    "procedurally-related": "Procedurally related",
    "procedurally-related-related-bill": "Related bill; Procedurally related",
    "procedurally_hyphen_related": "Procedurally-related",
    "procedurally_hyphen_related-related-bill": "Related bill; Procedurally-related",
    "cross-congress-related-bill": "Cross-Congress related bill",
    "public-law-contains-the-text": "Public law contains the text",
    "public-law-contains-the-text-related-bill": "Related bill; Public law contains the text",
    # 106 characters in full: the last type does not fit.
    "primarycompanionbillbecamelaw-public-law-contains-the-text-related-bill-secondarycompanionbillbecamelaw": (
        "Related bill; PrimaryCompanionBillBecameLaw; SecondaryCompanionBillBecameLaw"
    ),
    "contained-in-public-law-related-bill": "Related bill; Contained in public law",
    "text-similarities": "Text similarities",
}


def _links(related_bills):
    """OPEN-725's helper, OPEN-643: the label (core data.0052's `ddp_relation_label`) is compared on its own (see
    test_label_is_congress_gov_s_own_types); the rest is compared exactly here."""
    links = []
    for link in related_bills:
        link = dict(link)
        link.pop("ddp_relation_label", None)
        links.append(link)
    return links


def scrape_raw(name):
    root = ET.parse(os.path.join(FIXTURES, f"{name}.xml")).getroot()
    bill = Bill(
        f"{root.findtext('bill/type')} {root.findtext('bill/number')}",
        root.findtext("bill/congress"),
        "A bill",
        chamber="lower",
    )
    USBillScraper(jurisdiction="usa", datadir="/tmp").scrape_related_bills(bill, root)
    return bill.related_bills


def scrape(name):
    return _links(scrape_raw(name))


def test_every_fixture_is_covered():
    on_disk = {f[:-4] for f in os.listdir(FIXTURES) if f.endswith(".xml")}
    assert on_disk == set(EXPECTED) == set(EXPECTED_LABEL)


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


@pytest.mark.parametrize("name", sorted(EXPECTED_LABEL))
def test_label_is_congress_gov_s_own_types(name):
    """OPEN-643: every link keeps congress.gov's own types as its label; the companion/related mapping above is
    unchanged by it."""
    (link,) = scrape_raw(name)
    assert link["ddp_relation_label"] == EXPECTED_LABEL[name]
    assert len(link["ddp_relation_label"]) <= 100


def test_a_link_with_no_type_has_no_label():
    root = ET.fromstring(
        "<root><bill><relatedBills><item><type>HR</type><number>1</number><congress>119</congress>"
        "</item></relatedBills></bill></root>"
    )
    bill = Bill("HR 2", "119", "A bill", chamber="lower")
    USBillScraper(jurisdiction="usa", datadir="/tmp").scrape_related_bills(bill, root)
    assert bill.related_bills == [
        {
            "identifier": "HR 1",
            "legislative_session": "119",
            "relation_type": "related",
            "ddp_relation_label": None,
        }
    ]
