"""OPEN-689: Kentucky roll calls are classified from their motion text instead of a hard-coded "passage".

Every motion below is a real roll call from apps.legislature.ky.gov vote_history.pdf files (2025RS and 2026RS, read
2026-11-20), as the scraper builds it: the page's motion line, plus on a House page the amendment its roll-call line
names ("HB 1 HFA 8  RCS# 6" + "Adopt" -> "Adopt HFA 8"). The fixtures in fixtures/ky_open689 are four of those PDFs:
2026RS HB 500 (budget bill, line-item vetoes overridden), 2025RS HB 4 (whole-bill veto overridden, House and Senate
amendment votes), 2025RS HJR 15 and 2026RS SJR 23 (joint resolutions adopted in one chamber, passed in the other).
"""
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from classify_motion import classify_motion  # noqa: E402
from ky.bills import KYBillScraper, roll_call_part, vote_classification  # noqa: E402

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures", "ky_open689")

PASSAGE, AMENDMENT, NONE = ["passage"], ["amendment"], []

REAL_ROLL_CALLS = [
    # third reading, House and Senate (passed or lost: 2025 HR 7 "Adopt" failed 20-75 and is still the vote on it)
    ("Pass", PASSAGE),  # 2025 HB 1, House RCS# 7, 90-7
    ("PASS HB 1", PASSAGE),  # 2025 HB 1, Senate, 34-3
    ("PASS HB 15 W/ scs1", PASSAGE),  # 2025 HB 15, Senate
    ("PASS HB 4 W/ sfta 19", PASSAGE),  # 2025 HB 4, Senate, with a title amendment
    ("PASS SB 3 w/ SCA 1, SFA 2", PASSAGE),  # 2026 SB 3, Senate
    ("PASS HB 6 w/ SFA 2, SFA 1", PASSAGE),  # 2026 HB 6, Senate
    ("PASS SB 71 w/ scs1 sfa1", PASSAGE),  # 2025 SB 71, Senate, 21-11
    ("PASS HJR 15", PASSAGE),  # 2025 HJR 15, Senate
    (
        "CONSENT PASSAGE OF HB 265 w/ SCS 1",
        PASSAGE,
    ),  # 2026 HB 265, Senate consent calendar
    ("CONSENT PASSAGE OF HB 506", PASSAGE),  # 2026 HB 506, Senate consent calendar
    # the origin chamber's vote after concurring in the other chamber's changes or adopting a (free) conference report
    (
        "Final Passage",
        PASSAGE,
    ),  # 2025 HB 15, House, after the Senate's committee substitute
    (
        "Final Passage SB 100 W/ hcs1",
        PASSAGE,
    ),  # 2025 SB 100, Senate, after the House committee substitute
    ("FINAL PASSAGE OF SB 1 w/ HFA 2", PASSAGE),  # 2026 SB 1, Senate
    ("FINAL PASSAGE OF SB 30 w/ HFA 1, HFA 2 (T)", PASSAGE),  # 2026 SB 30, Senate, 35-1
    (
        "FINAL PASSAGE OF HB 500",
        PASSAGE,
    ),  # 2026 HB 500, Senate, after the free conference report
    # whole-bill veto overrides (the bill's history says "Vetoed")
    ("Override Veto Final Passage HB 2", PASSAGE),  # 2025 HB 2, Senate
    ("OVERRIDE VETO FINAL PASSAGE SB 1", PASSAGE),  # 2026 SB 1, Senate
    ("Veto Override", PASSAGE),  # 2026 SB 1, House
    # a resolution adopted on its own roll call
    ("Adopt", PASSAGE),  # 2025 HCR 20 (90-0), HJR 5, HJR 15 (79-13), House
    ("ADOPT SCR 9", PASSAGE),  # 2026 SCR 9, Senate
    ("ADOPT SJR 23 w/ SCS 1", PASSAGE),  # 2026 SJR 23, Senate
    # amendment votes
    ("Adopt HFA 8", AMENDMENT),  # 2025 HB 1, House RCS# 6, 20-77
    ("Adopt HFA 3", AMENDMENT),  # 2025 SB 25, House, 65-19
    ("Adopt HCS 1", AMENDMENT),  # 2025 SB 19, House, 67-20
    (
        "HFA 1",
        AMENDMENT,
    ),  # 2025 HJR 15, House: a page with no motion line under "HJR 15 HFA 1"
    ("SFA 5", AMENDMENT),  # 2025 HB 4, Senate, 7-31
    ("SFA 8", AMENDMENT),  # 2025 HB 4, Senate, 6-32
    # procedural and other votes
    (
        "Suspend the Rules HFA 13",
        NONE,
    ),  # 2026 HB 500, House, to take up a floor amendment
    ("Suspend the Rules HFA 8", NONE),  # 2025 HB 18, House
    ("Previous Question", NONE),  # 2025 SB 2, House
    ("Reconsider", NONE),  # 2025 SB 65, House
    ("Table", NONE),  # 2026 HB 1, House
    (
        "Co-Sponsor",
        NONE,
    ),  # 2026 HR 21, House (the resolution itself was adopted by voice vote)
    (
        "Misc",
        NONE,
    ),  # 2026 HB 500 (74-18, then "Final Passage" 73-21) and SB 30 (60-2, after "Pass" 92-0), House
]


@pytest.mark.parametrize("motion,expected", REAL_ROLL_CALLS)
def test_real_roll_calls(motion, expected):
    assert vote_classification(motion) == expected


@pytest.mark.parametrize(
    "motion", ["Veto Override", "OVERRIDE VETO FINAL PASSAGE HB 500"]
)
def test_line_item_veto_override_is_not_passage(motion):
    # 2026 HB 500-504 and 2025 SB 25: "line items vetoed", then the same override texts as a whole-bill override
    assert vote_classification(motion, line_item_veto=True) == ["veto-override"]
    assert vote_classification(motion, line_item_veto=False) == PASSAGE


def test_amendment_votes_are_not_passage_in_the_shared_rules():
    for motion in ("Adopt HFA 8", "Adopt HCS 1", "SFA 5", "HFA 1"):
        assert classify_motion("ky", motion) == []


@pytest.mark.parametrize(
    "motion",
    [
        "Passed over",  # "pass" must be the whole first word
        "Adopt HFA 8 and pass",  # an amendment's adoption is not a resolution's
        "Adopt HCS 1",
        "Final Passaged",
        "Veto Override HFA 1",
        "ADOPT SFA 2",
    ],
)
def test_near_misses_are_not_passage(motion):
    assert classify_motion("ky", motion) == []


@pytest.mark.parametrize(
    "line,part",
    [  # real roll-call lines: 2025 HB 1, SB 19, HB 1, HB 4 (Senate), HCR 20
        (
            "HB 1 HFA 8                                                                     RCS# 6",
            "HFA 8",
        ),
        (
            "SB 19 HCS 1                                                                                             RCS# 257",
            "HCS 1",
        ),
        (
            "HB 1                          AN ACT relating to the individual income tax rate.     RCS# 7",
            None,
        ),
        (
            "HB 4                      AN ACT relating to postsecondary institutions.              RSN# 3501",
            None,
        ),
        (
            "HCR 20                       A CONCURRENT RESOLUTION directing the LRC to                            RCS# 40",
            None,
        ),
    ],
)
def test_roll_call_part(line, part):
    assert roll_call_part(line) == part


def scraped(pdf, bill_chamber, tmp_path, actions=()):
    # scrape_votes deletes the file it reads, so give it a copy
    copy = str(tmp_path / os.path.basename(pdf))
    shutil.copy(pdf, copy)
    scraper = KYBillScraper({"name": "Kentucky"}, str(tmp_path))
    scraper.urlretrieve = lambda url, verify=None: (copy, None)
    bill = Bill("X 1", legislative_session="2026RS", chamber=bill_chamber, title="t")
    for action in actions:
        bill.add_action(action, "2026-04-13", chamber="executive")
    return [
        (
            json.loads(ve.organization[1:])["classification"],
            ve.motion_text,
            ve.motion_classification,
        )
        for ve in scraper.scrape_votes("https://example.com/v.pdf", bill, bill_chamber)
    ]


def test_budget_bill_line_item_overrides(tmp_path):
    votes = scraped(
        os.path.join(FIXTURES, "26RS_hb500_vote_history.pdf"),
        "lower",
        tmp_path,
        actions=["delivered to Governor", "line items vetoed"],
    )
    assert votes == [
        ("lower", "Suspend the Rules HFA 13", []),
        ("lower", "Suspend the Rules HFA 12", []),
        ("lower", "Suspend the Rules HFA 14", []),
        ("lower", "Suspend the Rules HFA 11", []),
        ("lower", "Suspend the Rules HFA 10", []),
        ("lower", "Suspend the Rules HFA 9", []),
        ("lower", "Pass", ["passage"]),
        ("upper", "PASS HB 500 w/ SCS 1", ["passage"]),
        ("upper", "FINAL PASSAGE OF HB 500", ["passage"]),
        ("lower", "Misc", []),
        ("lower", "Final Passage", ["passage"]),
        ("lower", "Veto Override", ["veto-override"]),
        ("upper", "OVERRIDE VETO FINAL PASSAGE HB 500", ["veto-override"]),
    ]


def test_whole_bill_override_and_amendment_votes(tmp_path):
    votes = scraped(
        os.path.join(FIXTURES, "25RS_hb4_vote_history.pdf"),
        "lower",
        tmp_path,
        actions=["delivered to Governor", "Vetoed"],
    )
    assert votes == [
        ("lower", "Adopt HFA 1", ["amendment"]),
        ("lower", "Adopt HFA 6", ["amendment"]),
        ("lower", "Pass", ["passage"]),
        ("upper", "SFA 5", ["amendment"]),
        ("upper", "SFA 8", ["amendment"]),
        ("upper", "PASS HB 4 W/ sfta 19", ["passage"]),
        ("lower", "Final Passage", ["passage"]),
        ("lower", "Final Passage", ["passage"]),
        ("upper", "Override Veto Final Passage HB 4", ["passage"]),
    ]


def test_joint_resolutions(tmp_path):
    assert scraped(
        os.path.join(FIXTURES, "25RS_hjr15_vote_history.pdf"), "lower", tmp_path
    ) == [
        ("lower", "HFA 1", ["amendment"]),
        ("lower", "Adopt", ["passage"]),
        ("upper", "PASS HJR 15", ["passage"]),
    ]
    assert scraped(
        os.path.join(FIXTURES, "26RS_sjr23_vote_history.pdf"), "upper", tmp_path
    ) == [
        ("upper", "ADOPT SJR 23 w/ SCS 1", ["passage"]),
        ("lower", "Suspend the Rules HFA 1", []),
        ("lower", "Adopt", ["passage"]),
        ("upper", "FINAL PASSAGE OF SJR 23 w/ HFA 1", ["passage"]),
    ]


def test_no_hard_coded_passage_on_votes():
    source = open(os.path.join(HERE, "..", "scrapers", "ky", "bills.py")).read()
    assert 'classification="passage"' not in source
