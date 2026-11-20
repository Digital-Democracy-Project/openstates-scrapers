"""Tests for OPEN-684: a Wyoming roll call's result is the outcome its text states, else the threshold it needs.

The texts and counts in REAL_RESULTS are real 2026 roll calls: from the 2026 probe sample (107 roll calls) and
lsoservice.wyoleg.gov/api/BillInformation/2026/<bill> (fetched 2026-11-20). The API has no outcome field.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper, vote_result  # noqa: E402

# (chamber that voted, motion as stored, yeas, nays, result)
REAL_RESULTS = [
    # The ticket's three: the House did not override, though yeas beat nays (and 41 is two thirds of the 60 voting).
    ("H", "SF0001VT002: Did Not Override Line Item Veto 34-26-1-1-0", 34, 26, "fail"),
    ("H", "SF0001VT003: Did Not Override Line Item Veto 34-26-1-1-0", 34, 26, "fail"),
    ("H", "SF0001VT007: Did Not Override Line Item Veto 41-19-1-1-0", 41, 19, "fail"),
    # Overrides that state no outcome: two thirds of 31 / 62.
    ("S", "SF0001VT001: Line Item Veto Override 23-6-2-0-0", 23, 6, "pass"),
    ("S", "SF0001VT007: Line Item Veto Override 24-5-2-0-0", 24, 5, "pass"),
    ("H", "SF0001VT004: Line Item Veto Override 57-3-1-1-0", 57, 3, "pass"),
    # HB 20: a budget-session introduction failed although yeas beat nays (it needs two thirds).
    ("H", "H Failed Introduction 34-28-0-0-0", 34, 28, "fail"),
    ("S", "S Failed Introduction 0-31-0-0-0", 0, 31, "fail"),  # SF 3
    # HB 10
    (
        "S",
        "S Motion to Suspend Rules to Resolve into COW & Place at the Top of GF Failed 13-18-0-0-0",
        13,
        18,
        "fail",
    ),
    ("H", "HB0001H2030: Amendment failed 30-30-2-0-0", 30, 30, "fail"),  # HB 1, a tie
    ("H", "HB0001H2018: Amendment adopted 31-29-1-0-1", 31, 29, "pass"),  # HB 1
    ("S", "S 3rd Reading:Passed 31-0-0-0-0", 31, 0, "pass"),  # SF 2
    ("H", "H 3rd Reading:Passed 48-13-1-0-0", 48, 13, "pass"),  # HB 10
    ("S", "S Concur:Passed 30-0-1-0-0", 30, 0, "pass"),  # SF 10
    ("S", "S Adopted SF0001JC001: 28-3-0-0-0", 28, 3, "pass"),  # SF 1
    ("S", "S Introduced and Referred to S10 - Labor 25-6-0-0-0", 25, 6, "pass"),  # SF 4
    ("S", "S01 - Judiciary:Recommend Amend and Do Pass 3-2-0-0-0", 3, 2, "pass"),
]


@pytest.mark.parametrize("chamber,motion,yes,no,expected", REAL_RESULTS)
def test_vote_result_on_real_2026_roll_calls(chamber, motion, yes, no, expected):
    assert vote_result(chamber, motion, yes, no) == expected


# Constructed counts on the real override text, to pin the threshold: two thirds of the members elected, 21 of the
# Senate's 31 and 42 of the House's 62, not of those voting.
@pytest.mark.parametrize(
    "chamber,yes,no,expected",
    [
        ("S", 21, 10, "pass"),
        ("S", 20, 11, "fail"),
        ("H", 42, 20, "pass"),
        ("H", 41, 19, "fail"),
    ],
)
def test_override_needs_two_thirds_of_the_members_elected(chamber, yes, no, expected):
    motion = "SF0001VT001: Line Item Veto Override {}-{}-0-0-0".format(yes, no)
    assert vote_result(chamber, motion, yes, no) == expected


def test_a_stated_outcome_wins_over_the_count():
    """Constructed counts on the real text: "Did Not Override" is a failure even with two thirds of the yeas."""
    motion = "SF0001VT002: Did Not Override Line Item Veto 42-20-0-0-0"
    assert vote_result("H", motion, 42, 20) == "fail"


@pytest.mark.parametrize(
    "motion",
    [
        "H 3rd Reading:Passed 30-30-2-0-0",
        "HB0001H2030: Amendment adopted 30-30-2-0-0",
        "SF0001VT004: Line Item Veto Override:Passed 35-25-2-0-0",
    ],
)
def test_a_stated_pass_wins_over_the_count(motion):
    """Constructed counts on real texts (the last a constructed text): a stated pass stands at a tie or short of
    two thirds."""
    yes, no = (int(n) for n in motion.rsplit(" ", 1)[1].split("-")[:2])
    assert vote_result("H", motion, yes, no) == "pass"


def test_scrape_vote_stores_the_failed_override_as_failed():
    """The ticket's example end to end: SF 1's House vote on line item VT007, 41-19, the override did not carry."""
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    bill = Bill("SF 1", legislative_session="2026", chamber="upper", title="t")
    rc = {
        "chamber": "H",
        "voteDate": "2026-03-20T10:00:00",
        "yesVotesCount": 41,
        "yesVotes": "",
        "noVotesCount": 19,
        "noVotes": "",
        "absentVotesCount": 1,
        "absentVotes": "",
        "conflictVotesCount": 0,
        "conflictVotes": "",
        "excusedVotesCount": 1,
        "excusedVotes": "",
        "billNumber": "SF0001",
        "action": "Did Not Override Line Item Veto 41-19-1-1-0",
        "amendmentNumber": "SF0001VT007",
    }
    (vote,) = scraper.scrape_vote(bill, rc, "2026")
    assert vote.result == "fail"
    assert vote.organization == '~{"classification": "lower"}'
