"""OPEN-597: Oregon vote labels in the or vote scraper.

The measure below copies the shape of one row of the Oregon OData `votes` resource (MeasureHistoryActions
with MeasureVotes, CommitteeAgendaItems with CommitteeVotes); the texts are real 2025R1 texts. No test
makes a live call.
"""
import importlib
from unittest import mock

ORVoteScraper = importlib.import_module(
    "or.votes"
).ORVoteScraper  # "or" is a Python keyword

LEGISLATORS = [{"LegislatorCode": "Smith", "FirstName": "Ann", "LastName": "Smith"}]


def floor(text, ayes=31, nays=29):
    return {
        "ActionText": text,
        "ActionDate": "2025-06-10T11:00:00",
        "Chamber": "H",
        "MeasureVotes": [{"VoteName": "Smith", "Vote": "Aye"}] * ayes
        + [{"VoteName": "Smith", "Vote": "Nay"}] * nays,
    }


def committee(action):
    return {
        "Action": action,
        "Comments": None,
        "MeetingDate": "2025-03-10T13:00:00",
        "CommitteCode": "HJUD",
        "CommitteeVotes": [
            {"VoteName": "Smith", "Meaning": "Aye"},
            {"VoteName": "Jones", "Meaning": "Aye"},
            {"VoteName": "Brown", "Meaning": "Nay"},
        ],
    }


def scrape(measure):
    scraper = ORVoteScraper.__new__(ORVoteScraper)
    scraper.api_client = mock.Mock()
    scraper.api_client.get.side_effect = (
        lambda resource, **kw: LEGISLATORS if resource == "legislators" else [measure]
    )
    return list(scraper.scrape_votes("2025R1"))


def measure(history=(), agenda=()):
    return {
        "MeasurePrefix": "HB",
        "MeasureNumber": 2942,
        "MeasureHistoryActions": list(history),
        "CommitteeAgendaItems": list(agenda),
    }


def test_floor_votes_use_the_or_block():
    votes = scrape(
        measure(
            history=[
                floor("Third reading. Carried by Nelson. Passed."),
                floor("House concurred in Senate amendments and repassed bill."),
                floor("Motion to withdraw from Rules failed."),
                floor("Passed."),
            ]
        )
    )
    assert [v.motion_classification for v in votes] == [
        ["passage"],
        ["passage"],
        [],
        ["passage"],
    ]


def test_committee_votes_are_committee_passage_by_source():
    votes = scrape(
        measure(
            agenda=[
                committee("Heard and Reported Out"),
                committee("Heard and Reported Out with Amendments"),
            ]
        )
    )
    assert [v.motion_classification for v in votes] == [
        ["committee-passage"],
        ["committee-passage"],
    ]
    assert all(v.motion_text.startswith("Heard") for v in votes)


def test_committee_vote_without_an_action_uses_comments_and_is_still_committee_passage():
    item = committee(None)
    item["Comments"] = "Heard"
    votes = scrape(measure(agenda=[item]))
    assert votes[0].motion_text == "Heard"
    assert votes[0].motion_classification == ["committee-passage"]
