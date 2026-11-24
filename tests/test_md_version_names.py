"""OPEN-813: Maryland's bill texts are named by the legislature's reader, without the bill title.

A bill's history table lists each printed text as "Text - <reader> - <bill title>". The scraper named the version
"<reader> - <bill title>" ("First - Motor Vehicles - Police Stops - ..."), which no version rule reads: 3,838 of
the 5,128 versions of Maryland's first scrape (2026, 2026s1; Mac replica) had no stage, and words in a title
("Governor", "Veto", "Chapter") gave 122 others a wrong one. The readers, as the General Assembly's Legislative
Lingo defines them: First Reader, the bill as first printed (<bill>f.pdf); Third Reader, printed after second
reading in the chamber of origin with the adopted amendments (<bill>t.pdf); Enrolled, the bill as amended in the
opposite chamber (<bill>e.pdf); Chapter, the law as signed (Chapters_noln/CH_<n>_...), or a joint resolution's
resolution number (Chapters_noln/JR_<n>_...) (scrapers/md/bills.py, version_name).

The fixtures (tests/fixtures/md_open813/) are real bill pages, mgaleg.maryland.gov/mgawebsite/Legislation/Details/
<bill>?ys=<session>, saved 2026-11-24 and trimmed to the page's main body (div#mainBody, without scripts and the
mobile copy of the history table): HB 998 (House, all four texts, chaptered from its enrolled text), SB 947
(Senate, all four), SB 982 (Senate, chaptered from its third reader), HB 81 and SB 854 (first reader and a Racial
Equity Impact Note), HJ 6 (a joint resolution with a resolution number), HB 2101 and SB 2102 (2026S1).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils.version_ordering import (  # noqa: E402
    STAGE_CHAMBER_PASSAGE,
    STAGE_ENACTED,
    STAGE_FINAL_PASSAGE,
    STAGE_INTRODUCED,
    STAGE_UNKNOWN,
    note_stage,
    version_sort_key,
)
from md.bills import MDBillScraper, version_name  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "md_open813")
SITE = "http://mgaleg.maryland.gov/"
REIN = "Racial Equity Impact Note"


@pytest.mark.parametrize(
    "link_text,url,expected",
    [
        (
            "Text - First - Motor Vehicles - Police Stops - Secondary Enforcement and Excludable Evidence",
            SITE + "2026RS/bills/hb/hb0081f.pdf",
            "Introduced (First Reader)",
        ),
        (
            "Text - Third - Baltimore City – Alcoholic Beverages – 46th Alcoholic Beverages District",
            SITE + "2026RS/bills/hb/hb0998t.pdf",
            "Engrossed (Third Reader)",
        ),
        (
            "Text - Enrolled - Maryland Transit Administration Reform Act",
            SITE + "2026RS/bills/sb/sb0947e.pdf",
            "Enrolled",
        ),
        (
            "Text - Chapter - Maryland Transit Administration Reform Act",
            SITE + "2026RS/Chapters_noln/CH_419_sb0947e.pdf",
            "Chapter 419",
        ),
        (
            "Text - Chapter - Judicial Compensation Commission - Recommendations",
            SITE + "2026RS/Chapters_noln/JR_4_hj0006f.pdf",
            "Chapter (Joint Resolution 4)",
        ),
        # a chapter link without its number keeps the reader's name
        ("Text - Chapter - A Title", SITE + "2026RS/chapters/hb0001.pdf", "Chapter"),
        # words in a title never name the text
        (
            "Text - First - Governor's Appointments - Veto Override - Chapter Laws",
            SITE + "2026RS/bills/hb/hb0001f.pdf",
            "Introduced (First Reader)",
        ),
        (
            "Text - Third - Enrolled Bills - Concurred Amendments",
            SITE + "2026RS/bills/sb/sb0001t.pdf",
            "Engrossed (Third Reader)",
        ),
        # any other reader keeps its own name, without the title
        (
            "Text - " + REIN,
            SITE + "Pubs/BudgetFiscal/2026RS-HB0081-REIN.pdf",
            REIN,
        ),
        (
            "Text - Committee Reprint - A Title",
            SITE + "2026RS/bills/hb/hb0001c.pdf",
            "Committee Reprint",
        ),
    ],
)
def test_version_name(link_text, url, expected):
    assert version_name(link_text, url) == expected


def test_names_have_their_stage_in_core():
    assert note_stage("Introduced (First Reader)")[0] == STAGE_INTRODUCED
    assert note_stage("Engrossed (Third Reader)")[0] == STAGE_CHAMBER_PASSAGE
    assert note_stage("Enrolled")[0] == STAGE_FINAL_PASSAGE
    assert note_stage("Chapter 419")[0] == STAGE_ENACTED
    assert note_stage("Chapter (Joint Resolution 4)")[0] == STAGE_ENACTED


class FakeResponse:
    def __init__(self, content):
        self.content = content


class OfflineMD(MDBillScraper):
    """Serves one saved bill page through the real scrape_bill()."""

    def __init__(self, page):
        self.page = page

    def get(self, url, **kwargs):
        with open(os.path.join(FIX, self.page), "rb") as f:
            return FakeResponse(f.read())

    def warning(self, *args, **kwargs):
        pass


def scrape(page):
    session = "2026s1" if page.endswith("2026S1.html") else "2026"
    chamber = "lower" if page.startswith("h") else "upper"
    url = "https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/" + page[:6]
    (bill,) = OfflineMD(page).scrape_bill(chamber, session, url)
    return bill


def versions(bill):
    return {v["note"]: [link["url"] for link in v["links"]] for v in bill.versions}


def bills(path):
    return [SITE + path]


EXPECTED = {
    "hb0998_2026RS.html": {
        "Introduced (First Reader)": bills("2026RS/bills/hb/hb0998f.pdf"),
        "Engrossed (Third Reader)": bills("2026RS/bills/hb/hb0998t.pdf"),
        "Enrolled": bills("2026RS/bills/hb/hb0998e.pdf"),
        "Chapter 844": bills("2026RS/Chapters_noln/CH_844_hb0998e.pdf"),
    },
    "sb0947_2026RS.html": {
        "Introduced (First Reader)": bills("2026RS/bills/sb/sb0947f.pdf"),
        "Engrossed (Third Reader)": bills("2026RS/bills/sb/sb0947t.pdf"),
        "Enrolled": bills("2026RS/bills/sb/sb0947e.pdf"),
        "Chapter 419": bills("2026RS/Chapters_noln/CH_419_sb0947e.pdf"),
    },
    "sb0982_2026RS.html": {
        "Introduced (First Reader)": bills("2026RS/bills/sb/sb0982f.pdf"),
        "Engrossed (Third Reader)": bills("2026RS/bills/sb/sb0982t.pdf"),
        "Chapter 687": bills("2026RS/Chapters_noln/CH_687_sb0982t.pdf"),
    },
    "hb0081_2026RS.html": {
        "Introduced (First Reader)": bills("2026RS/bills/hb/hb0081f.pdf"),
    },
    "sb0854_2026RS.html": {
        "Introduced (First Reader)": bills("2026RS/bills/sb/sb0854f.pdf"),
    },
    "hj0006_2026RS.html": {
        "Introduced (First Reader)": bills("2026RS/bills/hj/hj0006f.pdf"),
        "Chapter (Joint Resolution 4)": bills("2026RS/Chapters_noln/JR_4_hj0006f.pdf"),
    },
    "hb2101_2026S1.html": {
        "Introduced (First Reader)": bills("2026S1/bills/hb/hb2101f.pdf"),
        "Engrossed (Third Reader)": bills("2026S1/bills/hb/hb2101t.pdf"),
        "Chapter 882": bills("2026S1/Chapters_noln/CH_882_hb2101t.pdf"),
    },
    "sb2102_2026S1.html": {
        "Introduced (First Reader)": bills("2026S1/bills/sb/sb2102f.pdf"),
    },
}


@pytest.mark.parametrize("page", sorted(EXPECTED))
def test_saved_pages(page):
    # the Racial Equity Impact Note is not a text of the bill: OPEN-814 makes it a document
    bill = scrape(page)
    texts = {note: url for note, url in versions(bill).items() if note != REIN}
    assert texts == EXPECTED[page]
    for note in texts:
        assert bill.title not in note
        assert note_stage(note)[0] != STAGE_UNKNOWN


@pytest.mark.parametrize(
    "page",
    [
        "hb0998_2026RS.html",
        "sb0947_2026RS.html",
        "sb0982_2026RS.html",
        "hj0006_2026RS.html",
        "hb2101_2026S1.html",
    ],
)
def test_order_introduced_third_reader_enrolled_chapter(page):
    texts = [v for v in scrape(page).versions if v["note"] != REIN]
    for order in (texts, texts[::-1]):
        notes = [
            v["note"]
            for v in sorted(
                order,
                key=lambda v: version_sort_key(
                    v["note"], v.get("date"), [link["url"] for link in v["links"]]
                ),
            )
        ]
        assert notes == list(EXPECTED[page]), notes
