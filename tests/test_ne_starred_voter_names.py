"""OPEN-761: Nebraska prints a "*" after the name of a senator who was Present Not Voting when the vote was
taken and had the vote recorded later (Rules of the Nebraska Legislature, Rule 6, Sec. 9). The legislature counts
these votes, so the vote stays as printed; only the "*" comes off the name, which otherwise matches no one.

The fixtures are nebraskalegislature.gov's own vote pages, unchanged, saved 2026-11-22:
- ne_12956.html: LB 48 (109th), 2025-05-30, "Failed on Final Reading with Emergency Clause 26-22*-1"; seven of the 22
  No votes are starred (Hansen*, Armendariz*, Hardin*, Storm*, Strommen*, DeKay*, Dover*).
- ne_14292.html: LB 1096, 34-15; three of the 15 No votes are starred (DeBoer*, Cavanaugh, M.*, Guereca*).
"""
import os
import sys
from collections import Counter
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ne.bills import NEBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ne_open761")


def _page(fname):
    with open(os.path.join(FIXTURES, fname), encoding="utf-8") as f:
        return lxml.html.fromstring(f.read())


def _scraper():
    return NEBillScraper(jurisdiction="x", datadir="/tmp")


def _votes(fname, key_id):
    history = lxml.html.fromstring(
        '<table class="history"><tr><td>May 30, 2025</td><td>Failed on Final Reading</td>'
        f'<td><a href="https://nebraskalegislature.gov/bills/view_votes.php?KeyID={key_id}">v</a></td></tr></table>'
    )
    scraper = _scraper()
    with mock.patch.object(scraper, "lxmlize", return_value=_page(fname)):
        (vote,) = scraper.scrape_votes(
            Bill("LB 48", "109", "x", chamber="legislature"), history, "legislature"
        )
    return vote


@pytest.mark.parametrize(
    "fname,starred",
    [
        (
            "ne_12956.html",
            ["Hansen", "Armendariz", "Hardin", "Storm", "Strommen", "DeKay", "Dover"],
        ),
        ("ne_14292.html", ["DeBoer", "Cavanaugh, M.", "Guereca"]),
    ],
)
def test_starred_names_lose_the_marker_and_keep_their_no_vote(fname, starred):
    names, count = _scraper().get_votes(_page(fname), "No :")
    assert count == len(names)  # nobody dropped
    assert not [n for n in names if "*" in n]
    for name in starred:
        assert name in names


def test_lb48_vote_counts_and_options_unchanged():
    vote = _votes("ne_12956.html", 12956)
    counts = {c["option"]: c["value"] for c in vote.counts}
    assert (counts["yes"], counts["no"], counts["excused"]) == (26, 22, 1)
    # each option holds as many voters as its count: the starred senators still voted No
    assert Counter(v["option"] for v in vote.votes) == Counter(
        {"yes": 26, "no": 22, "excused": 1}
    )
    by_name = {v["voter_name"]: v["option"] for v in vote.votes}
    assert by_name["Hansen"] == "no"
    assert by_name["Dover"] == "no"
    assert not [v for v in vote.votes if v["voter_name"].endswith("*")]


def test_lb1096_cavanaugh_m_voted_no():
    vote = _votes("ne_14292.html", 14292)
    by_name = {v["voter_name"]: v["option"] for v in vote.votes}
    assert by_name["Cavanaugh, M."] == "no"
    assert "Cavanaugh, M.*" not in by_name


@pytest.mark.parametrize(
    "cell,name",
    [
        ("Hansen*", "Hansen"),
        ("  Cavanaugh, M. * ", "Cavanaugh, M."),
        ("Hansen", "Hansen"),
        ("Wordekemper", "Wordekemper"),
    ],
)
def test_marker_and_surrounding_spaces_come_off(cell, name):
    page = lxml.html.fromstring(
        '<div id="by_vote_viewport"><div class="card-header">No : 1</div>'
        f"<table><tr><td><div>{cell}</div><div> * </div></td></tr></table></div>"
    )
    assert _scraper().get_votes(page, "No :") == ([name], 1)
