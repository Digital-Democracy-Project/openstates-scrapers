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
