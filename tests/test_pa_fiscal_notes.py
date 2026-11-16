"""OPEN-576: Pennsylvania's fiscal and actuarial notes come from the daily Bill History
export as well as from the bill page, so a page served without its "Supporting Documents"
list no longer deletes the stored notes.

Fixtures (pa_open576/), all real and unchanged:
- three bills (HB 274, HB 1088, SB 146) cut out of the 2025-2026 export downloaded on
  2026-11-16 (exportDate "November 15, 2026 7:30:14 PM EST");
- the three bills' pages as palegis.us served them on 2026-11-16.
On that day the replica stored no fiscal note for HB 1088, one of HB 274's three and
one of SB 146's two, though the pages and the export list them all.
No request leaves the test.
"""
import io
import os
import zipfile
from unittest import mock

import lxml.html
import pytest

from openstates.scrape import Bill
from pa import utils
from pa.bills import PABillScraper

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pa_open576")
EXPORT = os.path.join(FIXTURES, "PA-Bill-History-2025-RegularSession-sample.xml")
FN = "https://www.palegis.us/WU01/LI/BI/FN/2025/0/"
SFN = "https://www.palegis.us/WU01/LI/BI/SFN/2025/0/"
ACTUARIAL = (
    "https://www.ifo.state.pa.us/Resources/Documents/Actuarial/"
    "Act_21_Pension_Analysis_2026_08.pdf"
)

# every note the export lists for the three bills, as the page names them
EXPECTED = {
    "HB 1088": {("House Fiscal Note", FN + "HB1088P1205.pdf")},
    "HB 274": {
        ("House Fiscal Note", FN + "HB0274P2683.pdf"),
        ("Senate Fiscal Note", SFN + "HB0274P2674.pdf"),
        ("House Fiscal Note", FN + "HB0274P1026.pdf"),
    },
    "SB 146": {
        ("House Fiscal Note", FN + "SB0146P1888.pdf"),
        ("Actuarial Note PN1888", ACTUARIAL),
        ("Senate Fiscal Note", SFN + "SB0146P0131.pdf"),
    },
}
PAGES = {"HB 1088": "hb1088.html", "HB 274": "hb274.html", "SB 146": "sb146.html"}


def export_bytes():
    with open(EXPORT, "rb") as f:
        return f.read()


def bill_page(bill_id, drop_notes=False):
    with open(os.path.join(FIXTURES, PAGES[bill_id]), encoding="utf-8") as f:
        page = lxml.html.fromstring(f.read())
    page.make_links_absolute(utils.info_url("2025-2026", 0, bill_id))
    if drop_notes:
        # the page as it comes back on a bad night: no fiscal or actuarial note links
        for a in page.xpath('//div[@id="section-pn"]//a'):
            if "Note" in a.text_content():
                a.drop_tree()
    return page


def scraper_for(page, export_documents):
    scraper = PABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.export_documents = export_documents
    scraper.session_year = "2025"
    empty = lxml.html.fromstring("<html><body></body></html>")

    def get_page(url):
        # the bill page, then amendment lists (not under test) come back empty
        return page if "/legislation/bills/" in url else empty

    scraper.get_page = get_page
    # votes are not under test
    scraper.parse_votes = lambda bill, page: iter(())
    return scraper


def scraped_notes(bill_id, drop_notes=False, export_documents=None):
    if export_documents is None:
        export_documents = utils.supporting_documents(export_bytes())
    scraper = scraper_for(bill_page(bill_id, drop_notes), export_documents)
    link = lxml.html.fromstring(
        '<a class="bill" href="/legislation/bills/2025/%s">%s</a>'
        % (bill_id.replace(" ", "").lower(), bill_id)
    )
    chamber = "lower" if bill_id.startswith("H") else "upper"
    (bill,) = [
        o
        for o in scraper.parse_bill(chamber, "2025-2026", 0, link)
        if isinstance(o, Bill)
    ]
    return bill.documents


def as_pairs(documents):
    return {(d["note"], link["url"]) for d in documents for link in d["links"]}


# --- the export reader ---------------------------------------------------------------


def test_export_lists_every_note_named_as_the_page_names_it():
    documents = utils.supporting_documents(export_bytes())
    assert set(documents) == {"HB274", "HB1088", "SB146"}
    for bill_id, expected in EXPECTED.items():
        assert set(documents[utils.bill_key(bill_id)]) == expected


def test_a_bill_without_notes_is_left_out():
    xml = (
        b'<historyExport exportDate="November 15, 2026 7:30:14 PM EST"><session>'
        b"<bill><body>H</body><type>B</type><number>0017</number>"
        b"<supportingDocuments/></bill></session></historyExport>"
    )
    assert utils.supporting_documents(xml) == {}


def test_media_type_comes_from_the_link():
    assert utils.document_media_type(FN + "HB1088P1205.pdf") == "application/pdf"
    assert utils.document_media_type("https://x/y.htm?a=b") == "text/html"
    assert utils.document_media_type("https://x/y") == ""


# --- parse_bill ----------------------------------------------------------------------


@pytest.mark.parametrize("bill_id", sorted(EXPECTED))
def test_good_page_yields_every_note(bill_id):
    assert as_pairs(scraped_notes(bill_id)) == EXPECTED[bill_id]
    # and the page alone (no export) already does, with the stored names
    assert as_pairs(scraped_notes(bill_id, export_documents={})) == EXPECTED[bill_id]


@pytest.mark.parametrize("bill_id", sorted(EXPECTED))
def test_page_without_its_notes_still_yields_them_from_the_export(bill_id):
    assert as_pairs(scraped_notes(bill_id, drop_notes=True)) == EXPECTED[bill_id]


def test_page_without_its_notes_and_no_export_drops_them_as_before():
    # the OPEN-576 failure: what the import was given on the nights the notes vanished
    notes = scraped_notes("HB 1088", drop_notes=True, export_documents={})
    assert notes == []


@pytest.mark.parametrize("bill_id", sorted(EXPECTED))
def test_good_and_bad_pages_give_the_same_documents(bill_id):
    # the same documents in the same order, so the import sees no change between nights
    assert scraped_notes(bill_id) == scraped_notes(bill_id, drop_notes=True)


def test_one_document_per_note_name():
    # page and export links of the same name land in one document, not two
    notes = scraped_notes("HB 274")
    assert [d["note"] for d in notes] == ["House Fiscal Note", "Senate Fiscal Note"]
    assert [link["media_type"] for d in notes for link in d["links"]] == [
        "application/pdf"
    ] * 3


def test_a_note_on_the_page_but_not_yet_in_the_export_is_kept():
    # a note filed after the export was built: only the page has it
    export_documents = utils.supporting_documents(export_bytes())
    export_documents["HB274"] = [
        n for n in export_documents["HB274"] if "P1026" not in n[1]
    ]
    pairs = as_pairs(scraped_notes("HB 274", export_documents=export_documents))
    assert pairs == EXPECTED["HB 274"]


# --- scrape(): the export is read once per run, full walk or incremental --------------


def zipped(xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("PA-Bill-History-2025-RegularSession.xml", xml)
    return buf.getvalue()


def run_scrape(content=None, error=None, **kwargs):
    scraper = PABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.jurisdiction = mock.Mock(legislative_sessions=[{"identifier": "2025-2026"}])
    index = lxml.html.fromstring(
        '<html><body><a class="bill" href="/legislation/bills/2025/hb1088">HB 1088</a>'
        "</body></html>"
    )
    scraper.get_page = mock.Mock(return_value=index)
    scraper.get = mock.Mock(return_value=mock.Mock(content=content), side_effect=error)
    seen = []
    scraper.parse_bill = lambda *a: seen.append(dict(scraper.export_documents)) or iter(
        ()
    )
    list(scraper.scrape(chamber="lower", session="2025-2026", **kwargs))
    return scraper, seen


def test_full_walk_reads_the_export_once_for_its_notes():
    scraper, seen = run_scrape(content=zipped(export_bytes()))
    scraper.get.assert_called_once()
    assert seen[0]["HB1088"] == [("House Fiscal Note", FN + "HB1088P1205.pdf")]


@pytest.mark.parametrize(
    "content,error",
    [(b"not a zip", None), (None, RuntimeError("503"))],
    ids=["garbage", "download-fails"],
)
def test_unreadable_export_leaves_the_pages_alone_as_before(content, error):
    scraper, seen = run_scrape(content=content, error=error)
    assert seen == [{}]


def test_export_with_broken_documents_still_walks_on_the_pages():
    broken = export_bytes().replace(b"<number>1088</number>", b"<number>x</number>")
    scraper, seen = run_scrape(content=zipped(broken))
    assert seen == [{}]
