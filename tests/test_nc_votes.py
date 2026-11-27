"""OPEN-572: North Carolina vote classification on real bill pages.

The fixtures are the vote cards of real ncleg.gov bill pages of the 2025 session, saved 2026-11-15
(tests/fixtures/nc_votes). Each card lists every roll call of the bill, newest first: the latest two in
the visible table and the rest in the "Show All Votes" block. No test makes a live call.
"""
import os
from unittest import mock

import lxml.html
import pytest

from nc.bills import NCBillScraper, vote_classification
from openstates.scrape import Bill

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nc_votes")

# every row of the card, visible or not (the scraper's own row reader is OPEN-573's business)
ALL_ROWS = (
    '//h6[@id="vote-header"]/ancestor::div[contains(@class, "gray-card")]'
    '//div[contains(@class, "card-body")]'
    '//div[contains(concat(" ", normalize-space(@class), " "), " row ")]'
)


def page(bill):
    with open(os.path.join(FIXTURES, f"votes_2025_{bill}.html"), encoding="utf-8") as f:
        return f.read()


def roll_calls(bill):
    """(subject, rcs) of every roll call on the page."""
    doc = lxml.html.fromstring(page(bill))
    rows = [
        [e.text_content() for e in r.xpath("div")[1:-1:2]] for r in doc.xpath(ALL_ROWS)
    ]
    return [(r[1], r[2]) for r in rows]


def classified(bill):
    calls = roll_calls(bill)
    return {rcs: vote_classification(subject, rcs, calls) for subject, rcs in calls}


# What each roll call is, from the bill's own history. HB 147 is a revenue bill: both chambers held a
# second- and a third-reading roll call, and its concurrence was ruled material (R2, then R3).
HB147 = {
    "[H]-802": ["passage"],  # R3 Ruled Mat'l M11 Concur
    "[H]-793": [],  # R2 Ruled Mat'l M11 Concur
    "[S]-695": ["passage"],  # Third Reading
    "[S]-679": [],  # Second Reading, the third-reading roll call followed the next day
    "[S]-678": [],  # Amendment 1
    "[H]-98": ["passage"],  # Third Reading
    "[H]-93": [],  # Second Reading
}
# HB 116: passed the House on a second-reading roll call alone (third reading the same day, no roll
# call), then a conference: report 1 (Senate adopts, House refuses), report 2 ruled material in the House.
HB116 = {
    "[H]-794": ["passage"],  # R3 Ruled Mat'l C RPT Adoption
    "[S]-676": ["passage"],  # Conference Rpt Third Reading
    "[S]-669": [],  # Conference Rpt Second Reading
    "[H]-784": [],  # R2 Ruled Mat'l C RPT Adoption
    "[S]-397": ["passage"],  # Conference Report Motion 8 To Adopt
    "[H]-396": ["passage"],  # M11 Not Concur (OPEN-920: a refusal to concur counts)
    "[H]-24": ["passage"],  # Second Reading, the House's only reading roll call
}
# HB 377: the House passed it on second reading ([H]-111) alone; the Senate held both readings.
HB377 = {
    "[H]-804": ["passage"],  # C RPT Adoption
    "[S]-702": ["passage"],  # Conference Rpt Motion 8 To Adopt
    "[H]-748": ["passage"],  # M11 Not Concur (OPEN-920)
    "[S]-556": ["passage"],  # Third Reading
    "[S]-555": [],  # Amendment 2
    "[S]-553": [],  # Amendment 1
    "[S]-554": [],  # Second Reading, third-reading roll call [S]-556 followed
    "[H]-111": ["passage"],  # Second Reading
}


@pytest.mark.parametrize(
    "bill,expected", [("H147", HB147), ("H116", HB116), ("H377", HB377)]
)
def test_every_roll_call_on_the_page(bill, expected):
    assert classified(bill) == expected


def test_one_passage_per_chamber_on_a_bill_without_a_conference():
    """HB 147 passed each chamber once and concurred once: three passage votes, one per step."""
    assert sorted(k for k, v in classified("H147").items() if v) == [
        "[H]-802",
        "[H]-98",
        "[S]-695",
    ]


def test_a_later_reading_roll_call_of_the_other_chamber_does_not_count():
    calls = [("Second Reading", "[H]-24"), ("Third Reading", "[S]-30")]
    assert vote_classification("Second Reading", "[H]-24", calls) == ["passage"]


def test_an_earlier_second_reading_is_superseded_by_a_later_one():
    """SB 675 (2026): a House second reading on 06/17 and again on 06/30 (passed 2nd and 3rd that day)."""
    calls = [("Second Reading", "[H]-763"), ("Second Reading", "[H]-700")]
    assert vote_classification("Second Reading", "[H]-700", calls) == []
    assert vote_classification("Second Reading", "[H]-763", calls) == ["passage"]


def test_an_amendment_on_second_reading_is_not_a_reading_roll_call():
    calls = [("A1 Almond Second Reading", "[H]-341"), ("Second Reading", "[H]-340")]
    assert vote_classification("Second Reading", "[H]-340", calls) == ["passage"]


def test_scrape_votes_classifies_through_the_rule():
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    bill = Bill("HB 147", "2025", "A bill", chamber="lower")
    transcript = mock.Mock(text="<html><body></body></html>")
    with mock.patch.object(scraper, "get", return_value=transcript):
        votes = list(scraper.scrape_votes(bill, lxml.html.fromstring(page("H147"))))
    got = {v.dedupe_key: v.motion_classification for v in votes}
    # the visible table always holds the latest two roll calls
    assert {"[H]-802", "[H]-793"} <= set(got)
    for key, classification in got.items():
        assert classification == HB147[key]


def test_a_senate_second_reading_with_unengrossed_house_amendments_is_the_senate_passage():
    """OPEN-920, HB 1249 (2026-11-17): the House passed it with two amendments, the Senate passed it second and third
    reading the same day on this one roll call (28-17)."""
    calls = [("Second Reading with unengrossed H Amends", "[S]-1")]
    assert vote_classification(calls[0][0], "[S]-1", calls) == ["passage"]


def test_that_second_reading_is_superseded_by_a_later_senate_reading_roll_call_like_any_second_reading():
    calls = [
        ("Second Reading with unengrossed H Amends", "[S]-1"),
        ("Third Reading", "[S]-2"),
    ]
    assert vote_classification(calls[0][0], "[S]-1", calls) == []
    # and it supersedes an earlier second reading of the same chamber
    calls = [
        ("Second Reading", "[S]-1"),
        ("Second Reading with unengrossed H Amends", "[S]-2"),
    ]
    assert vote_classification(calls[0][0], "[S]-1", calls) == []
    assert vote_classification(calls[1][0], "[S]-2", calls) == ["passage"]


def test_a_failed_second_reading_that_nothing_follows_is_passage_and_its_reconsider_vote_is_not():
    """OPEN-920, HB 305 (2025-05-07): House second reading failed 54-57, the motion to reconsider carried 68-42 the same
    day (the bill's actions: Failed 2nd Reading, Reconsidered 2nd Reading, Withdrawn From Cal, Re-ref Com), and the bill
    passed second reading again on 06/17. The reconsider vote is a vote on a motion, not on the bill. The failed
    reading is superseded by the later one (latest replaces earlier), exactly as it would be by a re-vote; with
    nothing after it, it is the chamber's failed vote and counts."""
    calls = [
        ("Second Reading", "[H]-100"),
        ("Second Reading M6 Reconsider", "[H]-101"),
        ("A1 Blust Second Reading", "[H]-300"),
        ("Second Reading", "[H]-301"),
    ]
    assert vote_classification("Second Reading", "[H]-100", calls) == []
    assert vote_classification("Second Reading M6 Reconsider", "[H]-101", calls) == []
    assert vote_classification("Second Reading", "[H]-301", calls) == ["passage"]
    assert vote_classification("Second Reading", "[H]-100", calls[:2]) == ["passage"]


# OPEN-926 (Ramon, 2026-11-26): a House YES on "M11 Not Concur" refuses the Senate's changes, a vote AGAINST the
# bill; the scraper marks it so the broker turns each member's round. The Senate's "Motion 9 To Concur" is not marked.
@pytest.mark.parametrize(
    "bill", ["H116", "H147", "H268", "H377", "H562", "H834", "H958", "S445"]
)
def test_only_the_house_m11_not_concur_roll_calls_are_marked_yes_is_against(bill):
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    b = Bill("HB 1", "2025", "A bill", chamber="lower")
    transcript = mock.Mock(text="<html><body></body></html>")
    with mock.patch.object(scraper, "get", return_value=transcript):
        votes = list(scraper.scrape_votes(b, lxml.html.fromstring(page(bill))))
    assert votes
    for v in votes:
        expected = v.motion_text.strip().lower().endswith("m11 not concur")
        assert v.extras.get("ddp_yes_is_against", False) is expected, v.motion_text
        if expected:
            assert "lower" in v.organization


def test_the_fixtures_hold_marked_roll_calls():
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    b = Bill("HB 1", "2025", "A bill", chamber="lower")
    transcript = mock.Mock(text="<html><body></body></html>")
    marked = []
    with mock.patch.object(scraper, "get", return_value=transcript):
        for bill in ["H116", "H268", "H377", "H562"]:
            for v in scraper.scrape_votes(b, lxml.html.fromstring(page(bill))):
                if v.extras.get("ddp_yes_is_against"):
                    marked.append(v.dedupe_key)
    assert "[H]-396" in marked and "[H]-748" in marked
    assert len(marked) == 4
