"""OPEN-811: Maine's printed LD paper is named by its stage, "Introduced (LD n, HP n)".

The bill-text page (display_ps.asp) heads the bill's printed paper with its numbers only ("Text / LD 144 /
SP 80"), which no version rule can read, so 2,368 of the 5,131 versions of Maine's first scrape (the 132nd,
sessions 132R1, 132S1, 132R2; Mac replica) had no stage. That paper is the Legislative Document as printed at
introduction (its first page: "Legislative Document No. 144 / S.P. 80 / In Senate, January 14, 2025 ...
Reference to the Committee on Marine Resources suggested and ordered printed"); a committee New Draft is a
Legislative Document of its own with new numbers, so an LD paper with other numbers than the bill's own
is never "Introduced" (scrapers/me/bills.py, version_name, add_bill_texts).

The fixtures (tests/fixtures/me_open811/) are real 132nd bill-text pages, legislature.maine.gov
legis/bills/display_ps.asp?paper=<paper>&snum=132, saved 2026-11-23:
HP 73 (LD 108, 132R1, carried over, two committee amendments, public law), HP 197 (LD 297, 132R1, carried
over, five amendments, public law), HP 1020 (LD 1562, 132S1), HP 1374 (LD 2050, 132R2, private and special
law), SP 80 (LD 144, 132R1), SP 538 (LD 1308, 132S1, a Resolve), SP 851 (LD 2063, 132R2), SP 919 (LD 0, 132R2,
a joint resolution).
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from openstates.utils.version_ordering import (  # noqa: E402
    STAGE_AMENDMENT,
    STAGE_ENACTED,
    STAGE_INTRODUCED,
    note_stage,
    version_sort_key,
)
from me.bills import add_bill_texts, version_name  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "me_open811")
SITE = "https://legislature.maine.gov/legis/bills/"


@pytest.mark.parametrize(
    "title,bill_id,expected",
    [
        ("LD 144 SP 80", "LD 144", "Introduced (LD 144, SP 80)"),
        ("LD 2050 HP 1374", "LD 2050", "Introduced (LD 2050, HP 1374)"),
        # a joint resolution's paper has LD 0; the bill is its paper
        ("LD 0 SP 919", "SP 919", "Introduced (LD 0, SP 919)"),
        (" LD 108  HP 73 ", "LD 108", "Introduced (LD 108, HP 73)"),
        # every other header keeps its name, spacing included (shapes among the replica's 5,131 names)
        ("Amendment C-A (S-46)", "LD 144", "Amendment C-A (S-46)"),
        ("Amendment H-A to C-A (H-701)", "LD 297", "Amendment H-A to C-A (H-701)"),
        ("Chapter 82", "LD 144", "Chapter 82"),
        ("ACTPS  Chapter 12", "LD 2050", "ACTPS  Chapter 12"),
        # a paper header with anything more is not the plain LD paper
        ("LD 144 SP 80 Draft", "LD 144", "LD 144 SP 80 Draft"),
        ("Amendment LD 144 SP 80", "LD 144", "Amendment LD 144 SP 80"),
        # an LD paper with other numbers than the bill's own is a committee New Draft
        ("LD 1890 HP 1210", "LD 54", "Amended in New Draft (LD 1890, HP 1210)"),
        ("LD 14 SP 80", "LD 144", "Amended in New Draft (LD 14, SP 80)"),
        ("LD 0 SP 920", "SP 919", "Amended in New Draft (LD 0, SP 920)"),
        # only an LD 0 paper is the bill named by its paper
        ("LD 14 SP 80", "SP 80", "Amended in New Draft (LD 14, SP 80)"),
        ("LD 14 HP 80", "HP 80", "Amended in New Draft (LD 14, HP 80)"),
        ("LD 0 HP 499", "HP 499", "Introduced (LD 0, HP 499)"),
    ],
)
def test_version_name(title, bill_id, expected):
    assert version_name(title, bill_id) == expected


def test_names_have_their_stage_in_core():
    assert note_stage("Introduced (LD 144, SP 80)") == (STAGE_INTRODUCED, 0.0)
    assert note_stage("Introduced (LD 0, SP 919)") == (STAGE_INTRODUCED, 0.0)
    assert note_stage("Amended in New Draft (LD 1890, HP 1210)")[0] == STAGE_AMENDMENT


# each saved page's bill, as the search results name it
BILL_IDS = {
    "HP0073": "LD 108",
    "HP0197": "LD 297",
    "HP1020": "LD 1562",
    "HP1374": "LD 2050",
    "SP0080": "LD 144",
    "SP0538": "LD 1308",
    "SP0851": "LD 2063",
    "SP0919": "SP 919",
}


def parse(paper):
    page = lxml.html.parse(os.path.join(FIX, f"display_ps_132_{paper}.html")).getroot()
    page.make_links_absolute(f"{SITE}display_ps.asp?paper={paper}&snum=132")
    bill = Bill(BILL_IDS[paper], "132R1", "title", chamber="lower")
    add_bill_texts(bill, page)
    return bill


def versions(bill):
    return {v["note"]: [link["url"] for link in v["links"]] for v in bill.versions}


def pdf(paper, item):
    return [f"{SITE}getPDF.asp?paper={paper}&item={item}&snum=132"]


def test_carried_over_bill_with_five_amendments():
    # HP 197 / LD 297 (132R1, carried over, public law): each text once, with its own PDF
    assert versions(parse("HP0197")) == {
        "Introduced (LD 297, HP 197)": pdf("HP0197", 1),
        "Amendment C-A (H-537)": pdf("HP0197", 2),
        "Amendment S-A (S-392)": pdf("HP0197", 6),
        "Chapter 373": pdf("HP0197", 8),
        "Amendment S-A to C-A (S-324)": pdf("HP0197", 4),
        "Amendment H-A (H-664)": pdf("HP0197", 5),
        "Amendment H-A to C-A (H-701)": pdf("HP0197", 7),
    }


@pytest.mark.parametrize(
    "paper,introduced,rest",
    [
        (
            "HP0073",
            "Introduced (LD 108, HP 73)",
            {"Amendment C-A (H-154)", "Amendment C-B (H-155)", "Chapter 131"},
        ),
        (
            "HP1020",
            "Introduced (LD 1562, HP 1020)",
            {"Amendment C-A (H-579)", "Chapter 395"},
        ),
        ("HP1374", "Introduced (LD 2050, HP 1374)", {"ACTPS  Chapter 12"}),
        (
            "SP0080",
            "Introduced (LD 144, SP 80)",
            {"Amendment C-A (S-46)", "Chapter 82"},
        ),
        (
            "SP0538",
            "Introduced (LD 1308, SP 538)",
            {"Amendment C-A (S-314)", "Chapter 82"},
        ),
        (
            "SP0851",
            "Introduced (LD 2063, SP 851)",
            {"Amendment C-A (S-508)", "Amendment C-B (S-509)", "Chapter 590"},
        ),
        ("SP0919", "Introduced (LD 0, SP 919)", set()),
    ],
)
def test_each_page_has_one_introduced_text(paper, introduced, rest):
    found = versions(parse(paper))
    assert found[introduced] == pdf(paper, 1)  # the LD paper is the page's item 1
    assert set(found) == {introduced} | rest
    assert [n for n in found if note_stage(n)[0] == STAGE_INTRODUCED] == [introduced]


@pytest.mark.parametrize(
    "paper", ["HP0073", "HP0197", "HP1020", "HP1374", "SP0080", "SP0538", "SP0851"]
)
def test_every_text_has_a_stage_and_orders_introduced_amendments_chapter(paper):
    bill = parse(paper)
    for order in (bill.versions, list(reversed(bill.versions))):
        notes = [
            v["note"]
            for v in sorted(
                order,
                key=lambda v: version_sort_key(
                    v["note"], v.get("date"), [link["url"] for link in v["links"]]
                ),
            )
        ]
        stages = [note_stage(n)[0] for n in notes]
        assert stages[0] == STAGE_INTRODUCED
        assert stages[-1] == STAGE_ENACTED
        assert set(stages[1:-1]) <= {STAGE_AMENDMENT}


def test_fiscal_notes_stay_documents():
    # the fiscal notes are documents, named as before (not versions)
    bill = parse("SP0080")
    assert "LD 144 SP 80 - Fiscal Note" in [d["note"] for d in bill.documents]
    assert not [v for v in bill.versions if "Fiscal" in v["note"]]


def redrafted_page(first):
    """SP 80's saved page with its own paper block copied under new numbers (LD 1890, HP 1210, item 9),
    placed before (first=True) or after the bill's own. No 132nd page has two LD papers: the bill
    directory lists one "Printed LD PDF" for each of its 2,245 LDs."""
    with open(os.path.join(FIX, "display_ps_132_SP0080.html")) as f:
        page = lxml.html.fromstring(f.read())
    own = page.cssselect("span.tlnk-bill")[0]
    redraft = lxml.html.fromstring(
        lxml.html.tostring(own, encoding="unicode")
        .replace("LD 144", "LD 1890")
        .replace("SP 80", "HP 1210")
        .replace("item=1", "item=9")
    )
    if first:
        own.addprevious(redraft)
    else:
        own.addnext(redraft)
    page.make_links_absolute(f"{SITE}display_ps.asp?paper=SP0080&snum=132")
    return page


@pytest.mark.parametrize("first", [True, False])
def test_a_new_draft_on_the_page_is_never_introduced(first):
    bill = Bill("LD 144", "132R1", "title", chamber="upper")
    add_bill_texts(bill, redrafted_page(first))
    found = versions(bill)
    assert found["Introduced (LD 144, SP 80)"] == pdf("SP0080", 1)
    assert found["Amended in New Draft (LD 1890, HP 1210)"] == pdf("SP0080", 9)


def test_an_ld_paper_of_another_bill_alone_is_not_introduced():
    # the page holds only an LD paper that is not the bill's own: no "Introduced" at all
    page = redrafted_page(first=True)
    own = page.cssselect("span.tlnk-bill")[1]
    own.getparent().remove(own)
    bill = Bill("LD 144", "132R1", "title", chamber="upper")
    add_bill_texts(bill, page)
    names = [v["note"] for v in bill.versions]
    assert "Amended in New Draft (LD 1890, HP 1210)" in names
    assert not [n for n in names if n.startswith("Introduced")]
