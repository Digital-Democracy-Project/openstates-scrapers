"""Tests for AZBillScraper.scrape_votes' vote counts (OPEN-431).

scrape_votes() makes one BillStatusFloorAction request per floor header; the tests
hand it a fake response, so no real HTTP request is made.
"""
import json
import os
import sys
from unittest import mock

import pytest
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from az import Arizona  # noqa: E402
from az.bills import AZBillScraper  # noqa: E402


def floor_action(**counts):
    action = {
        "Action": "Third Read Passed",
        "ReportDate": "2026-02-17T11:54:33.000",
        "ReferralNumber": 7,
        "Votes": [{"Vote": "Y", "Legislator": {"FullName": "A. Member"}}],
    }
    action.update(counts)
    return action


def scrape(action):
    scraper = AZBillScraper(Arizona(), "/tmp/")
    response = mock.Mock()
    response.url = "https://apps.azleg.gov/api/BillStatusFloorAction?x=1"
    response.content = json.dumps([action]).encode("utf-8")
    scraper.get = mock.Mock(return_value=response)
    bill = Bill("HB 1", "57th-2nd-regular", "A bill", chamber="lower")
    page = {
        "BillId": 1,
        "FloorHeaders": [{"BillStatusActionId": 2, "LegislativeBody": "H"}],
    }
    (vote,) = list(scraper.scrape_votes(bill, page))
    return {c["option"]: c["value"] for c in vote.counts}


def test_excused_is_recorded_when_nobody_voted_present():
    # the bug: the excused count was kept only when "Present" was non-zero
    counts = scrape(floor_action(Ayes=50, Nays=5, Present=0, Excused=3))
    assert counts["excused"] == 3
    assert counts["other"] == 0


def test_excused_is_recorded_alongside_a_present_count():
    counts = scrape(floor_action(Ayes=50, Nays=5, Present=1, Excused=3))
    assert (counts["excused"], counts["other"]) == (3, 1)


@pytest.mark.parametrize("extra", [{}, {"Excused": None}, {"Excused": 0}])
def test_excused_is_zero_when_missing_or_empty(extra):
    counts = scrape(floor_action(Ayes=50, Nays=5, **extra))
    assert counts["excused"] == 0


def test_present_without_excused_does_not_invent_an_excused_count():
    counts = scrape(floor_action(Ayes=50, Nays=5, Present=2))
    assert (counts["excused"], counts["other"]) == (0, 2)


# OPEN-625: which floor roll calls are votes on the bill. Real 2026 rows (57th-2nd-regular),
# trimmed to the fields scrape_votes reads: tests/fixtures/az_open625/<bill>.json holds the
# bill's FloorHeaders and the BillStatusFloorAction answer for each header.
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "az_open625")
FIXTURES_OPEN627 = os.path.join(os.path.dirname(__file__), "fixtures", "az_open627")


def chamber(vote):
    return json.loads(vote.organization[1:])["classification"]


def scrape_bill(number, fixtures=FIXTURES):
    with open(os.path.join(fixtures, number + ".json")) as f:
        data = json.load(f)
    scraper = AZBillScraper(Arizona(), "/tmp/")

    def get(url, timeout=None, params=None):
        response = mock.Mock()
        response.url = f"{url}?billStatusActionId={params['billStatusActionId']}"
        response.content = json.dumps(
            data["FloorActions"][str(params["billStatusActionId"])]
        ).encode("utf-8")
        return response

    scraper.get = get
    bill = Bill(number, "57th-2nd-regular", "A bill", chamber="lower")
    votes = list(scraper.scrape_votes(bill, data))
    by_key = {
        (chamber(v), v.start_date, v.motion_text, v.result): (
            v.motion_classification,
            {c["option"]: c["value"] for c in v.counts}["yes"],
            {c["option"]: c["value"] for c in v.counts}["no"],
        )
        for v in votes
    }
    assert len(by_key) == len(votes)  # no two roll calls share a key
    return by_key


def test_cow_motion_to_amend_is_not_a_passage_vote():
    # HB 2689: the House's "COW Motion to Amend" roll call failed 24-32 on 2/11; the
    # Committee of the Whole's own "do pass" has no roll call (0-0) and is not emitted.
    assert scrape_bill("HB2689") == {
        ("lower", "2026-02-11", "failed to pass", "fail"): ([], 24, 32),
    }


def test_committee_of_the_whole_roll_call_is_not_a_passage_vote():
    # HB 2758: a recorded Committee of the Whole vote (2/17, 28-29) and a COW motion to
    # amend (2/19, 23-32) are not votes on the bill; the third reading (2/19, 32-24) is.
    assert scrape_bill("HB2758") == {
        ("lower", "2026-02-17", "failed to pass", "fail"): ([], 28, 29),
        ("lower", "2026-02-19", "failed to pass", "fail"): ([], 23, 32),
        ("lower", "2026-02-19", "Passed", "pass"): (["passage"], 32, 24),
    }


def test_third_readings_final_reading_and_reconsider_motion():
    # SB 1418 in the Senate: the third reading failed 15-12 on 2/25 (16 needed), the motion
    # to reconsider it passed 16-8 the same day, the third reading passed 16-14 on 3/3 and
    # the final reading (after the House amended it) passed 16-11 on 6/11. The House's
    # third reading passed 31-23 on 6/9. Every third and final reading is passage, failed
    # or passed; the reconsider motion is not. The failed reading is "fail" although its yeas
    # outnumber its nays (OPEN-627).
    assert scrape_bill("SB1418") == {
        ("upper", "2026-02-25", "failed to pass", "fail"): (["passage"], 15, 12),
        ("upper", "2026-02-25", "Passed", "pass"): ([], 16, 8),
        ("upper", "2026-03-03", "Passed", "pass"): (["passage"], 16, 14),
        ("upper", "2026-06-11", "Passed", "pass"): (["passage"], 16, 11),
        ("lower", "2026-06-09", "Passed", "pass"): (["passage"], 31, 23),
    }


@pytest.mark.parametrize(
    "floor_step",
    [
        "COW",
        "ADDCOW",
        "MOTION",
        "RECON_3RD",
        "RECON_FNL",
        "MISC",
        "MOTIONRETURN",
        "CONCUR",
        "CONF",
        None,
    ],
)
@pytest.mark.parametrize("motion_text", ["Passed", "failed to pass"])
def test_only_third_and_final_readings_are_passage(floor_step, motion_text):
    from az.bills import vote_classification

    assert vote_classification(floor_step, motion_text) == []
    assert vote_classification("THIRD", motion_text) == ["passage"]
    assert vote_classification("FINAL", motion_text) == ["passage"]


# OPEN-627: a reading's result is azleg's own outcome ("Passed" / "failed to pass"), not yeas > nays.
# Real 2026 rows: tests/fixtures/az_open627/<bill>.json, built like az_open625's.
def test_failed_reading_with_more_yeas_than_nays_is_a_fail():
    # HB 2918: the House's third reading failed 28-25 on 2/26 (31 needed); it passed 32-24 on 3/3.
    # Its Committee of the Whole reports and the empty 0-0 roll calls are not emitted.
    assert scrape_bill("HB2918", FIXTURES_OPEN627) == {
        ("lower", "2026-02-26", "failed to pass", "fail"): (["passage"], 28, 25),
        ("lower", "2026-03-03", "Passed", "pass"): (["passage"], 32, 24),
    }


def test_plain_failed_reading_is_a_fail():
    # HB 2913: the House's third reading failed 22-30 on 3/9.
    assert scrape_bill("HB2913", FIXTURES_OPEN627) == {
        ("lower", "2026-03-09", "failed to pass", "fail"): (["passage"], 22, 30),
    }


def test_azleg_outcome_wins_over_a_majority_count():
    # SB 1152: the Senate's third reading failed 16-11 on 2/23 although 16 is a majority of 30;
    # some readings need more, and azleg's own outcome says which.
    assert scrape_bill("SB1152", FIXTURES_OPEN627) == {
        ("upper", "2026-02-23", "failed to pass", "fail"): (["passage"], 16, 11),
    }


@pytest.mark.parametrize(
    "chamber, motion_text, yes_count, unanimous, expected",
    [
        ("lower", "Passed", 32, False, "pass"),
        ("lower", "failed to pass", 28, False, "fail"),
        ("upper", "failed to pass", 16, False, "fail"),
        ("lower", "do pass amended", 0, False, "pass"),
        # no outcome in the text: a majority of the chamber's members (31 of 60, 16 of 30)
        ("lower", "Retained on the Calendar", 31, False, "pass"),
        ("lower", "Retained on the Calendar", 30, False, "fail"),
        ("upper", "retained", 16, False, "pass"),
        ("upper", "retained", 15, False, "fail"),
        ("upper", "", 0, True, "pass"),
        ("lower", None, 0, False, "fail"),
    ],
)
def test_vote_result(chamber, motion_text, yes_count, unanimous, expected):
    from az.bills import vote_result

    assert vote_result(chamber, motion_text, yes_count, unanimous) == expected
