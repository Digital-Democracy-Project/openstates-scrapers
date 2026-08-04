"""Tests for OPEN-29: add_votes() never set VoteEvent.identifier, and the BatchNumber
fallback used `"BatchNumber" in row` -- which only checks key *presence*, not truthiness.
VA's getvotebyidasync API returns rows where BatchNumber is a key that's present but None,
so `in` doesn't catch it and the resulting vote source URL literally ended in "/None".
"""
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from va import Virginia  # noqa: E402
from va.bills import VaBillScraper  # noqa: E402


def make_scraper() -> VaBillScraper:
    scraper = VaBillScraper(Virginia(), "/tmp/")
    scraper.session_code = "20262"
    return scraper


def make_bill():
    from openstates.scrape import Bill

    return Bill("HB30", "2026S1", "A bill title", chamber="lower", classification="bill")


ABSENT = object()


def make_vote_row(vote_id: str, batch_number) -> dict:
    row = {
        "VoteID": vote_id,
        "PassFail": "P",
        "IsVoice": False,
        "VoteDate": "2026-06-29T00:00:00",
        "LegislationActionDescription": "Adopt Governor's Recommendation  R",
        "VoteActionDescription": None,
        "ChamberCode": "H",
        "VoteMember": [
            {"ResponseCode": "Y", "MemberDisplayName": "Member One"},
            {"ResponseCode": "Y", "MemberDisplayName": "Member Two"},
            {"ResponseCode": "N", "MemberDisplayName": "Member Three"},
        ],
    }
    if batch_number is not ABSENT:
        row["BatchNumber"] = batch_number
    return row


def run_add_votes(monkeypatch, row) -> list:
    scraper = make_scraper()
    fake_response = mock.Mock(content=json.dumps({"Votes": [row]}).encode())
    monkeypatch.setattr(
        "va.bills.requests.get", mock.Mock(return_value=fake_response)
    )
    return list(scraper.add_votes(make_bill(), "some-legislation-id"))


def test_identifier_is_always_set_to_vote_id(monkeypatch):
    row = make_vote_row("H1003V0001", batch_number="H1003V0001")
    votes = run_add_votes(monkeypatch, row)

    assert len(votes) == 1
    assert votes[0].identifier == "H1003V0001"


@pytest.mark.parametrize(
    "batch_number,expected_url_part",
    [
        pytest.param("H1003V0001", "H1003V0001", id="batch_number_present_and_truthy"),
        pytest.param(None, "SV12345", id="batch_number_present_but_none"),
        pytest.param(ABSENT, "SV12345", id="batch_number_key_absent"),
    ],
)
def test_vote_source_url_falls_back_to_vote_id_when_batch_number_falsy(
    monkeypatch, batch_number, expected_url_part
):
    row = make_vote_row("SV12345", batch_number=batch_number)
    votes = run_add_votes(monkeypatch, row)

    assert len(votes) == 1
    (source,) = votes[0].sources
    assert source["url"] == (
        f"https://lis.virginia.gov/vote-details/HB30/20262/{expected_url_part}"
    )
    assert not source["url"].endswith("/None")
