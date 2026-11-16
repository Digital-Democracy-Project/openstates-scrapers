"""OPEN-573: the North Carolina scraper reads every roll call on a bill page, not only the latest two.

The page shows a bill's latest two roll calls in the visible table (class "row") and the rest in a
collapsed "Show All Votes" block (class "row mx-0"). The fixtures are the vote cards of the real
ncleg.gov pages of the eight bills the govbot check reported (2025 session, saved 2026-11-15,
tests/fixtures/nc_votes). The govbot roll calls below are its vote files for each bill
(~/.govbot-data/nc-legislation, failed votes included); the stored ones are the Mac replica's.
No test makes a live call.
"""
import os
from unittest import mock

import lxml.html
import pytest

from nc.bills import NCBillScraper
from openstates.scrape import Bill

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nc_votes")

# bill: (page file, every roll call on the page newest first, govbot's roll calls, stored on the replica)
BILLS = {
    "HB 116": (
        "H116",
        ["[H]-794", "[S]-676", "[S]-669", "[H]-784", "[S]-397", "[H]-396", "[H]-24"],
        {"[H]-794", "[S]-676", "[S]-669", "[H]-784"},
        {"[H]-794", "[S]-676"},
    ),
    "HB 147": (
        "H147",
        ["[H]-802", "[H]-793", "[S]-695", "[S]-679", "[S]-678", "[H]-98", "[H]-93"],
        {"[H]-802", "[H]-793", "[H]-98", "[H]-93"},
        {"[H]-802", "[H]-793"},
    ),
    "HB 268": (
        "H268",
        [
            "[H]-803",
            "[H]-795",
            "[S]-696",
            "[S]-677",
            "[H]-632",
            "[S]-473",
            "[H]-62",
            "[H]-54",
        ],
        {"[H]-803", "[H]-795", "[H]-632", "[S]-473"},
        {"[H]-803", "[H]-795"},
    ),
    "HB 377": (
        "H377",
        [
            "[H]-804",
            "[S]-702",
            "[H]-748",
            "[S]-556",
            "[S]-555",
            "[S]-553",
            "[S]-554",
            "[H]-111",
        ],
        {"[H]-804", "[S]-702", "[H]-748", "[S]-556"},
        {"[H]-804", "[S]-702"},
    ),
    "HB 562": (
        "H562",
        ["[H]-796", "[S]-697", "[H]-634", "[S]-471", "[S]-472", "[H]-248"],
        {"[H]-796", "[S]-697", "[H]-634", "[S]-471"},
        {"[H]-796", "[S]-697"},
    ),
    "HB 834": (
        "H834",
        ["[H]-800", "[S]-682", "[S]-683", "[H]-340", "[H]-339"],
        {"[H]-800", "[S]-682", "[H]-340", "[H]-339"},
        {"[H]-800", "[S]-682"},
    ),
    "HB 958": (
        "H958",
        ["[H]-801", "[S]-693"]
        + [f"[S]-{n}" for n in range(692, 683, -1)]
        + ["[H]-758", "[H]-757", "[H]-756", "[H]-755"],
        {"[H]-801", "[S]-693", "[H]-758", "[H]-757"},
        {"[H]-801", "[S]-693"},
    ),
    "SB 445": (
        "S445",
        [
            "[H]-797",
            "[S]-701",
            "[S]-618",
            "[H]-677",
            "[H]-676",
            "[H]-675",
            "[H]-674",
            "[S]-152",
        ],
        {"[H]-797", "[S]-701", "[S]-618", "[H]-677"},
        {"[H]-797", "[S]-701"},
    ),
}


def scrape_votes(identifier):
    name = BILLS[identifier][0]
    with open(os.path.join(FIXTURES, f"votes_2025_{name}.html"), encoding="utf-8") as f:
        doc = lxml.html.fromstring(f.read())
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    bill = Bill(identifier, "2025", "A bill", chamber="lower")
    transcript = mock.Mock(text="<html><body></body></html>")
    with mock.patch.object(scraper, "get", return_value=transcript) as get:
        votes = list(scraper.scrape_votes(bill, doc))
    return votes, get


@pytest.mark.parametrize("identifier", sorted(BILLS))
def test_every_roll_call_on_the_page_is_read(identifier):
    _, on_page, govbot, stored = BILLS[identifier]
    votes, get = scrape_votes(identifier)
    keys = [v.dedupe_key for v in votes]
    assert keys == on_page
    # nothing govbot has is missing, and nothing stored today is lost
    assert govbot <= set(keys)
    assert stored <= set(keys)
    # one roll-call transcript fetched per vote
    assert get.call_count == len(on_page)


def test_hb116_july_2_votes_are_read_with_their_tallies():
    """The two votes the govbot check found missing: House 107-2 and Senate 47-0 on 07/02/2026."""
    votes, _ = scrape_votes("HB 116")
    by_key = {v.dedupe_key: v for v in votes}
    house, senate = by_key["[H]-784"], by_key["[S]-669"]
    assert house.motion_text == "R2 Ruled Mat'l C RPT Adoption"
    assert house.start_date.startswith("2026-07-02")
    assert {c["option"]: c["value"] for c in house.counts}["yes"] == 107
    assert {c["option"]: c["value"] for c in house.counts}["no"] == 2
    assert senate.motion_text == "Conference Rpt Second Reading"
    assert {c["option"]: c["value"] for c in senate.counts}["yes"] == 47
    assert senate.sources[0]["url"].endswith("/RollCallVoteTranscript/2025/S/669")


def test_no_roll_call_is_read_twice():
    for identifier in BILLS:
        keys = [v.dedupe_key for v in scrape_votes(identifier)[0]]
        assert len(keys) == len(set(keys)), identifier
