from pathlib import Path

import lxml.html
import pytest
from openstates.scrape import Bill
from spatula import URL

from nv.bills import UTF8_PARSER, BillTabText, ExhibitTabText, FiscalTabText

# OPEN-941: NELIS tabs saved 2026-11-27 (Bill/FillSelectedBillTab?selectedTab=...&billKey=...).
# no_notes_fiscal.html is hand-made from the "no fiscal notes" notice upstream #6048 describes.
FIXTURES = Path(__file__).parent / "fixtures" / "nv_open941"
BASE = "https://www.leg.state.nv.us/App/NELIS/REL/83rd2025/Bill/FillSelectedBillTab"


def _run(page_class, tab, bill_key, fixture):
    bill = Bill("AB 105", "83", "t", chamber="lower", classification="bill")
    url = f"{BASE}?selectedTab={tab}&billKey={bill_key}"
    page = page_class(bill, source=URL(url))
    page.root = lxml.html.fromstring(
        (FIXTURES / fixture).read_bytes(), parser=UTF8_PARSER
    )
    page.root.make_links_absolute(url)
    return bill, page.process_page()


def _fiscal_docs(bill):
    return [(d["note"], d["links"][0]["url"]) for d in bill.documents]


def test_text_tab_hands_over_to_exhibits_tab():
    bill = Bill("AB 105", "83", "t", chamber="lower", classification="bill")
    page = BillTabText(bill, source=URL(f"{BASE}?selectedTab=Text&billKey=12000"))
    page.root = lxml.html.fromstring(b"<div></div>", parser=UTF8_PARSER)
    nxt = page.process_page()
    assert str(nxt.source) == f"{BASE}?selectedTab=Exhibits&billKey=12000"


def test_exhibits_tab_hands_over_to_fiscal_notes_tab_not_exhibits_again():
    bill, nxt = _run(ExhibitTabText, "Exhibits", 12000, "ab105_83_exhibits.html")
    assert isinstance(nxt, FiscalTabText)
    assert str(nxt.source) == f"{BASE}?selectedTab=FiscalNotes&billKey=12000"
    # the exhibits themselves are still stored, and none of them as a fiscal note
    assert bill.documents
    assert not any(d["note"].startswith("Fiscal Note") for d in bill.documents)


@pytest.mark.parametrize(
    "fixture,bill_key,expected",
    [
        # AB10 (2025): one fiscal note
        (
            "ab10_83_fiscal.html",
            11760,
            [("Fiscal Note: Local Government  (As Introduced)", "4892")],
        ),
        # AB105 (2025): three requested notes and one unsolicited, under a second list
        (
            "ab105_83_fiscal.html",
            12000,
            [
                (
                    "Fiscal Note: Department of Public Safety, Records, "
                    "Communications and Compliance Division  (As Introduced)",
                    "1294",
                ),
                (
                    "Fiscal Note: Department of Public Safety, Capitol Police  "
                    "(As Introduced)",
                    "766",
                ),
                ("Fiscal Note: Department of Corrections  (As Introduced)", "105"),
                ("Fiscal Note: Department of Corrections  (1st Reprint)", "15215"),
            ],
        ),
        ("no_notes_fiscal.html", 1, []),
    ],
)
def test_fiscal_notes_tab_stores_each_note(fixture, bill_key, expected):
    bill, result = _run(FiscalTabText, "FiscalNotes", bill_key, fixture)
    assert result is bill
    assert _fiscal_docs(bill) == [
        (title, f"https://www.leg.state.nv.us/Session/83rd2025/FiscalNotes/{n}.pdf")
        for title, n in expected
    ]
    for d in bill.documents:
        assert d["links"][0]["media_type"] == "application/pdf"
