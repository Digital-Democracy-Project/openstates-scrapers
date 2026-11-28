"""Tests for OPEN-951: a roll call whose question prints the wrong file type is filed under the file in hand.

The fixtures are cut from real Iowa House journals (legis.iowa.gov/docs/publications/HJNL/20250512_HJNL.pdf and
20260502_HJNL.pdf, read 2026-11-27) as pdftotext -layout gives them. Bill, tally and names were read off the
journal text by hand.
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


# House 2025-05-12: "Senate File 593, a bill for an act ..., was taken up for consideration" and then
# 'On the question "Shall the bill pass?" (H.F. 593)': the 89-0 is Senate File 593's (the legislature's
# bill history lists "Passed House, yeas 89, nays 0" on SF 593).
# House 2026-05-02: "Senate File 639, a bill for an act creating a specialty business court" and then
# "(H.F. 639)" for the bill's passage, 79-6 (the legislature lists it on SF 639); its amendment H-8456 just
# before carries the right "(S.F. 639)".
CASES = [
    ("house_20250512_sf593.txt", [("SF 593", "Shall the bill pass?", 89, 0)]),
    (
        "house_20260502_sf639.txt",
        [
            ("SF 639", "Shall amendment H-8456 be adopted?", 8, 77),
            ("SF 639", "Shall the bill pass?", 79, 6),
        ],
    ),
]


@pytest.mark.parametrize("name,expected", CASES)
def test_vote_is_filed_under_the_file_in_hand(name, expected, monkeypatch):
    found = []
    for vote in scrape_votes(name, "lower", monkeypatch):
        counts = {c["option"]: c["value"] for c in vote.counts}
        found.append((bill_of(vote), vote.motion_text, counts["yes"], counts["no"]))
    assert found == expected


def test_a_correct_bill_number_is_left_alone(monkeypatch):
    # House 2026-05-02 reads two questions on Senate File 639 whose numbers agree with the file in hand
    # (H-8456's "(S.F. 639)"); only the wrong one moves, and the names still add up to the tally.
    votes = scrape_votes("house_20260502_sf639.txt", "lower", monkeypatch)
    assert [bill_of(v) for v in votes] == ["SF 639", "SF 639"]
    passage = votes[1]
    assert len([v for v in passage.votes if v["option"] == "yes"]) == 79


def test_other_number_is_not_moved(monkeypatch):
    # A question whose number differs from the file in hand is not a typo of it (SF 2464 / HF 2739 type
    # substitutions print the new bill's own number): the scraper only repairs the same number.
    path = os.path.join(FIXTURES, "house_20250512_sf593.txt")
    with open(path) as f:
        text = f.read().replace("(H.F. 593)", "(H.F. 594)")
    monkeypatch.setattr(ia.votes, "convert_pdf", lambda filename, type: text.encode())
    scraper = IAVoteScraper.__new__(IAVoteScraper)
    scraper.urlretrieve = lambda url: (path, None)
    scraper.warning = scraper.error = lambda *a, **k: None
    scraper.logger = logging.getLogger("test_ia_open951")
    votes = list(
        scraper.scrape_journal(
            "https://www.legis.iowa.gov/x.pdf", "lower", "2025", datetime(2026, 1, 1)
        )
    )
    assert [bill_of(v) for v in votes] == ["HF 594"]


def test_the_file_in_hand_is_the_latest_one_named(monkeypatch):
    # Two journals' excerpts read as one: the second repair needs the file named last (SF 639), not the first.
    texts = []
    for name in ("house_20250512_sf593.txt", "house_20260502_sf639.txt"):
        with open(os.path.join(FIXTURES, name), "rb") as f:
            texts.append(f.read())
    monkeypatch.setattr(
        ia.votes, "convert_pdf", lambda filename, type: b"\n".join(texts)
    )
    scraper = IAVoteScraper.__new__(IAVoteScraper)
    scraper.urlretrieve = lambda url: ("x", None)
    scraper.warning = scraper.error = lambda *a, **k: None
    scraper.logger = logging.getLogger("test_ia_open951")
    votes = list(
        scraper.scrape_journal(
            "https://www.legis.iowa.gov/x.pdf", "lower", "2025", datetime(2026, 1, 1)
        )
    )
    assert [bill_of(v) for v in votes] == ["SF 593", "SF 639", "SF 639"]
