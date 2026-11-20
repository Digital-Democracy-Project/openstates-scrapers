"""Tests for OPEN-675: Wyoming's API gives some Senate roll calls the House's chamber.

The chamber/action/amendment cases below are real 2026 roll calls from
lsoservice.wyoleg.gov/api/BillInformation/2026/<bill> (fetched 2026-11-20). Every case reuses SF 10's
introduction-vote tallies and voters; only the chamber, action and amendment number vary. SF 10's and SF 2's
Senate introduction votes ("S Introduced and Referred to ...", 31 votes: the Senate's size) come back with
chamber "H"; the action's "S " prefix names the chamber that voted.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper, voting_chamber  # noqa: E402

SENATORS_SF10 = (
    "Anderson, Barlow, Boner, Brennan, Case, Cooper, Crago, Crum, Driskill, Dockstader, French, Gierau, Hicks, "
    "Hutchings, Ide, Jones, Kolb, Landen, Laursen, Love, McKeown, Nethercott, Olsen, Pappas, Rothfuss, Pearson, "
    "Salazar, Scott, Schuler, Steinmetz, Biteman"
)


def roll_call(chamber, action, amendment=None):
    return {
        "chamber": chamber,
        "voteDate": "2026-02-09T14:48:50",
        "yesVotesCount": 31,
        "yesVotes": SENATORS_SF10,
        "noVotesCount": 0,
        "noVotes": "",
        "absentVotesCount": 0,
        "absentVotes": "",
        "conflictVotesCount": 0,
        "conflictVotes": "",
        "excusedVotesCount": 0,
        "excusedVotes": "",
        "billNumber": "SF0010",
        "action": action,
        "amendmentNumber": amendment,
    }


# (API chamber, action, amendmentNumber, the chamber that voted) -- every one a real 2026 roll call.
REAL_ROLL_CALLS = [
    # The API's chamber is wrong: Senate introduction votes on Senate files.
    (
        "H",
        "S Introduced and Referred to S01 - Judiciary 31-0-0-0-0",
        None,
        "upper",
    ),  # SF 10
    (
        "H",
        "S Introduced and Referred to S02 - Appropriations 31-0-0-0-0",
        None,
        "upper",
    ),  # SF 2
    # The API's chamber is right and agrees with the prefix.
    ("S", "S Introduced and Referred to S10 - Labor 25-6-0-0-0", None, "upper"),  # SF 4
    ("S", "S 3rd Reading:Passed 31-0-0-0-0", None, "upper"),  # SF 10
    ("H", "H 3rd Reading:Passed 55-2-5-0-0", None, "lower"),  # SF 2
    (
        "H",
        "H Introduced and Referred to H01 - Judiciary 46-16-0-0-0",
        None,
        "lower",
    ),  # HB 10
    ("H", "H Failed Introduction 34-28-0-0-0", None, "lower"),  # HB 20
    (
        "S",
        "S Motion to Suspend Rules to Resolve into COW & Place at the Top of GF",
        None,
        "upper",
    ),  # HB 10
    # No "S "/"H " prefix: the API's chamber stands.
    (
        "S",
        "S02 - Appropriations:Recommend Do Pass 5-0-0-0-0",
        None,
        "upper",
    ),  # SF 2 committee
    (
        "H",
        "H01 - Judiciary:Recommend Amend and Do Pass 6-1-2-0-0",
        None,
        "lower",
    ),  # HB 10 committee
    ("S", "Amendment failed 3-28-0-0-0", "SF0002S2001", "upper"),  # SF 2
    ("H", "Amendment failed 22-38-2-0-0", "SF0004H2001", "lower"),  # SF 4
]


@pytest.mark.parametrize("api_chamber,action,amendment,expected", REAL_ROLL_CALLS)
def test_voting_chamber_on_real_2026_roll_calls(
    api_chamber, action, amendment, expected
):
    rc = roll_call(api_chamber, action, amendment=amendment)
    assert WYBillScraper.chamber_abbrev_map[voting_chamber(rc)] == expected


@pytest.mark.parametrize("api_chamber,action,amendment,expected", REAL_ROLL_CALLS)
def test_scrape_vote_stores_the_chamber_that_voted(
    api_chamber, action, amendment, expected
):
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    bill = Bill("SF 10", legislative_session="2026", chamber="upper", title="t")
    (vote,) = scraper.scrape_vote(
        bill, roll_call(api_chamber, action, amendment=amendment), "2026"
    )
    assert vote.organization == '~{"classification": "%s"}' % expected


def test_sf10_introduction_senators_are_on_a_senate_vote():
    """The ticket's example: SF 10's introduction vote, chamber "H" in the API, 31 senators voting yes."""
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    bill = Bill("SF 10", legislative_session="2026", chamber="upper", title="t")
    rc = roll_call("H", "S Introduced and Referred to S01 - Judiciary 31-0-0-0-0")
    (vote,) = scraper.scrape_vote(bill, rc, "2026")
    assert vote.organization == '~{"classification": "upper"}'
    assert len(vote.votes) == 31
    assert {"Driskill", "Case", "Pappas"} <= {v["voter_name"] for v in vote.votes}


def test_house_prefix_wins_over_a_senate_api_chamber():
    """Synthetic (no real case seen in 2026): the rule is the prefix in both directions, not a Senate-only patch."""
    rc = roll_call("S", "H Introduced and Referred to H01 - Judiciary 46-16-0-0-0")
    assert voting_chamber(rc) == "H"
