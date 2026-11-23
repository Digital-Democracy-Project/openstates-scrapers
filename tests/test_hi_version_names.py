"""OPEN-804: Hawaii's versions are named by stage, not by file.

The bill page's "All Versions of this Measure" names each text by its file ("HB1163_HD1"), which no
version rule can read, so all 11,369 versions of Hawaii's first scrape (2026) had no stage. Each name
is now the draft it is: "Introduced", "House Draft N", "Senate Draft N", "Conference Draft N"
(scrapers/hi/bills.py, version_name). Proposed drafts, floor amendments and governor's messages are
not texts the bill took, so they are documents.

The fixtures (tests/fixtures/hi_open804/) are the "All Versions of this Measure" panels
(MainContent_UpdatePanel2) of real 2026 measure pages on data.capitol.hawaii.gov
(session/measure_indiv.aspx?billtype=..&billnumber=..&year=2026), saved 2026-11-23, cut out of the page:
HB 1163 (Introduced, HD1, SD1, SD2, CD1), HB 1334 (HD1-HD3, SD1-SD2, CD1, its House and Senate floor
amendments, CD2), SB 2 (Introduced, SD1), GM 1101 (a governor's message: a bill signed into law),
HB 900 ("HB900_HD1.pdf") and SB 903 (proposed drafts, a "HD2_PG20-21.pdf" file).

The link texts below are every shape among the 11,369 stored Hawaii names on the Mac replica
(2026-11-23); the version rule for the names is in core (note_stage, ddp_states/hi.py).
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi.bills import HIBillScraper, version_name  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open804")
BILLS = "https://data.capitol.hawaii.gov/sessions/session2026/bills/"


@pytest.mark.parametrize(
    "link_text,expected",
    [
        ("HB1163", ("Introduced", True)),
        ("SCR62", ("Introduced", True)),
        ("HB1163_HD1", ("House Draft 1", True)),
        ("HB1334_HD3", ("House Draft 3", True)),
        ("HB1163_SD2", ("Senate Draft 2", True)),
        ("SB2_SD1", ("Senate Draft 1", True)),
        ("HB1163_CD1", ("Conference Draft 1", True)),
        ("HB1334_CD2", ("Conference Draft 2", True)),
        ("HB900_HD1.pdf", ("House Draft 1", True)),
        (" HB1163_SD1 ", ("Senate Draft 1", True)),
        ("SB903_SD1_PROPOSED", ("Proposed Senate Draft 1", False)),
        ("HB1494_HD2_PROPOSED", ("Proposed House Draft 2", False)),
        ("SB2627_SD1_PROPOSED_", ("Proposed Senate Draft 1", False)),
        ("HB1334_CD1_HFA4", ("House Floor Amendment 4 to Conference Draft 1", False)),
        (
            "HB1334_CD1_SFA12",
            ("Senate Floor Amendment 12 to Conference Draft 1", False),
        ),
        ("HB2275_SD1_SFA6", ("Senate Floor Amendment 6 to Senate Draft 1", False)),
        ("SB2397_SFA4", ("Senate Floor Amendment 4", False)),
        ("GM1101", ("Governor's Message", False)),
        ("GM1", ("Governor's Message", False)),
        # a shape seen once, not a draft's file: keeps its own name
        ("SB903_HD2_PG20-21.pdf", ("SB903_HD2_PG20-21.pdf", True)),
    ],
)
def test_version_name(link_text, expected):
    assert version_name(link_text) == expected


def parse(measure):
    path = os.path.join(FIX, f"{measure}-2026.html")
    page = lxml.html.parse(path).getroot()
    # as scrape_bill: the list links to capitol.hawaii.gov, the scraper reads data.capitol.hawaii.gov
    page.make_links_absolute("https://capitol.hawaii.gov/session/measure_indiv.aspx")
    kind = measure.rstrip("0123456789")
    bill = Bill(
        f"{kind} {measure[len(kind):]}",
        "2026",
        "title",
        chamber="upper" if kind in ("SB", "GM") else "lower",
    )
    HIBillScraper.parse_bill_versions_table(
        HIBillScraper.__new__(HIBillScraper), bill, page
    )
    return links(bill.versions), links(bill.documents)


def links(items):
    return {i["note"]: [link["url"] for link in i["links"]] for i in items}


def test_hb1163_every_draft_is_named_by_stage():
    versions, documents = parse("HB1163")
    assert versions == {
        "Senate Draft 2": [BILLS + "HB1163_SD2_.HTM", BILLS + "HB1163_SD2_.PDF"],
        "Conference Draft 1": [BILLS + "HB1163_CD1_.HTM", BILLS + "HB1163_CD1_.PDF"],
        "Senate Draft 1": [BILLS + "HB1163_SD1_.HTM", BILLS + "HB1163_SD1_.PDF"],
        "House Draft 1": [BILLS + "HB1163_HD1_.HTM", BILLS + "HB1163_HD1_.PDF"],
        "Introduced": [BILLS + "HB1163_.HTM", BILLS + "HB1163_.PDF"],
    }
    assert documents == {}


def test_hb1334_floor_amendments_are_documents():
    versions, documents = parse("HB1334")
    assert list(versions) == [
        "Conference Draft 2",
        "Conference Draft 1",
        "Senate Draft 2",
        "Senate Draft 1",
        "House Draft 1",
        "House Draft 3",
        "House Draft 2",
        "Introduced",
    ]
    assert documents == {
        "House Floor Amendment 4 to Conference Draft 1": [
            BILLS + "HB1334_CD1_HFA4_.HTM",
            BILLS + "HB1334_CD1_HFA4_.PDF",
        ],
        "Senate Floor Amendment 12 to Conference Draft 1": [
            BILLS + "HB1334_CD1_SFA12_.HTM",
            BILLS + "HB1334_CD1_SFA12_.PDF",
        ],
    }


def test_sb2():
    versions, documents = parse("SB2")
    assert list(versions) == ["Senate Draft 1", "Introduced"]
    assert documents == {}


def test_governors_message_is_a_document():
    versions, documents = parse("GM1101")
    assert versions == {}
    assert documents == {"Governor's Message": [BILLS + "GM1101_.PDF"]}


def test_pdf_file_name_is_its_draft():
    versions, _ = parse("HB900")
    assert list(versions) == ["House Draft 2", "House Draft 1", "Introduced"]
    assert versions["House Draft 1"] == [
        BILLS + "HB900_HD1.HTM",
        BILLS + "HB900_HD1.PDF",
    ]


def test_sb903_proposed_drafts_are_documents():
    versions, documents = parse("SB903")
    assert sorted(documents) == ["Proposed House Draft 2", "Proposed Senate Draft 1"]
    assert sorted(versions) == [
        "Conference Draft 1",
        "House Draft 1",
        "House Draft 2",
        "Introduced",
        "SB903_HD2_PG20-21.pdf",
        "Senate Draft 1",
        "Senate Draft 2",
    ]
