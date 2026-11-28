"""Tests for OPEN-952: a Montana roll call's result is the outcome its bill action states, not yeas > nays.

Some Montana bills need more than a majority (2025 HB 316, a constitutional amendment: 33-17 in the Senate is short of
two thirds). The legislature records that vote as lost, "(S) 3rd Reading Failed; 2nd House Vote Required", and the
scraper stored it as passed because 33 > 17. Five bills of 2025 had such a first vote (HB316, HB821, HB822, HB921,
SB185; all five died in process, none had a second vote), and two lost "(H) Motion Failed" motions to take a bill
from committee (HB552 51-47, HB640 50-48; they need 60 votes) were stored as passed too.

The action texts and tallies are the 2025 session's own, read from the legislature's saved data (govbot-history/
mt-legislation-data, 2026-11-27): the roll call's tally with the action line of the same chamber and day.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from mt.bills import MTBillScraper, vote_result  # noqa: E402
from test_mt_action_outcomes import OfflineScraper, bill_row  # noqa: E402

P, N = ["passage"], []

# (classification, the action line, yeas, nays, result): every row is a real 2025 roll call
REAL_2025 = [
    # a first vote that fell short and needs a second one: lost, whatever the tally
    (P, "(S) 3rd Reading Failed; 2nd House Vote Required", 33, 17, "fail"),  # HB316
    (
        P,
        "(S) 3rd Reading Failed; 2nd House Vote Required",
        30,
        19,
        "fail",
    ),  # HB821, HB822
    (P, "(H) 3rd Reading Failed; 2nd House Vote Required", 56, 44, "fail"),  # HB921
    (P, "(H) 3rd Reading Failed; 2nd House Vote Required", 58, 40, "fail"),  # SB185
    # the bills API's name for the same vote carries no outcome word
    (P, "(S) 3rd Reading; 2nd Chamber Vote Required", 33, 17, "fail"),  # HB316
    (P, "(H) 3rd Reading; 2nd Chamber Vote Required", 56, 44, "fail"),  # HB921
    # a bill that passed and a bill that failed on a plain majority keep their result
    (P, "(H) 3rd Reading Passed", 56, 43, "pass"),  # HB557
    (P, "(S) 3rd Reading Failed", 24, 26, "fail"),  # HB557
    (P, "(S) 3rd Reading Failed", 25, 25, "fail"),  # HB827, a tie
    (P, "(S) 3rd Reading Passed as Amended by House", 29, 21, "pass"),
    (P, "(H) 3rd Reading Concurred", 49, 48, "pass"),  # SB535, after a reconsideration
    (P, "(H) 3rd Reading Not Passed as Amended by Senate", 40, 60, "fail"),
    (P, "(H) 3rd Reading Conference Committee Report Rejected", 30, 70, "fail"),
    # an outcome word beats the tally in the other direction too
    (P, "(S) 3rd Reading Passed", 20, 30, "pass"),
    # a motion to take a bill from committee that lost a 60-vote threshold on a majority
    (N, "(H) Motion Failed", 51, 47, "fail"),  # HB552
    (N, "(H) Motion Failed", 50, 48, "fail"),  # HB640
    (N, "(H) Motion Carried", 60, 40, "pass"),
    # every other roll call keeps yeas > nays: a motion's own result, not the action's
    (["amendment"], "(H) 2nd Reading Motion to Amend Carried", 58, 40, "pass"),
    (
        N,
        "(H) 2nd Reading Senate Amendments Not Concurred",
        58,
        42,
        "pass",
    ),  # "Do Not Concur" carried
    (N, "(H) 2nd Reading Not Passed", 100, 0, "pass"),  # HB933, "Do Not Pass" carried
    (N, "(S) 2nd Reading", 22, 27, "fail"),
    # no action text, or no outcome in it: yeas > nays
    (P, None, 30, 20, "pass"),
    (P, "", 20, 30, "fail"),
    (P, "(H) 3rd Reading", 51, 49, "pass"),
    (P, "(H) 3rd Reading", 49, 51, "fail"),
]


@pytest.mark.parametrize("classification,text,yes,no,expected", REAL_2025)
def test_result_from_the_stated_outcome(classification, text, yes, no, expected):
    assert vote_result(classification, text, yes, no) == expected


def test_a_stated_outcome_beats_the_second_vote_required_suffix():
    # a first vote the bills API did record as passed is not a failure because of the suffix
    assert (
        vote_result(P, "(S) 3rd Reading; 2nd Chamber Vote Required Passed", 40, 10)
        == "pass"
    )


def _live_results(slug, folder="mt_open694"):
    """The bills API path: scrape_actions fills the lookups, scrape_votes reads the roll calls."""
    scraper = OfflineScraper(folder, slug)
    bill = Bill(slug, legislative_session="2025", chamber="lower", title="t")
    bill.add_source("https://bills.legmt.gov/")
    scraper.scrape_actions(bill, bill_row(folder, slug))
    return [
        (v.bill_action, v.motion_classification, v.result)
        for v in scraper.scrape_votes(bill, "1")
    ]


def test_real_hb316_senate_vote_is_fail_through_the_scraper():
    rows = _live_results("HB316")
    assert rows == [
        ("(H) 2nd Reading", N, "pass"),
        ("(H) 3rd Reading", P, "pass"),
        ("(S) 2nd Reading", N, "pass"),
        ("(S) 3rd Reading; 2nd Chamber Vote Required", P, "fail"),
    ]


def test_a_lost_third_reading_stays_fail_through_the_scraper():
    # 2025 HB 500 (lost twice) and SB 158 (lost on a plain majority): the API's own BILL_NOT_PASSED row and the
    # tally agree, and the result is unchanged
    def third(slug):
        return [r for r in _live_results(slug, "mt_open851") if r[1] == P]

    assert third("HB500") == [("(H) 3rd Reading", P, "fail")] * 2
    assert third("SB158") == [("(S) 3rd Reading", P, "fail")]


def test_archive_path_uses_the_action_text():
    # the archive API's own 2025-style row: the action text and the tally (HB 921's lost House vote, 56-44)
    scraper = MTBillScraper.__new__(MTBillScraper)
    bill = Bill("HB 921", legislative_session="2023", chamber="lower", title="t")
    bill.add_source("https://bills.legmt.gov/")
    row = {
        "billActions": [
            _archive_action("(H) 3rd Reading Failed; 2nd House Vote Required", 56, 44),
            _archive_action("(H) 3rd Reading Passed", 54, 44, seq=2),
            _archive_action("(S) 2nd Reading", 31, 19, seq=3),
        ]
    }
    results = [
        (v.motion_text, v.result) for v in scraper.scrape_archive_actions(bill, row)
    ]
    assert results == [
        ("(H) 3rd Reading Failed; 2nd House Vote Required", "fail"),
        ("(H) 3rd Reading Passed", "pass"),
        ("(S) 2nd Reading", "pass"),
    ]


def _archive_action(name, yes, no, seq=1):
    return {
        "actionType": {"description": name},
        "date": "2025-04-28T17:10:00",
        "yesVotes": yes,
        "noVotes": no,
        "voteSeq": seq,
    }
