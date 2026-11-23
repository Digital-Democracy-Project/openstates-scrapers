"""Tests for OPEN-784: Rhode Island's versions were named by bill number, which has no stage.

The search page (status.rilegislature.gov) links only a bill's current text, and the scraper
named it by the link text: "7603", "7532  SUB B as amended". openstates-core's note_stage() has
no stage for those, so 2,936 of RI's 3,011 2026 versions had none. The texts a bill had before
its current one (the introduced text of every substituted or amended bill) were not kept.

The legislature's text index for each chamber and year lists every text, in the order they were
printed, and each text's own header names it by its file's ending (read 2026-11-23):
H7532 (introduced), H7532A "SUBSTITUTE A", H7532Aaa "SUBSTITUTE A AS AMENDED", H7532B
"SUBSTITUTE B", H7532Baa "SUBSTITUTE B AS AMENDED"; H7007aa "AS AMENDED".

tests/fixtures/ri_open784/ holds the real 2026 search entries of six bills (H7007, H7008,
H7031, H7532, H7603, S2048) and the two real 2026 text indexes cut to those bills' rows.
"""
import os
import re
import sys

import pytest
import scrapelib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ri.bills as ri_bills  # noqa: E402
from ri.bills import RIBillScraper  # noqa: E402
from openstates.utils.version_ordering import (  # noqa: E402
    STAGE_INTRODUCED,
    STAGE_UNKNOWN,
    note_stage,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ri_open784")
TEXT = "http://webserver.rilegislature.gov/BillText/BillText26/"


class _Response:
    def __init__(self, text, url="", status_code=200):
        self.text, self.url, self.status_code = text, url, status_code


def _scraper(fail_index=False):
    """A scraper whose search returns the fixture's six bills and whose GETs read the
    fixture text indexes; `fail_index` makes the index unreadable: "http" an HTTP error,
    "empty" an empty page."""
    page = open(os.path.join(FIXTURES, "bills_2026.html"), encoding="utf-8").read()
    # the next range search finds nothing: the page without its entries
    empty = (
        page[: page.index("<div>House")] + page[page.index("<br /><br /><div><table") :]
    )
    pages = [page]
    fetched = []

    def get(url):
        fetched.append(url)
        if fail_index == "http":
            raise scrapelib.HTTPError(_Response("", url, 503))
        if fail_index == "empty":
            return _Response("")
        name = url.rpartition("/")[2]
        return _Response(open(os.path.join(FIXTURES, name), encoding="latin-1").read())

    scraper = object.__new__(RIBillScraper)
    scraper.info = scraper.warning = lambda *a, **k: None
    scraper.post = lambda url, data: _Response(pages.pop() if pages else empty)
    scraper.get = get
    scraper._bill_id_by_type = {}
    scraper._text_index = {}
    return scraper, fetched


def _bills(monkeypatch, **kw):
    monkeypatch.setattr(ri_bills, "get_default_headers", lambda page: {})
    monkeypatch.setattr(ri_bills, "bill_start_numbers", lambda session: {"lower": [1]})
    scraper, fetched = _scraper(**kw)
    bills = list(scraper.scrape_bills("lower", "2026", {}))
    return {b.identifier: b for b in bills}, fetched


def _versions(bill):
    return [(v["note"], [ln["url"] for ln in v["links"]]) for v in bill.versions]


def test_each_text_is_named_by_its_stage_oldest_first(monkeypatch):
    bills, _ = _bills(monkeypatch)
    house = TEXT + "HouseText26/"
    assert _versions(bills["HR7532"]) == [
        ("Introduced", [house + "H7532.pdf"]),
        ("Substitute A", [house + "H7532A.pdf"]),
        ("Substitute A As Amended", [house + "H7532Aaa.pdf"]),
        ("Substitute B", [house + "H7532B.pdf"]),
        ("Substitute B As Amended", [house + "H7532Baa.pdf"]),
    ]
    assert _versions(bills["HB7007"]) == [
        ("Introduced", [house + "H7007.pdf"]),
        ("As Amended", [house + "H7007aa.pdf"]),
    ]
    assert _versions(bills["HB7008"]) == [
        ("Introduced", [house + "H7008.pdf"]),
        ("Substitute A", [house + "H7008A.pdf"]),
    ]
    assert _versions(bills["HR7031"]) == [
        ("Introduced", [house + "H7031.pdf"]),
        ("Substitute A", [house + "H7031A.pdf"]),
        ("Substitute A As Amended", [house + "H7031Aaa.pdf"]),
    ]
    # a bill never amended keeps its one text, now named as introduced
    assert _versions(bills["HB7603"]) == [("Introduced", [house + "H7603.pdf"])]


def test_the_current_text_stays_the_last_version(monkeypatch):
    """The last version is the text the search page links as current, the link it had before.
    S2048's index lists a Substitute A printed after the "as amended" text the search page
    shows as current, so it is left out."""
    bills, _ = _bills(monkeypatch)
    page = open(os.path.join(FIXTURES, "bills_2026.html"), encoding="utf-8").read()
    links = re.findall(r"No\. <a href=\"([^\"]+)\"", page)
    assert len(links) == len(bills) == 6
    for bill in bills.values():
        number = re.search(r"\d+", bill.identifier).group(0)
        (link,) = [u for u in links if re.search(rf"/[HS]{number}[A-Za-z]*\.pdf$", u)]
        assert bill.versions[-1]["links"][0]["url"] == link, bill.identifier
    assert _versions(bills["SB2048"]) == [
        ("Introduced", [TEXT + "SenateText26/S2048.pdf"]),
        ("As Amended", [TEXT + "SenateText26/S2048aa.pdf"]),
    ]


def test_every_name_has_a_stage(monkeypatch):
    """The gate this ticket is for: core's note_stage() (DDP fork) gives every name a stage,
    and only the first text is the introduced one."""
    bills, _ = _bills(monkeypatch)
    for bill in bills.values():
        stages = [note_stage(v["note"])[0] for v in bill.versions]
        assert STAGE_UNKNOWN not in stages, bill.identifier
        assert stages[0] == STAGE_INTRODUCED
        assert STAGE_INTRODUCED not in stages[1:], bill.identifier


def test_each_index_is_read_once(monkeypatch):
    _, fetched = _bills(monkeypatch)
    assert sorted(fetched) == [
        TEXT + "HouseText26/HouseText26.html",
        TEXT + "SenateText26/SenateText26.html",
    ]


@pytest.mark.parametrize("fail_index", ["http", "empty"])
def test_unreadable_index_keeps_the_current_text(monkeypatch, fail_index):
    bills, _ = _bills(monkeypatch, fail_index=fail_index)
    assert _versions(bills["HR7532"]) == [
        ("Substitute B As Amended", [TEXT + "HouseText26/H7532Baa.pdf"])
    ]
    assert _versions(bills["HB7603"]) == [
        ("Introduced", [TEXT + "HouseText26/H7603.pdf"])
    ]


def test_a_link_of_another_shape_keeps_its_link_text():
    scraper, fetched = _scraper()
    assert scraper.bill_texts(TEXT + "HouseText26/H7603.htm") is None
    assert scraper.bill_texts("http://example.org/BillText/law26.pdf") is None
    assert fetched == []
