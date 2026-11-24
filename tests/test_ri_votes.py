"""Tests for OPEN-683: Rhode Island's roll calls are classified from the motion lines of their header.

Every header below is a real roll call from the Senate and House vote reports
(webserver.rilegislature.gov/SVotes|HVotes/votereport.asp, 2025 and 2026, read 2026-11-20): the lines
of the report's <pre> header, as the scraper reads them. The motion is the motion lines at the end
joined with " / "; a budget article's vote keeps its article; a header with no motion line ends in
the title, as before, except a calendar item (OPEN-873: its motion is the marker, "CALENDAR").
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
from ri.bills import RIBillScraper, vote_classification, vote_motion  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ri_open683")

REAL_HEADERS = [
    # House 5/28/2026 (id 22600): a House bill passed
    (
        [
            "CALENDAR",
            "ITEM 4              2026-H 7115",
            "McNamara         Education",
            "HEALTH AND SAFETY OF PUPILS",
            "PASSAGE",
        ],
        "PASSAGE",
        ["passage"],
    ),
    # House 6/5/2026 (id 22723): the whole budget, after its articles
    (
        [
            "CALENDAR",
            "ITEM 1         2026-H 7127 SUB A",
            "Abney            Finance",
            "APP. FY ENDING JUNE 30, 2027",
            "PASSAGE",
            "AS AMENDED",
        ],
        "PASSAGE / AS AMENDED",
        ["passage"],
    ),
    # House 6/11/2026 (id 23006): consent calendar: a Senate bill passed in concurrence
    (
        [
            "CONSENT CALENDAR",
            "ITEM 1              2026-S 2824",
            "LaMountain       Ordered on Cal",
            "CRIMINAL INJURIES COMPENSATION",
            "PASSAGE",
            "IN CONCURRENCE",
        ],
        "PASSAGE / IN CONCURRENCE",
        ["passage"],
    ),
    # House 6/20/2025 (id 22189): consent calendar, passed in concurrence
    (
        [
            "CONSENT CALENDAR",
            "ITEM 15         2025-S 672 SUB A",
            "Bissaillon       Ordered on Cal",
            "ARCHITECTS",
            "PASSAGE",
            "IN CONCURRENCE",
        ],
        "PASSAGE / IN CONCURRENCE",
        ["passage"],
    ),
    # House 6/18/2025 (id 22166): passed in concurrence as amended
    (
        [
            "CALENDAR",
            "ITEM 92              2025-S 679",
            "Bissaillon       Ordered on Cal",
            "FORESTRY AND FOREST PARITY ACT",
            "PASSAGE",
            "IN CONCURRENCE",
            "AS AMENDED",
        ],
        "PASSAGE / IN CONCURRENCE / AS AMENDED",
        ["passage"],
    ),
    # Senate 6/20/2025 (id 17103): S 359 passed after three amendment votes
    (
        [
            "CALENDAR",
            "ITEM 1          2025-S 359 SUB A",
            "CRIMINAL OFFENSES -- UNLAWFUL",
            "SALE OF PROHIBITED FIREARMS",
            "Passage",
        ],
        "Passage",
        ["passage"],
    ),
    # Senate 6/11/2026 (id 17923): passage as amended, right after the amendment vote 17922
    (
        [
            "CALENDAR",
            "ITEM 7              2026-S 3334",
            "HEALTH AND SAFETY--RHODE ISLAND",
            "LIFE SCIENCE HUB ACT",
            "Passage as Amended",
            "Passage",
        ],
        "Passage as Amended / Passage",
        ["passage"],
    ),
    # Senate 6/11/2026 (id 17954): a House bill passed in concurrence
    (
        [
            "CALENDAR",
            "ITEM 33        2026-H 8005 SUB A",
            "RELATING TO TOWNS AND CITIES --",
            "ZONING ORDINANCES",
            "In Concurrence",
        ],
        "In Concurrence",
        ["passage"],
    ),
    # Senate 6/20/2025 (id 17252): a House bill passed in concurrence
    (
        [
            "CALENDAR",
            "ITEM 20        2025-H 5130 SUB A",
            "RELATING TO CRIMINAL OFFENSES",
            "-- WEAPONS",
            "In Concurrence",
            "Passage",
        ],
        "In Concurrence / Passage",
        ["passage"],
    ),
    # Senate 6/5/2025 (id 16903): the re-vote on passage after S 981 was reconsidered
    (
        [
            "RECONSIDERATION 2025-S 981 SUB A",
            "ZURIER            HOUSING & MUN.",
            "RELATING TO STATE AFFAIRS/GOV.",
            "--ENERGY FACILITY SITING ACT",
            "Passage as Amended",
        ],
        "Passage as Amended",
        ["passage"],
    ),
    # House 6/3/2025 (id 21773): an amendment roll call
    (
        [
            "CALENDAR",
            "ITEM 19        2025-H 6235 SUB A",
            "Serpa            State Gov. & El",
            "COMMITTEES AND STAFF",
            "PASSAGE",
            "PASSAGE OF AMENDMENT",
        ],
        "PASSAGE / PASSAGE OF AMENDMENT",
        ["amendment"],
    ),
    # House 6/18/2025 (id 22165): an amendment to a Senate bill being passed in concurrence
    (
        [
            "CALENDAR",
            "ITEM 92              2025-S 679",
            "Bissaillon       Ordered on Cal",
            "FORESTRY AND FOREST PARITY ACT",
            "PASSAGE",
            "IN CONCURRENCE",
            "PASSAGE OF AMENDMENT",
        ],
        "PASSAGE / IN CONCURRENCE / PASSAGE OF AMENDMENT",
        ["amendment"],
    ),
    # Senate 6/20/2025 (id 17100): an amendment roll call
    (
        [
            "CALENDAR",
            "ITEM 1          2025-S 359 SUB A",
            "CRIMINAL OFFENSES -- UNLAWFUL",
            "SALE OF PROHIBITED FIREARMS",
            "Approval of Amendment",
        ],
        "Approval of Amendment",
        ["amendment"],
    ),
    # Senate 6/11/2026 (id 17922): the amendment vote keeps "Passage" under it; 17923 is the passage
    (
        [
            "CALENDAR",
            "ITEM 7              2026-S 3334",
            "HEALTH AND SAFETY--RHODE ISLAND",
            "LIFE SCIENCE HUB ACT",
            "Approval of Amendment",
            "Passage",
        ],
        "Approval of Amendment / Passage",
        ["amendment"],
    ),
    # House 6/5/2026 (id 22694): a budget article's amendment
    (
        [
            "CALENDAR",
            "ITEM 1         2026-H 7127 SUB A",
            "Abney            Finance",
            "ARTICLE 3",
            "PASSAGE",
            "PASSAGE OF AMENDMENT",
        ],
        "ARTICLE 3 PASSAGE / PASSAGE OF AMENDMENT",
        ["amendment"],
    ),
    # House 6/5/2026 (id 22697): a budget article adopted as amended: not the whole bill
    (
        [
            "CALENDAR",
            "ITEM 1         2026-H 7127 SUB A",
            "Abney            Finance",
            "ARTICLE 3",
            "PASSAGE",
            "AS AMENDED",
        ],
        "ARTICLE 3 PASSAGE / AS AMENDED",
        [],
    ),
    # House 6/5/2026 (id 22693): a budget article adopted: not the whole bill
    (
        [
            "CALENDAR",
            "ITEM 1         2026-H 7127 SUB A",
            "Abney            Finance",
            "ARTICLE 2",
            "PASSAGE",
        ],
        "ARTICLE 2 PASSAGE",
        [],
    ),
    # House 6/20/2025 (id 22296): a motion to reconsider
    (
        [
            "CALENDAR",
            "ITEM 53             2025-H 5448",
            "McEntee          Ordered on the",
            "EMPLOYMENT SEC.- GEN. PROVISIONS",
            "PASSAGE",
            "AS AMENDED",
            "RECONSIDERATION",
        ],
        "PASSAGE / AS AMENDED / RECONSIDERATION",
        [],
    ),
    # House 5/12/2026 (id 22558): an appeal of the chair's ruling
    (
        [
            "CALENDAR",
            "ITEM 6              2026-H 7551",
            "Kennedy          Judiciary",
            "FRAUD AND FALSE DEALING",
            "PASSAGE",
            "AS AMENDED",
            "RULING OF THE CHAIR",
        ],
        "PASSAGE / AS AMENDED / RULING OF THE CHAIR",
        [],
    ),
    # Senate 6/20/2025 (id 17099): a point of order: no motion line, the text ends in the title
    (
        [
            "POINT of ORDER",
            "ITEM 1          2025-S 359 SUB A",
            "CRIMINAL OFFENSES -- UNLAWFUL",
            "SALE OF PROHIBITED FIREARMS",
        ],
        "SALE OF PROHIBITED FIREARMS",
        [],
    ),
    # House 1/20/2026 (id 22382): an immediate-consideration item with no motion line is the item
    # read and passed (OPEN-873): its motion is the marker
    (
        ["IMMEDIATE CONSIDERATION", "ITEM 1                26-H 7165"],
        "IMMEDIATE CONSIDERATION",
        ["passage"],
    ),
]


@pytest.mark.parametrize("headers,motion,expected", REAL_HEADERS)
def test_real_roll_calls(headers, motion, expected):
    assert vote_motion(headers) == motion
    assert vote_classification(motion) == expected


def test_shared_rules_only_decide_passage():
    assert classify_motion("ri", "Approval of Amendment / Passage") == []
    assert classify_motion("ri", "PASSAGE / PASSAGE OF AMENDMENT") == []
    assert classify_motion("ri", "PASSAGE / IN CONCURRENCE") == ["passage"]


@pytest.mark.parametrize(
    "motion",
    [
        # An unseen line must never default to passage. No veto-override or conference-report
        # roll call appears in 2025-2026 (2,948 headers), so none is ruled on here: one would
        # stay unlabelled until its real text is seen.
        "PASSAGE OF THE RESOLUTION",
        "PASSAGE / POSTPONED",
        "RELATING TO PASSAGE",  # a title fragment that contains the word
        "",
    ],
)
def test_unseen_text_stays_unclassified(motion):
    assert vote_classification(motion) == []


def _scraper_votes(name, session):
    html = open(os.path.join(FIXTURES, name), encoding="utf-8").read()
    scraper = object.__new__(RIBillScraper)
    scraper.warning = lambda *a, **k: None
    scraper.get = lambda url: types.SimpleNamespace(text=html)
    return list(scraper.get_votes("https://example/" + name, session).values())


@pytest.mark.parametrize(
    "name,session,motion,expected",
    [
        (
            "H_22694.html",
            "2026",
            "ARTICLE 3 PASSAGE / PASSAGE OF AMENDMENT",
            ["amendment"],
        ),
        ("H_22697.html", "2026", "ARTICLE 3 PASSAGE / AS AMENDED", []),
        ("S_17922.html", "2026", "Approval of Amendment / Passage", ["amendment"]),
        ("S_17923.html", "2026", "Passage as Amended / Passage", ["passage"]),
        ("S_17099.html", "2025", "SALE OF PROHIBITED FIREARMS", []),
    ],
)
def test_real_vote_reports(name, session, motion, expected):
    (vote,) = _scraper_votes(name, session)
    assert vote["meta"]["extra"]["motion"] == motion
    assert vote_classification(vote["meta"]["extra"]["motion"]) == expected
    assert len(vote["votes"]) > 30


def test_scraper_no_longer_hard_codes_passage():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "scrapers", "ri", "bills.py")
    ).read()
    assert 'classification="passage"' not in src
    assert "classification=vote_classification(" in src
