"""Tests for OPEN-951: an Iowa roll call keeps the journal page it was taken on, so two same-day votes are ordered.

The fixture is cut from the real Senate journal legis.iowa.gov/docs/publications/SJNL/20250514_SJNL.pdf (read
2026-11-27) as pdftotext -layout gives it: SF 660's two passage votes of 2025-05-14 (two excerpts of the one journal
joined, with their page headers). The legislature's bill history cites them "S.J. 1033" and "S.J. 1038".
"""

import logging
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ia.votes  # noqa: E402
from ia.votes import IAVoteScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open951")


def scrape_votes(name, chamber, monkeypatch):
    """The VoteEvents scrape_journal() returns for one saved journal excerpt."""
    path = os.path.join(FIXTURES, name)
    with open(path, "rb") as f:
        text = f.read()
    monkeypatch.setattr(ia.votes, "convert_pdf", lambda filename, type: text)
    scraper = IAVoteScraper.__new__(IAVoteScraper)
    scraper.urlretrieve = lambda url: (path, None)
    scraper.warning = scraper.error = lambda *a, **k: None
    scraper.logger = logging.getLogger("test_ia_open951")
    return list(
        scraper.scrape_journal(
            "https://www.legis.iowa.gov/x.pdf", chamber, "2025", datetime(2026, 1, 1)
        )
    )


def bill_of(vote):
    return vote.bill.split('"identifier": "')[1].split('"')[0]


def test_two_same_day_votes_carry_their_journal_pages(monkeypatch):
    votes = scrape_votes("senate_20250514_sf660.txt", "upper", monkeypatch)
    found = []
    for vote in votes:
        counts = {c["option"]: c["value"] for c in vote.counts}
        found.append((bill_of(vote), counts["yes"], vote.extras))
    assert found == [
        ("SF 660", 43, {"senate-rollcall-num": "1033"}),
        ("SF 660", 39, {"senate-rollcall-num": "1038"}),
    ]


def test_house_votes_use_the_house_key(monkeypatch):
    # House 2026-05-02 (the legislature cites the amendment vote "H.J. 1101" and the passage "H.J. 1102"): the
    # amendment is on the page whose header, "1101", comes first in the excerpt's second half.
    votes = scrape_votes("house_20260502_sf639.txt", "lower", monkeypatch)
    assert [v.extras for v in votes] == [
        {"house-rollcall-num": "1101"},
        {"house-rollcall-num": "1102"},
    ]


def test_a_question_at_a_page_foot_takes_the_page_its_tally_is_on(monkeypatch):
    # House 2025-01-30: 'On the question "Shall the bill pass?" (H.F. 117)' ends page 166 and the tally ("The ayes
    # were, 99") starts page 167, which is the page the legislature cites (H.J. 167). The rules vote before it
    # has its tally on page 166.
    votes = scrape_votes("house_20250130_hf117.txt", "lower", monkeypatch)
    assert [(v.motion_text, v.extras) for v in votes] == [
        (
            "Shall the rules be suspended to consider amendment H-1003?",
            {"house-rollcall-num": "166"},
        ),
        ("Shall the bill pass?", {"house-rollcall-num": "167"}),
    ]
