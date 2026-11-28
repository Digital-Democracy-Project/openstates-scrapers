import json
from pathlib import Path

import lxml.html
from openstates.scrape import Bill
from spatula import URL

import nv.bills
from nv.bills import UTF8_PARSER, BillTabText

# OPEN-940 (upstream #6035): Nevada no longer asks for the "Amendments" tab. The old
# request fetched the Exhibits tab a second time (its URL has no "Text" to replace) and
# its selector matched nothing, so it added nothing. NELIS tabs saved from the live site:
# the Text tab on 2026-11-24 (OPEN-830), the Exhibits tab on 2026-11-27.
TESTS = Path(__file__).parent / "fixtures"
TEXT = TESTS / "nv_open830" / "ab105_83_text.html"
EXHIBITS = TESTS / "nv_open940" / "ab105_83_exhibits.html"
GOLDEN = TESTS / "nv_open940" / "ab105_83_bill_from_fork_main.json"
TEXT_URL = (
    "https://www.leg.state.nv.us/App/NELIS/REL/83rd2025/Bill/"
    "FillSelectedBillTab?selectedTab=Text&billKey=12000"
)


def _walk():
    """Follow the page chain as the scraper does, answering every tab from a saved
    page (an unknown tab gets the Exhibits page, as the real site did for the old
    Exhibits-shaped URLs). Returns the bill and the (class, tab) of every page asked for."""
    bill = Bill("AB 105", "83", "t", chamber="lower", classification="bill")
    page = BillTabText(bill, source=URL(TEXT_URL))
    asked = []
    while not isinstance(page, Bill):  # the last page returns the finished bill
        if isinstance(page.source, str):  # spatula makes it a URL when it fetches
            page.source = URL(page.source)
        url = page.source.url
        tab = url.split("selectedTab=")[1].split("&")[0]
        asked.append((type(page).__name__, tab))
        html = TEXT if tab == "Text" else EXHIBITS
        page.root = lxml.html.fromstring(html.read_bytes(), parser=UTF8_PARSER)
        page.root.make_links_absolute(url)
        page = page.process_page()
    return bill, asked


def test_the_amendments_tab_is_never_requested():
    _, asked = _walk()
    assert not hasattr(nv.bills, "AmendmentTabText")
    assert [name for name, _ in asked] == [
        "BillTabText",
        "ExhibitTabText",
        "FiscalTabText",
    ]
    assert all(tab != "Amendments" for _, tab in asked)


def test_bill_output_is_what_it_was_with_the_amendments_request():
    # the golden file is this same walk run on fork main (c3ff46e14), where the
    # Amendments page is asked for and adds nothing: 3 texts, 38 documents, every field
    golden = json.loads(GOLDEN.read_text())
    bill, _ = _walk()
    assert bill.versions == golden["versions"]
    assert bill.documents == golden["documents"]
    assert len(golden["versions"]) == 3 and len(golden["documents"]) == 38
