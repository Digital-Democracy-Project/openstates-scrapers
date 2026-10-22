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

    return Bill(
        "HB30", "2026S1", "A bill title", chamber="lower", classification="bill"
    )


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
    # upstream's VA scraper now goes through the scraper's own self.get()/self.post()
    # (scrapelib retry/backoff) rather than the raw requests module
    monkeypatch.setattr(VaBillScraper, "get", mock.Mock(return_value=fake_response))
    return list(scraper.add_votes(make_bill(), "some-legislation-id"))


def test_identifier_is_always_set_to_vote_id(monkeypatch):
    row = make_vote_row("H1003V0001", batch_number="H1003V0001")
    votes = run_add_votes(monkeypatch, row)

    assert len(votes) == 1
    assert votes[0].identifier == "H1003V0001"


def test_unmapped_response_code_skips_only_that_voter(monkeypatch):
    """OPEN-306: self.vote_map[ResponseCode] used to raise a bare KeyError on any code not in
    the hardcoded map -- VA's API has no published enum for this field, so a new code crashes
    the whole scrape rather than just costing one voter's row."""
    row = make_vote_row("H1003V0002", batch_number="H1003V0002")
    row["VoteMember"].append({"ResponseCode": "Z", "MemberDisplayName": "Member Four"})
    votes = run_add_votes(monkeypatch, row)

    assert len(votes) == 1
    voter_names = {v["voter_name"] for v in votes[0].votes}
    assert voter_names == {"Member One", "Member Two", "Member Three"}
    assert "Member Four" not in voter_names


def test_unmapped_response_code_for_every_voter_warns_with_a_summary(
    monkeypatch, caplog
):
    """pm-review (OPEN-306): an unmapped code affecting MANY voters, not just one, would
    otherwise look like a complete vote with a much smaller voter count than reality -- confirms
    a single summary warning fires naming the affected VoteID, not just scattered per-voter
    noise. Note: this row's Y/N/A tally would all be zero after every voter is skipped, which
    add_votes already treats as a miscoded voice vote and drops -- so this asserts the warning
    fired, not that a VoteEvent survives (a separate, pre-existing behavior, unrelated to this
    fix)."""
    row = make_vote_row("H1003V0003", batch_number="H1003V0003")
    for member in row["VoteMember"]:
        member["ResponseCode"] = "Z"

    import logging

    with caplog.at_level(logging.WARNING, logger="openstates"):
        run_add_votes(monkeypatch, row)

    assert "VoteID H1003V0003" in caplog.text
    assert "3 voter(s) skipped due to an unmapped response code" in caplog.text


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
    monkeypatch.setattr(VaBillScraper, "post", mock.Mock(return_value=fake_response))


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


# Upstream openstates-scrapers #5826 (OPEN-406): a vote's motion text falls back to the bill's own
# action text, the same committee vote LIS lists under two VoteIDs is yielded once, and a bill the
# list repeats once per summary version is scraped once, from its most recent row.


def make_committee_vote_row(
    vote_id, description="Reported from Appropriations with substitute"
):
    """The shape LIS returned for HB 1398 (2026): one committee vote under two VoteIDs."""
    row = make_vote_row(vote_id, batch_number=None)
    row.update(
        {
            "VoteDate": "2026-02-11T12:45:00",
            "CommitteeName": "Appropriations",
            "Description": description,
            "LegislationActionDescription": None,
            "VoteActionDescription": "Reported from Appropriations with substitute",
            "VoteLegislation": [
                {
                    "LegislationNumber": "HB30",
                    "LegislationActionDescription": "Reported from Appropriations with substitute",
                }
            ],
        }
    )
    return row


def run_add_votes_many(monkeypatch, rows) -> list:
    scraper = make_scraper()
    fake_response = mock.Mock(content=json.dumps({"Votes": rows}).encode())
    monkeypatch.setattr(VaBillScraper, "get", mock.Mock(return_value=fake_response))
    return list(scraper.add_votes(make_bill(), "some-legislation-id"))


def test_same_committee_vote_under_two_vote_ids_is_yielded_once(monkeypatch):
    votes = run_add_votes_many(
        monkeypatch,
        [make_committee_vote_row("296656"), make_committee_vote_row("296660")],
    )

    assert len(votes) == 1
    # the first VoteID is kept, so a stored vote keeps its dedupe_key
    assert votes[0].dedupe_key == "296656-HB30"


def test_distinct_votes_with_the_same_voters_are_both_kept(monkeypatch):
    """Two real votes can have an identical roll (a repeated set of amendment votes): a
    different Description or a different time means they are not the LIS duplicate."""
    votes = run_add_votes_many(
        monkeypatch,
        [
            make_committee_vote_row("1", description="Amendment 1 agreed to"),
            make_committee_vote_row("2", description="Amendment 2 agreed to"),
        ],
    )
    assert [v.identifier for v in votes] == ["1", "2"]

    later = make_committee_vote_row("4")
    later["VoteDate"] = "2026-02-11T13:00:00"
    votes = run_add_votes_many(monkeypatch, [make_committee_vote_row("3"), later])
    assert [v.identifier for v in votes] == ["3", "4"]


def test_vote_rows_without_committee_or_description_do_not_crash_the_scrape(
    monkeypatch,
):
    first = make_vote_row("10", batch_number=None)
    second = make_vote_row("11", batch_number=None)
    # make_vote_row has neither CommitteeName nor Description: the de-duplication must
    # tolerate that rather than raise a KeyError that stops the whole VA scrape
    votes = run_add_votes_many(monkeypatch, [first, second])

    assert len(votes) == 1  # identical in every field the key uses


def test_null_top_level_action_falls_back_to_the_bills_own_vote_legislation_entry(
    monkeypatch,
):
    votes = run_add_votes_many(monkeypatch, [make_committee_vote_row("20")])

    assert votes[0].motion_text == "Reported from Appropriations with substitute"
    assert votes[0].bill_action == "Reported from Appropriations with substitute"
    # the classifier is given the same text, so VA's bill_action rules see it
    assert votes[0].motion_classification == ["committee-passage"]


def test_bill_repeated_once_per_summary_version_is_scraped_once_from_its_last_row(
    monkeypatch,
):
    monkeypatch.setenv("VA_API_KEY", "test-key")
    rows = [
        {
            "LegislationID": 100,
            "LegislationNumber": "HB1",
            "Description": "A bill",
            "LegislationTitle": None,
            "LegislationSummary": f"<p>{summary}</p>",
            "SummaryVersion": version,
            "ChamberCode": "H",
            "LegislationTypeCode": "HB",
        }
        for summary, version in [
            ("introduced text", "SUMMARY AS INTRODUCED"),
            ("passed text", "SUMMARY AS PASSED"),
        ]
    ] + [
        {
            "LegislationID": 101,
            "LegislationNumber": "HB2",
            "Description": "Another bill",
            "LegislationTitle": None,
            "LegislationSummary": None,
            "SummaryVersion": None,
            "ChamberCode": "H",
            "LegislationTypeCode": "HB",
        }
    ]
    scraper = make_scraper()
    monkeypatch.setattr(
        VaBillScraper,
        "post",
        mock.Mock(return_value=mock.Mock(json=lambda: {"Legislations": rows})),
    )
    monkeypatch.setattr(VaBillScraper, "classify_bill", lambda self, row: ["bill"])
    for name in (
        "add_actions",
        "add_versions",
        "add_carryover_related_bill",
        "add_sponsors",
    ):
        monkeypatch.setattr(VaBillScraper, name, lambda self, *a, **k: None)
    monkeypatch.setattr(VaBillScraper, "_fetch_events", lambda self, legislation_id: [])
    monkeypatch.setattr(VaBillScraper, "add_votes", lambda self, *a, **k: iter(()))

    bills = [b for b in scraper.scrape(session="2026S1") if b.identifier]

    assert [b.identifier for b in bills] == ["HB1", "HB2"]
    first = bills[0].abstracts
    assert [a["abstract"] for a in first] == ["passed text"]
    assert first[0]["note"] == "SUMMARY AS PASSED"


def test_real_hb1398_votes_the_duplicate_committee_vote_is_dropped_and_the_rest_kept(
    monkeypatch,
):
    """Real LIS rows (HB 1398, 2026), trimmed to the fields add_votes reads. VoteIDs 296656 and
    296660 are one Appropriations committee vote listed twice (same time 12:45:00, committee,
    description and 22 voters); 296661 is the "Reconsidered" row with no members (dropped as a
    miscoded voice vote, as before); 297828 is the House floor vote."""
    path = os.path.join(
        os.path.dirname(__file__), "fixtures", "va_hb1398_votes_real.json"
    )
    with open(path) as f:
        rows = json.load(f)["Votes"]
    votes = run_add_votes_many(monkeypatch, rows)

    assert [v.dedupe_key for v in votes] == ["296656-HB30", "297828-HB30"]
    assert votes[0].motion_text.startswith(
        "Reported from Appropriations with substitute"
    )
    yes = {c["option"]: c["value"] for c in votes[0].counts}["yes"]
    assert yes == 22


# pm-review (OPEN-406): the edges of the duplicate skip and of the VoteLegislation fallback.


def test_identical_votes_on_two_different_bills_are_both_kept(monkeypatch):
    """The skip is scoped to one bill (add_votes runs once per bill): the same time,
    committee, description and roll on two bills is two votes, not a duplicate."""
    from openstates.scrape import Bill

    scraper = make_scraper()
    row = make_committee_vote_row("500")
    monkeypatch.setattr(
        VaBillScraper,
        "get",
        mock.Mock(
            return_value=mock.Mock(content=json.dumps({"Votes": [row]}).encode())
        ),
    )
    first = list(scraper.add_votes(Bill("HB1", "2026S1", "t", chamber="lower"), "id-1"))
    row["VoteLegislation"][0]["LegislationNumber"] = "HB2"
    second = list(
        scraper.add_votes(Bill("HB2", "2026S1", "t", chamber="lower"), "id-2")
    )

    assert len(first) == 1 and len(second) == 1


def test_votes_with_no_committee_or_description_are_kept_when_their_time_or_roll_differs(
    monkeypatch,
):
    a = make_vote_row("600", batch_number=None)
    b = make_vote_row("601", batch_number=None)
    b["VoteDate"] = "2026-06-29T00:05:00"  # a different time
    c = make_vote_row("602", batch_number=None)
    c["VoteMember"][2]["ResponseCode"] = "Y"  # one member voted differently
    votes = run_add_votes_many(monkeypatch, [a, b, c])

    assert [v.identifier for v in votes] == ["600", "601", "602"]


def test_vote_with_no_matching_vote_legislation_entry_falls_back_to_the_vote_description(
    monkeypatch,
):
    """Real shape (SB 822, 2026): VoteLegislation is empty and the top-level action is null, so
    the motion is VoteActionDescription, exactly as before the change, and bill_action stays None."""
    row = make_vote_row("700", batch_number=None)
    row["LegislationActionDescription"] = None
    row["VoteActionDescription"] = "Constitutional reading dispensed  R"
    row["VoteLegislation"] = []
    (vote,) = run_add_votes_many(monkeypatch, [row])
    assert vote.motion_text == "Constitutional reading dispensed  R"
    assert vote.bill_action is None

    # an entry for a different bill does not match either
    row["VoteLegislation"] = [
        {"LegislationNumber": "HB999", "LegislationActionDescription": "Passed House"}
    ]
    (vote,) = run_add_votes_many(monkeypatch, [row])
    assert vote.motion_text == "Constitutional reading dispensed  R"


def test_vote_legislation_entries_missing_a_field_do_not_stop_the_scrape(monkeypatch):
    row = make_vote_row("800", batch_number=None)
    row["LegislationActionDescription"] = None
    row["VoteActionDescription"] = "Fallback text"
    row["VoteLegislation"] = [
        {"LegislationNumber": "HB30"},
        {"LegislationActionDescription": "x"},
        {},
    ]
    (vote,) = run_add_votes_many(monkeypatch, [row])

    assert vote.motion_text == "Fallback text"
