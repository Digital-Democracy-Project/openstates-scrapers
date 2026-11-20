"""Tests for OPEN-704: an Oklahoma roll call's result is the outcome the vote page states, else
the vote's own threshold, never simply more yeas than nays for a supermajority vote.

Real pages: 2025 HB 1003 House (emergency clause 54-26, page says FAILED), 2026 HB 3005 House
(emergency clause 70-17, page says PASSED) and 2025 HB 2770 Senate (emergency clause 40-2; Senate
pages state no outcome). Thresholds: Oklahoma Constitution Art. V sec. 58 (emergency clause,
two-thirds of all members elected; vetoed emergency measure, three-fourths) and Art. VI sec. 11
(veto override, two-thirds of the members elected), with 101 House and 48 Senate members.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ok.bills import vote_result  # noqa: E402
import test_ok_votes  # noqa: E402
from test_ok_votes import _scrape_page  # noqa: E402

FIXTURES_704 = os.path.join(os.path.dirname(__file__), "fixtures", "ok_open704")


def _emergency(votes):
    return [v for v in votes if v[1] == "Emergency"]


def test_hb1003_house_emergency_54_26_fails():
    assert _emergency(_scrape_page("House_HB1003_VOTES.HTM")) == [
        ("2025-05-15", "Emergency", [], "fail")
    ]


def test_stated_outcome_comes_first():
    # the same page with its FAILED line turned to PASSED: the page's word wins over the count
    def flip(text):
        first = text.index("</span>FAILED<span")
        return text[:first] + "</span>PASSED<span" + text[first + 18 :]

    votes = _scrape_page("House_HB1003_VOTES.HTM", edit=flip)
    assert _emergency(votes) == [("2025-05-15", "Emergency", [], "pass")]


def test_without_a_stated_outcome_the_emergency_threshold_applies():
    # the same page with no outcome line: 54 yeas is under two-thirds of 101 (68), so it fails
    # although yeas outnumber nays
    def drop(text):
        first = text.index("</span>FAILED<span")
        return text[:first] + "</span><span" + text[first + 18 :]

    votes = _scrape_page("House_HB1003_VOTES.HTM", edit=drop)
    assert _emergency(votes) == [("2025-05-15", "Emergency", [], "fail")]
    # nothing else on the page changes
    assert [v for v in votes if v[1] != "Emergency"] == [
        v for v in _scrape_page("House_HB1003_VOTES.HTM") if v[1] != "Emergency"
    ]


def _scrape_704(monkeypatch, fname):
    monkeypatch.setattr(test_ok_votes, "FIXTURES", FIXTURES_704)
    return _scrape_page(fname)


def test_hb3005_house_emergency_70_17_passes(monkeypatch):
    assert _emergency(_scrape_704(monkeypatch, "House_HB3005_VOTES.HTM")) == [
        ("2026-03-12", "Emergency", [], "pass")
    ]


def test_senate_emergency_without_stated_outcome_passes_on_two_thirds(monkeypatch):
    assert _emergency(_scrape_704(monkeypatch, "Senate_HB2770_VOTES.HTM")) == [
        ("2025-05-22", "Emergency", [], "pass")
    ]


@pytest.mark.parametrize(
    "chamber,motion,yes,no,expected",
    [
        # emergency clause: two-thirds of members elected (House 68 of 101, Senate 32 of 48)
        ("lower", "Emergency", 68, 30, "pass"),
        ("lower", "Emergency", 67, 30, "fail"),
        ("upper", "Emergency", 32, 10, "pass"),
        ("upper", "Emergency", 31, 10, "fail"),
        # veto override: two-thirds of members elected
        ("lower", "Veto Override Without Emer.", 68, 30, "pass"),
        ("lower", "Veto Override Without Emer.", 67, 30, "fail"),
        ("upper", "Veto Override No Emergency", 32, 16, "pass"),
        ("upper", "Veto Override No Emergency", 31, 10, "fail"),
        # vetoed emergency measure: three-fourths (House 76, Senate 36)
        ("lower", "Veto Override With Emer.", 76, 20, "pass"),
        ("lower", "Veto Override With Emer.", 75, 20, "fail"),
        ("upper", "Veto Override With Emergency", 36, 10, "pass"),
        ("upper", "Veto Override With Emergency", 35, 10, "fail"),
        # everything else: more yeas than nays
        ("lower", "Third Reading", 40, 39, "pass"),
        ("lower", "Third Reading", 39, 39, "fail"),
        ("upper", "Fourth Reading", 20, 19, "pass"),
        ("upper", "Advance", 10, 11, "fail"),
    ],
)
def test_threshold_when_the_page_states_nothing(chamber, motion, yes, no, expected):
    assert vote_result(chamber, motion, False, None, yes, no) == expected


def test_committee_vote_is_a_simple_majority_whatever_its_text():
    assert vote_result("upper", "Emergency", True, None, 5, 2) == "pass"


@pytest.mark.parametrize("stated,expected", [("PASSED", "pass"), ("FAILED", "fail")])
def test_stated_outcome_overrides_the_count(stated, expected):
    assert vote_result("lower", "Emergency", False, stated, 54, 26) == expected
    assert vote_result("lower", "Third Reading", False, stated, 10, 90) == expected
