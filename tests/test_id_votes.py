"""Tests for OPEN-682: Idaho's roll calls are classified from their motion text, not hard-coded "passage".

Every motion below is a real roll call from legislature.idaho.gov bill pages (read 2026-11-20), written
the way the id scraper builds it: the text in front of the tally, with hyphens removed. A bill page
carries only the votes on the bill itself: a third reading, the same reading under suspended rules,
the origin chamber's vote on the other chamber's amendments, a concurrent resolution's adoption, and
a veto override.
"""
import os
import sys
import types
from collections import defaultdict

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
from id.bills import IDBillScraper  # noqa: E402

from openstates.scrape import VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

REAL_ROLL_CALLS = [
    # the probe sample's 13 roll calls (2026 S 1221, 1222, 1224-1227): third readings
    "Read third time in full –",
    "Read Third Time in Full –",
    "Read third time in full as amended –",
    "Read third time in full as amended in House –",
    "Read third time as amended in the House –",
    # 2025 H 6, Senate: the House's vote on the Senate's amendments (concurrence = passage)
    "Read third time as amended in the Senate –",
    # 2025 H 13, House
    "Read third time in full as amended in Senate –",
    # 2025 S 1071, House 23-44: a lost third reading is a lost passage vote
    "Read third time in full as amended in House –",
    # 2025 H 96, House: the reading under suspended rules, passed 54-13-3 the same day
    "Rules Suspended: Ayes 68 Nays 0 Abs/Excd 2, read in full as required –",
    # 2025 H 130, Senate
    "Rules Suspended (2/3 Vote  Read in full as required) –",
    "Rules Suspended (2/3 Vote  Read in full as required) – Read third time in full –",  # 2025 S 1175
    "Read third time in full – Rules Suspended (2/3 Vote  Read in full as required) –",  # 2025 HJR 4
    "Read third time in full as amended – Rules Suspended (2/3 Vote  Read in full as required) –",  # 2025 S 1025, failed 6-28
    # 2025 HCR 3, SCR 102: a concurrent resolution adopted on the tenth order
    "Read in full –",
    # 2025 S 1023: a whole-bill veto override (failed, less than two-thirds) counts (Ramon, OPEN-677)
    "Senate vote to override veto",
    # 2026 H 760, Senate 03/25: the text-less tally ("FAILED - 15-20-0") under "Motion to reconsider - PASSED",
    # the re-vote on the third reading that tied 17-17 the day before; it killed the bill
    "Motion to reconsider  PASSED",
]


@pytest.mark.parametrize("motion", REAL_ROLL_CALLS)
def test_real_roll_calls_are_passage(motion):
    assert classify_motion("id", motion) == ["passage"]


@pytest.mark.parametrize(
    "motion",
    [
        "House vote to override line item veto",  # not seen; a line-item override is not passage
        "Senate vote to override veto of line item",
        "Read second time; Filed for Third Reading",  # an action row with no vote on the bill
        "Reported Printed; Filed for Second Reading",
        "Motion to send to Gen Ord, motion failed",
        "Motion to reconsider –",  # a roll call on the reconsider motion itself is procedural
        "Motion to reconsider  FAILED",
        "PASSED  6163",
        "",
    ],
)
def test_other_texts_stay_unclassified(motion):
    assert classify_motion("id", motion) == []


@pytest.fixture
def scraper(tmp_path, monkeypatch):
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text("id: {}\n")
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    return IDBillScraper.__new__(IDBillScraper)


def test_veto_override_row_end_to_end(scraper):
    path = os.path.join(
        FIXTURES, "id_open682", "s1023_2025_senate_veto_override_row.html"
    )
    row = lxml.html.fromstring(open(path, encoding="utf-8").read()).xpath("//tr")[0]
    (vote,) = scraper.parse_vote(
        "upper", "2025-04-03", row[2], "2025", "S 1023", "upper", "https://x"
    )
    assert vote.motion_text == "Senate vote to override veto"
    assert vote.motion_classification == ["passage"]
    assert vote.result == "fail"


def test_tally_row_without_text_takes_the_reading_above_it(scraper):
    """2025 H 231, House 02/14: "PASSED - 61-6-3" is printed on its own row, under
    "Rules Suspended: Ayes 62 Nays 6 Abs/Excd 2, read in full as required – ..." (it used to be
    stored with the motion "passage")."""
    page = open(
        os.path.join(FIXTURES, "id_open682", "h0231_2025.html"), encoding="utf-8"
    ).read()
    scraper._subjects = defaultdict(list)
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(text=page)
    votes = [
        v
        for v in scraper.scrape_bill("lower", "2025", "H 231")
        if isinstance(v, VoteEvent)
    ]
    house = [v for v in votes if v.start_date == "2025-02-14"]
    assert len(house) == 1
    assert house[0].motion_text.startswith(
        "Rules Suspended: Ayes 62 Nays 6 Abs/Excd 2, read in full as required"
    )
    assert house[0].motion_classification == ["passage"]
    assert all(v.motion_classification == ["passage"] for v in votes)


def test_tally_row_takes_only_the_row_directly_above(scraper):
    """An empty separator row between the action and the text-less tally breaks the link."""
    page = open(
        os.path.join(FIXTURES, "id_open682", "h0231_2025.html"), encoding="utf-8"
    ).read()
    tally = "PASSED&#160;-&#160;61-6-3"
    assert page.count(tally) == 1
    start = page.rindex("<tr", 0, page.index(tally))
    page = page[:start] + "<tr><td></td></tr>" + page[start:]
    scraper._subjects = defaultdict(list)
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(text=page)
    (house,) = [
        v
        for v in scraper.scrape_bill("lower", "2025", "H 231")
        if isinstance(v, VoteEvent) and v.start_date == "2025-02-14"
    ]
    assert house.motion_text == "PASSED - 61-6-3"
    assert house.motion_classification == []


def test_tally_row_with_nothing_above_stays_unclassified(scraper):
    row = lxml.html.fromstring(
        "<table><tr><td></td><td></td><td> <span>PASSED&#160;-&#160;61-6-3</span><br>"
        "<span>AYES</span>&#160;&#8211;&#160;Achilles</td><td></td></tr></table>"
    ).xpath("//tr")[0]
    (vote,) = scraper.parse_vote(
        "lower", "2025-02-14", row[2], "2025", "H 231", "lower", "https://x"
    )
    assert vote.motion_text == "PASSED - 61-6-3"
    assert vote.motion_classification == []


def test_scraper_no_longer_hard_codes_passage():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "scrapers", "id", "bills.py")
    ).read()
    assert 'classification="passage"' not in src
    assert 'else "passage"' not in src
    assert 'classification=classify_motion("id", motion)' in src
