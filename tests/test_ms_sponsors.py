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


def sponsors(monkeypatch, measure, chamber):
    """(name, primary, pseudo id) of each author of one real bill, as scrape_bills() makes them."""
    scraper = MSBillScraper.__new__(MSBillScraper)
    history = open(os.path.join(FIXTURES, measure + "_2026_history.xml"), "rb").read()

    def get(url, verify=False):
        if "all_measures" in url:
            return FakeResponse(ALLMSRS % measure.encode())
        return FakeResponse(history)

    monkeypatch.setattr(scraper, "get", get, raising=False)
    monkeypatch.setattr(
        scraper, "scrape_votes", lambda *a, **k: iter(()), raising=False
    )
    (bill,) = [o for o in scraper.scrape_bills(chamber, "2026") if isinstance(o, Bill)]
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
        # a nomination: the appointing authority has no member page, so no chamber (as before)
        ("SN10", "upper", [("GOVERNOR", True, {"name": "GOVERNOR"})]),
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
