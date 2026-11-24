from pathlib import Path

import lxml.html
import pytest
from openstates.scrape import Bill
from spatula import URL

from nv.bills import UTF8_PARSER, BillTabText

# OPEN-830: bill Text tabs saved from NELIS on 2026-11-24
# (Bill/FillSelectedBillTab?selectedTab=Text&billKey=...).
FIXTURES = Path(__file__).parent / "fixtures" / "nv_open830"
SESSION_URL = "https://www.leg.state.nv.us/Session"


def _texts(fixture, slug, bill_key):
    bill = Bill("AB 1", "84", "t", chamber="lower", classification="bill")
    url = (
        f"https://www.leg.state.nv.us/App/NELIS/REL/{slug}/Bill/"
        f"FillSelectedBillTab?selectedTab=Text&billKey={bill_key}"
    )
    page = BillTabText(bill, source=URL(url))
    page.root = lxml.html.fromstring(
        (FIXTURES / fixture).read_bytes(), parser=UTF8_PARSER
    )
    page.root.make_links_absolute(url)
    page.process_page()
    versions = [(v["note"].strip(), v["links"][0]["url"]) for v in bill.versions]
    documents = [(d["note"], d["links"][0]["url"]) for d in bill.documents]
    return versions, documents


@pytest.mark.parametrize(
    "fixture,slug,bill_key,versions,documents",
    [
        # 2025 special session AB 4: four reprints, five amendments (one only proposed)
        (
            "ab4_2025special36_text.html",
            "36th2025Special",
            12994,
            [
                ("As Introduced", "36th2025Special/Bills/AB/AB4.pdf"),
                ("Reprint 1", "36th2025Special/Bills/AB/AB4_R1.pdf"),
                ("Reprint 2", "36th2025Special/Bills/AB/AB4_R2.pdf"),
                ("Reprint 3", "36th2025Special/Bills/AB/AB4_R3.pdf"),
                ("Reprint 4", "36th2025Special/Bills/AB/AB4_R4.pdf"),
                ("As Enrolled", "36th2025Special/Bills/AB/AB4_EN.pdf"),
            ],
            [
                ("Amendment 13", "36th2025Special/Bills/Amendments/A_AB4_13.pdf"),
                ("Amendment 5", "36th2025Special/Bills/Amendments/A_AB4_5.pdf"),
                ("Amendment 15", "36th2025Special/Bills/Amendments/A_AB4_R1_15.pdf"),
                ("Amendment 31", "36th2025Special/Bills/Amendments/A_AB4_R2_31.pdf"),
                ("Amendment 34", "36th2025Special/Bills/Amendments/A_AB4_R3_34.pdf"),
            ],
        ),
        # 2025 regular session AB 105: the same page shape
        (
            "ab105_83_text.html",
            "83rd2025",
            12000,
            [
                ("As Introduced", "83rd2025/Bills/AB/AB105.pdf"),
                ("Reprint 1", "83rd2025/Bills/AB/AB105_R1.pdf"),
                ("As Enrolled", "83rd2025/Bills/AB/AB105_EN.pdf"),
            ],
            [("Amendment 287", "83rd2025/Bills/Amendments/A_AB105_287.pdf")],
        ),
        # 84th (2027) session AB 1: pre-filed, introduced text only
        (
            "ab1_84_text.html",
            "84th2027",
            13014,
            [("As Introduced", "84th2027/Bills/AB/AB1.pdf")],
            [],
        ),
    ],
)
def test_amendments_are_documents_and_texts_are_versions(
    fixture, slug, bill_key, versions, documents
):
    got_versions, got_documents = _texts(fixture, slug, bill_key)
    assert got_versions == [(n, f"{SESSION_URL}/{u}") for n, u in versions]
    assert got_documents == [(n, f"{SESSION_URL}/{u}") for n, u in documents]
