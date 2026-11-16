"""OPEN-598: Oregon vote results come from the legislature's motion text when it states one.

Every text below is a real 2025R1 floor text with its real tally (OpenStates API, read 2026-11-16).
Oregon needs a majority of all members, so the first eight were stored as passes by yes > no.
"""
import importlib

import pytest

or_votes = importlib.import_module("or.votes")  # "or" is a Python keyword
ORVoteScraper = or_votes.ORVoteScraper
result_from_text = or_votes.result_from_text

LEGISLATORS = [{"LegislatorCode": "Smith", "FirstName": "Ann", "LastName": "Smith"}]

CASES = [
    # (text, yes, no, expected result)
    (
        "Third reading. Carried by Andersen, McDonald. Failed.",
        29,
        22,
        "fail",
    ),  # SB 726, House
    ("Third reading. Carried by McLain. Failed.", 26, 24, "fail"),  # HB 2931, House
    ("Third reading. Carried by Gomberg. Failed.", 28, 12, "fail"),  # SB 5541, House
    (
        "Third reading.  Carried by Sollman.  Bill failed.",
        13,
        10,
        "fail",
    ),  # HB 3026, Senate
    (
        "Third reading.  Carried by Frederick.  Bill failed.",
        12,
        9,
        "fail",
    ),  # HB 3025, Senate
    ("Motion to withdraw from Rules failed.", 28, 27, "fail"),  # SB 83, House
    ("Motion to withdraw from Revenue failed.", 30, 26, "fail"),  # HB 3753, House
    (
        "Motion to withdraw from Housing and Homelessness failed.",
        28,
        24,
        "fail",
    ),  # HB 2432, House
    # outcome words that say pass
    ("Third reading. Carried by Nelson. Passed.", 50, 8, "pass"),
    ("Repassed.", 40, 15, "pass"),
    ("Final reading. Carried by Manning Jr. Adopted.", 25, 3, "pass"),
    ("Motion to reconsider carried.", 31, 20, "pass"),
    # "refused to concur" names no outcome: the tally decides, and the motion to refuse passed
    ("House refused to concur in Senate amendments.", 59, 0, "pass"),
    # no outcome word: the tally decides either way
    (
        "Taken from 06-18 Calendar and placed on 06-19 Calendar. Ayes, 18; Nays, 11--Anderson.",
        18,
        11,
        "pass",
    ),
    ("Senate refused to concur in House amendments.", 14, 15, "fail"),
]


def floor(text, ayes, nays):
    return {
        "ActionText": text,
        "ActionDate": "2025-06-10T11:00:00",
        "Chamber": "H",
        "MeasureVotes": [{"VoteName": "Smith", "Vote": "Aye"}] * ayes
        + [{"VoteName": "Smith", "Vote": "Nay"}] * nays,
    }


def scrape(history):
    from unittest import mock

    measure = {
        "MeasurePrefix": "HB",
        "MeasureNumber": 2931,
        "MeasureHistoryActions": history,
        "CommitteeAgendaItems": [],
    }
    scraper = ORVoteScraper.__new__(ORVoteScraper)
    scraper.api_client = mock.Mock()
    scraper.api_client.get.side_effect = (
        lambda resource, **kw: LEGISLATORS if resource == "legislators" else [measure]
    )
    return list(scraper.scrape_votes("2025R1"))


@pytest.mark.parametrize("text,yes,no,expected", CASES)
def test_scraper_result(text, yes, no, expected):
    (vote,) = scrape([floor(text, yes, no)])
    assert vote.result == expected


def test_text_without_an_outcome_word_returns_none():
    assert result_from_text("House refused to concur in Senate amendments.") is None
    assert (
        result_from_text(
            "Rules suspended. Made a Special Order of Business immediately."
        )
        is None
    )


def test_the_carrier_is_not_an_outcome():
    # "Carried by X." names who carries the bill; without an outcome word the tally decides
    assert result_from_text("Third reading. Carried by McLain.") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Third reading. Carried by Gomberg. Failed.", "fail"),
        ("Third reading.  Carried by Sollman.  Bill failed.", "fail"),
        ("Motion to withdraw from Rules failed.", "fail"),
        ("Third reading. Carried by Nelson. Passed.", "pass"),
        ("Repassed.", "pass"),
        ("Read. Carried by Chotzen. Adopted.", "pass"),
        ("House concurred in Senate amendments and readopted measure.", "pass"),
        ("Motion to reconsider carried.", "pass"),
    ],
)
def test_outcome_words(text, expected):
    assert result_from_text(text) == expected
