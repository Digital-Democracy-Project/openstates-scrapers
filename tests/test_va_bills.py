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


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-80: bill_no= targeting -- scopes scrape() to just the requested bill(s)
# within the one shared getlegislationlistasync list call, instead of every
# bill in the session.
# ═══════════════════════════════════════════════════════════════════════════


def _make_bill_row(number: str, legislation_id=None) -> dict:
    return {
        "LegislationNumber": number,
        "Description": f"A bill about {number}",
        "LegislationTitle": None,
        "LegislationSummary": None,
        "ChamberCode": "H" if number.startswith("H") else "S",
        "LegislationID": legislation_id or number,
    }


BILL_LIST_ROWS = [
    _make_bill_row("HB30"),
    _make_bill_row("SB12"),
    _make_bill_row("HB99"),
]


def _mock_bill_list(monkeypatch, rows=BILL_LIST_ROWS):
    fake_response = mock.Mock()
    fake_response.json.return_value = {"Legislations": rows}
    monkeypatch.setattr(
        "va.bills.requests.post", mock.Mock(return_value=fake_response)
    )


def _stub_detail_calls(monkeypatch, scraper) -> list:
    """Stubs the four expensive per-bill calls; records the LegislationID passed
    to _fetch_events (the first of the four) as a proxy for "this bill reached
    full detail processing" -- fixture rows above set LegislationID equal to
    LegislationNumber so assertions can compare directly against bill numbers.
    """
    reached_detail_processing = []
    monkeypatch.setattr(
        scraper,
        "_fetch_events",
        lambda legislation_id: reached_detail_processing.append(legislation_id) or [],
    )
    monkeypatch.setattr(scraper, "add_versions", lambda bill, legislation_id: None)
    monkeypatch.setattr(scraper, "add_sponsors", lambda bill, legislation_id: None)
    monkeypatch.setattr(scraper, "add_votes", lambda bill, legislation_id: iter(()))
    return reached_detail_processing


def _make_scraper_with_env(monkeypatch) -> VaBillScraper:
    monkeypatch.setenv("VA_API_KEY", "test-key")
    return VaBillScraper(Virginia(), "/tmp/")


def test_scrape_with_bill_no_only_scrapes_the_matching_bill(monkeypatch):
    scraper = _make_scraper_with_env(monkeypatch)
    _mock_bill_list(monkeypatch)
    reached_detail_processing = _stub_detail_calls(monkeypatch, scraper)

    bills = list(scraper.scrape("2026S1", bill_no="HB30"))

    assert reached_detail_processing == ["HB30"]
    assert [b.identifier for b in bills] == ["HB30"]


def test_scrape_with_multi_bill_no_scrapes_all_requested_bills_only(monkeypatch):
    scraper = _make_scraper_with_env(monkeypatch)
    _mock_bill_list(monkeypatch)
    reached_detail_processing = _stub_detail_calls(monkeypatch, scraper)

    bills = list(scraper.scrape("2026S1", bill_no="HB30,SB12"))

    assert reached_detail_processing == ["HB30", "SB12"]
    assert [b.identifier for b in bills] == ["HB30", "SB12"]


def test_scrape_without_bill_no_scrapes_every_bill_unchanged(monkeypatch):
    scraper = _make_scraper_with_env(monkeypatch)
    _mock_bill_list(monkeypatch)
    reached_detail_processing = _stub_detail_calls(monkeypatch, scraper)

    bills = list(scraper.scrape("2026S1"))

    assert reached_detail_processing == ["HB30", "SB12", "HB99"]
    assert [b.identifier for b in bills] == ["HB30", "SB12", "HB99"]


def test_scrape_with_bill_no_normalizes_case_and_whitespace(monkeypatch):
    scraper = _make_scraper_with_env(monkeypatch)
    _mock_bill_list(monkeypatch)
    reached_detail_processing = _stub_detail_calls(monkeypatch, scraper)

    bills = list(scraper.scrape("2026S1", bill_no=" hb30 , Sb12 "))

    assert reached_detail_processing == ["HB30", "SB12"]
    assert [b.identifier for b in bills] == ["HB30", "SB12"]


def test_scrape_warns_on_unmatched_bill_no(monkeypatch):
    scraper = _make_scraper_with_env(monkeypatch)
    _mock_bill_list(monkeypatch)
    _stub_detail_calls(monkeypatch, scraper)

    warnings = []
    monkeypatch.setattr(scraper, "warning", lambda msg: warnings.append(msg))

    list(scraper.scrape("2026S1", bill_no="HB30,HB404"))

    assert any("HB404" in msg for msg in warnings)
    assert not any("HB30" in msg for msg in warnings)
