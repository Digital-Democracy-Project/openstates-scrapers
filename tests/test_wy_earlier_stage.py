"""Tests for OPEN-874: Wyoming's earlier-stage roll calls count as passage when nothing later replaces them.

The fixtures are the `rollCalls` of real 2026 bills from lsoservice.wyoleg.gov/api/BillInformation/2026/<bill>
(fetched 2026-11-24). HB 116: House failed introduction, then introduced again and passed. HB 145: Senate
Committee of the Whole failed, then passed, then third reading. HB 178 and SF 119: a whole-bill veto the chamber
did not override. SF 1: the budget bill's line-item overrides.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper, vote_classification  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wy_open874")


def scrape(bill_number):
    with open(os.path.join(FIXTURES, "2026_%s.json" % bill_number)) as f:
        roll_calls = json.load(f)["rollCalls"]
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    bill = Bill(bill_number, legislative_session="2026", chamber="upper", title="t")
    votes = {}
    for roll_call in roll_calls:
        for vote in scraper.scrape_vote(bill, roll_call, "2026", roll_calls):
            votes[roll_call["voteID"]] = vote
    return votes


def labels(votes, prefix):
    return {
        v.motion_text: v.motion_classification
        for v in votes.values()
        if v.motion_text.startswith(prefix)
    }


@pytest.mark.parametrize(
    "motion,expected",
    [
        ("S Failed Introduction 0-31-0-0-0", ["passage", "reading-1"]),
        (
            "H Introduced and Referred to H05 - Agriculture 46-16-0-0-0",
            ["passage", "reading-1"],
        ),
        ("S COW:Failed 13-16-2-0-0", ["passage"]),
        (
            "H COW:Passed 34-22-6-0-0",
            [],
        ),  # advances the bill; the third reading is the vote
    ],
)
def test_earlier_stage_alone_is_passage(motion, expected):
    assert vote_classification(motion) == expected


@pytest.mark.parametrize(
    "motion,expected",
    [
        ("S Failed Introduction 0-31-0-0-0", ["reading-1"]),
        ("H Introduced and Referred to H05 - Agriculture 46-16-0-0-0", ["reading-1"]),
        ("S COW:Failed 13-16-2-0-0", []),
    ],
)
def test_earlier_stage_is_not_passage_when_a_later_one_replaces_it(motion, expected):
    assert vote_classification(motion, later_passage=True) == expected


def test_hb116_failed_introduction_is_replaced_by_the_third_reading():
    votes = scrape("HB0116")
    assert labels(votes, "H Failed Introduction") == {
        "H Failed Introduction 39-21-2-0-0": ["reading-1"]
    }
    assert labels(votes, "H 3rd Reading")["H 3rd Reading:Passed 44-17-1-0-0"] == [
        "passage"
    ]


def test_hb145_cow_failed_is_replaced_by_the_senate_third_reading():
    votes = scrape("HB0145")
    assert labels(votes, "S COW:Failed") == {"S COW:Failed 13-16-2-0-0": []}
    # the House's introduction is replaced by its own third reading, and the Senate has no introduction roll call
    assert labels(votes, "H Introduced") == {
        "H Introduced and Referred to H08 - Transportation 57-1-4-0-0": ["reading-1"]
    }


def test_a_later_roll_call_of_the_other_chamber_does_not_replace_it():
    votes = scrape("SF0119")
    # SF 119: the Senate's introduction is replaced by the Senate's third reading, not counted twice
    assert labels(votes, "S Introduced") == {
        "S Introduced and Referred to S02 - Appropriations 27-4-0-0-0": ["reading-1"]
    }


def test_whole_bill_override_counts_and_line_item_override_does_not():
    for bill, text in (
        ("HB0178", "HB0178VT001: Did Not Override Veto 36-21-5-0-0"),
        ("SF0119", "SF0119VT001: Did Not Override Veto 20-10-1-0-0"),
    ):
        (vote,) = [v for v in scrape(bill).values() if v.motion_text == text]
        assert vote.motion_classification == ["passage"]
        assert vote.result == "fail"
    budget = scrape("SF0001")
    overrides = [v for v in budget.values() if "Veto" in v.motion_text]
    assert len(overrides) == 14
    assert all(v.motion_classification == ["veto-override"] for v in overrides)


def test_a_passed_whole_bill_override_needs_two_thirds():
    from wy.bills import vote_result

    assert vote_classification("HB0001VT001: Veto Override 42-20-0-0-0") == ["passage"]
    assert vote_result("H", "HB0001VT001: Veto Override 41-21-0-0-0", 41, 21) == "fail"
    assert vote_result("H", "HB0001VT001: Veto Override 42-20-0-0-0", 42, 20) == "pass"


def test_the_other_chambers_third_reading_does_not_replace_it():
    # HB 145's real roll calls with the House's own passage votes left out: the Senate's later third reading and
    # COW passage must not stop the House's introduction roll call counting
    with open(os.path.join(FIXTURES, "2026_HB0145.json")) as f:
        roll_calls = json.load(f)["rollCalls"]
    house_intro = [r for r in roll_calls if r["voteID"] == 5146]
    senate_later = [r for r in roll_calls if r["voteID"] in (471, 510)]
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    bill = Bill("HB 145", legislative_session="2026", chamber="lower", title="t")
    (vote,) = scraper.scrape_vote(
        bill, house_intro[0], "2026", house_intro + senate_later
    )
    assert vote.motion_classification == ["passage", "reading-1"]
