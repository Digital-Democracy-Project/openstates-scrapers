"""Tests for OPEN-808: Mississippi's bill authors keep the name the legislature prints and their chamber.

The bill's history XML (billstatus.ls.state.ms.us/<session>/pdf/history/<HB|SB|SN>/<bill>.xml) prints each
author once (P_NAME / CO_NAME) with a link to the author's page under House_authors/ or Senate_authors/
(P_LINK / CO_LINK). Two members of one chamber who share a surname are printed with their district
("Simmons (12th)"); a surname unique in its chamber is printed bare ("Boyd" in the Senate, while the House
has "Boyd (19th)" and "Boyd (37th)"). The scraper used to keep only the first word of the principal author
and no chamber, so neither could be matched. The fixtures are real 2026 histories, read 2026-11-23, run
through the scraper's own scrape_bills() offline.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.metadata import lookup  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

from ms.bills import MSBillScraper, author_name_and_chamber  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ms_open808")

ALLMSRS = b"""<?xml version="1.0" encoding="ISO-8859-1"?>
<LASTACTION><MSRGROUP><MEASURE>%s</MEASURE><MEASURELINK>x</MEASURELINK>
<ACTIONLINK>../history/x.xml</ACTIONLINK></MSRGROUP></LASTACTION>"""


class FakeResponse:
    def __init__(self, content):
        self.content = content


def scrape_bill(monkeypatch, measure, chamber, fixtures=FIXTURES):
    """The Bill scrape_bills() makes from one real history XML (its roll calls are not read)."""
    scraper = MSBillScraper.__new__(MSBillScraper)
    history = open(os.path.join(fixtures, measure + "_2026_history.xml"), "rb").read()

    def get(url, verify=False):
        if "all_measures" in url:
            return FakeResponse(ALLMSRS % measure.encode())
        return FakeResponse(history)

    monkeypatch.setattr(scraper, "get", get, raising=False)
    monkeypatch.setattr(
        scraper, "scrape_votes", lambda *a, **k: iter(()), raising=False
    )
    (bill,) = [o for o in scraper.scrape_bills(chamber, "2026") if isinstance(o, Bill)]
    return bill


def sponsors(monkeypatch, measure, chamber):
    """(name, primary, pseudo id) of each author of one real bill, as scrape_bills() makes them."""
    bill = scrape_bill(monkeypatch, measure, chamber)
    return [
        (s["name"], s["primary"], get_pseudo_id(s["person_id"]))
        for s in bill.sponsorships
    ]


@pytest.mark.parametrize(
    "measure,chamber,expected",
    [
        # a district-qualified principal author: the whole printed name, not its first word
        (
            "SB2204",
            "upper",
            [("Simmons (12th)", True, {"name": "Simmons (12th)", "chamber": "upper"})],
        ),
        # a two-word surname, which the first word alone did not match
        (
            "SB2542",
            "upper",
            [("Gillespie Isom", True, {"name": "Gillespie Isom", "chamber": "upper"})],
        ),
        # a bare surname in the Senate, co-authors with their chamber
        (
            "SB2001",
            "upper",
            [
                ("DeBar", True, {"name": "DeBar", "chamber": "upper"}),
                ("Hopson", False, {"name": "Hopson", "chamber": "upper"}),
                ("Boyd", False, {"name": "Boyd", "chamber": "upper"}),
                ("Barnett", False, {"name": "Barnett", "chamber": "upper"}),
            ],
        ),
        # a district-qualified House co-author
        (
            "HB1938",
            "lower",
            [
                ("Oliver", True, {"name": "Oliver", "chamber": "lower"}),
                ("Read", False, {"name": "Read", "chamber": "lower"}),
                ("Arnold", False, {"name": "Arnold", "chamber": "lower"}),
                ("Boyd (19th)", False, {"name": "Boyd (19th)", "chamber": "lower"}),
            ],
        ),
        # "Hines *": filed by request ("By: Representative Hines (By Request)" on the bill)
        ("HB1595", "lower", [("Hines", True, {"name": "Hines", "chamber": "lower"})]),
    ],
)
def test_real_authors_keep_name_and_chamber(monkeypatch, measure, chamber, expected):
    got = sponsors(monkeypatch, measure, chamber)
    # SB 2001 and HB 1938 have more co-authors than the ones listed; the listed ones lead
    assert got[: len(expected)] == expected


@pytest.mark.parametrize(
    "name,link,expected",
    [
        # synthetic names: the rule is the printed form, not any member
        ("Zed (7th)", "../../House_authors/Zed_(7th).xml", ("Zed (7th)", "lower")),
        ("Zed  Ober ", "../../Senate_authors/Zed_Ober.xml", ("Zed Ober", "upper")),
        ("Zed *", "../../Senate_authors/Zed.xml", ("Zed", "upper")),
        ("Zed (7th) *", "../../House_authors/Zed_(7th).xml", ("Zed (7th)", "lower")),
        ("Zed*", "../../House_authors/Zed.xml", ("Zed", "lower")),
        ("SOME OFFICE", "", ("SOME OFFICE", None)),
        ("Zed", "../../Joint_authors/Zed.xml", ("Zed", None)),
    ],
)
def test_author_name_and_chamber(name, link, expected):
    assert author_name_and_chamber(name, link) == expected


@pytest.mark.parametrize(
    "measure,chamber,page",
    [
        ("SB2001", "upper", "Senate_authors/Boyd.xml"),
        ("HB1938", "lower", "House_authors/Boyd_(19th).xml"),
    ],
)
def test_co_author_source_is_their_own_page(monkeypatch, measure, chamber, page):
    sources = [s["url"] for s in scrape_bill(monkeypatch, measure, chamber).sources]
    assert "http://billstatus.ls.state.ms.us/2026/pdf/" + page in sources


# OPEN-828: on a nomination the legislature prints the appointing office as the author, with no
# member page. The fixtures under ms_open828 are real 2026 nomination histories, read 2026-11-23
# (SN 50 and SN 101 by the Governor, SN 1 by the Lieutenant Governor, SN 110 by the Attorney
# General); SN 10 (the Governor) is the OPEN-808 fixture.
FIXTURES_828 = os.path.join(os.path.dirname(__file__), "fixtures", "ms_open828")


def sponsor_entities(monkeypatch, measure, fixtures):
    """(name, entity type, primary, pseudo id) of each author of one real nomination."""
    bill = scrape_bill(monkeypatch, measure, "upper", fixtures)
    return [
        (
            s["name"],
            s["entity_type"],
            s["primary"],
            get_pseudo_id(s["person_id"] or s["organization_id"]),
        )
        for s in bill.sponsorships
    ]


@pytest.mark.parametrize(
    "measure,fixtures",
    [("SN10", FIXTURES), ("SN50", FIXTURES_828), ("SN101", FIXTURES_828)],
)
def test_governor_nomination_is_sponsored_by_the_executive(
    monkeypatch, measure, fixtures
):
    # the name core resolves is Mississippi's executive organization as core's metadata names it
    executive = lookup(abbr="ms").executive_name
    assert sponsor_entities(monkeypatch, measure, fixtures) == [
        (executive, "organization", True, {"name": executive})
    ]


@pytest.mark.parametrize(
    "measure,office",
    [("SN1", "LT. GOVERNOR"), ("SN110", "ATTORNEY GENERAL")],
)
def test_other_appointing_offices_stay_as_printed(monkeypatch, measure, office):
    # no organization for these offices in core: unchanged from OPEN-808
    assert sponsor_entities(monkeypatch, measure, FIXTURES_828) == [
        (office, "person", True, {"name": office})
    ]
