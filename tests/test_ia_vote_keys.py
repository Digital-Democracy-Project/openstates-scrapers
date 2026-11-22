"""OPEN-760: every Iowa roll call keeps its own identity at the import (North Dakota's OPEN-757 pattern).

The vote importer (openstates-core `vote_events.py`, `get_object()`) matches a vote with no `dedupe_key` on session +
bill + motion text + start date + chamber. An Iowa journal prints no roll-call number and no time (every roll call of a
day has the journal's date), so a roll call is known by the day's journal (its address names the chamber and the date:
docs/publications/SJNL/20250407_SJNL.pdf), its bill and its question; the scraper already numbers a question put more
than once on one bill that day ("Shall the bill pass? #2"). That is the key, unique across sessions and bills. Each
year of a General Assembly reads both years' journals (OPEN-745), so the same journal read twice must give the same
keys, which the importer then takes as one roll call.

No bill's question is put twice in one day in the saved excerpts, so the second roll call below is built from Senate
2025-04-07's real "Shall the bill pass?" on HF 954 (a copy with its own tally, as after a reconsideration).
The fixtures are tests/fixtures/ia_open699 (journal text as pdftotext -layout gives it, read 2026-11-20).
"""
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ia.votes  # noqa: E402
from ia.votes import IAVoteScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open699")
SJNL = "https://www.legis.iowa.gov/docs/publications/SJNL/20250407_SJNL.pdf"


def journal_votes(text, url, monkeypatch):
    monkeypatch.setattr(ia.votes, "convert_pdf", lambda filename, type: text)
    scraper = IAVoteScraper.__new__(IAVoteScraper)
    scraper.urlretrieve = lambda url: ("unused.pdf", None)
    scraper.warning = scraper.error = lambda *a, **k: None
    scraper.logger = logging.getLogger("test_ia_vote_keys")
    return list(scraper.scrape_journal(url, "upper", "2025", datetime(2025, 4, 7)))


def hf954():
    with open(os.path.join(FIXTURES, "senate_20250407_hf954.txt"), "rb") as f:
        return f.read()


def test_each_roll_call_is_keyed_on_its_journal_bill_and_question(monkeypatch):
    votes = journal_votes(hf954(), SJNL, monkeypatch)
    assert [v.dedupe_key for v in votes] == [
        SJNL + "#HF 954#Shall amendment S-3077 be adopted",
        SJNL + "#HF 954#Shall the bill pass?",
    ]


def test_the_same_question_twice_in_a_day_gets_two_keys(monkeypatch):
    text = hf954()
    start = text.index(
        "   On the question \xe2\x80\x9cShall the bill pass?".encode("latin-1")
    )
    end = text.index(b"CONSIDERATION OF BILL")
    again = text[start:end].replace(b"Yeas, 32:", b"Yeas, 31:")
    votes = journal_votes(text[:end] + again + text[end:], SJNL, monkeypatch)
    passing = [v for v in votes if v.motion_text.startswith("Shall the bill pass?")]
    assert len(passing) == 2
    a, b = passing
    assert (str(a.start_date), str(a.organization)) == (
        str(b.start_date),
        str(b.organization),
    )
    assert [a.dedupe_key, b.dedupe_key] == [
        SJNL + "#HF 954#Shall the bill pass?",
        SJNL + "#HF 954#Shall the bill pass? #2",
    ]
    assert [c["value"] for c in b.counts][0] == 31


def test_the_same_journal_read_twice_gives_the_same_keys(monkeypatch):
    once = journal_votes(hf954(), SJNL, monkeypatch)
    again = journal_votes(hf954(), SJNL, monkeypatch)
    assert [v.dedupe_key for v in once] == [v.dedupe_key for v in again]

    # word for word apart from each object's own random _id, so the importer takes them as one roll call
    def record(v):
        return {k: x for k, x in v.as_dict().items() if k != "_id"}

    assert [record(v) for v in once] == [record(v) for v in again]


def test_another_days_journal_keeps_its_own_keys(monkeypatch):
    other = SJNL.replace("20250407", "20250408")
    keys = {v.dedupe_key for v in journal_votes(hf954(), SJNL, monkeypatch)}
    keys |= {v.dedupe_key for v in journal_votes(hf954(), other, monkeypatch)}
    assert len(keys) == 4


def test_which_votes_count_as_passage_is_unchanged(monkeypatch):
    """OPEN-699's labels stand."""
    assert [
        (v.motion_text, v.motion_classification, v.result)
        for v in journal_votes(hf954(), SJNL, monkeypatch)
    ] == [
        ("Shall amendment S-3077 be adopted", ["amendment"], "fail"),
        ("Shall the bill pass?", ["passage"], "pass"),
    ]
