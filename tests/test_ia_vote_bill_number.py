"""Tests for OPEN-951: which bill an Iowa journal roll call belongs to when the journal prints the wrong letter.

The fixtures are real stretches of House journals (legis.iowa.gov/docs/publications/HJNL/<yyyymmdd>_HJNL.pdf,
2025-2026), as pdftotext -layout gives them, run through the scraper's own scrape_journal(). Expected bills and
tallies were read off the journal text by hand.

Two things are pinned here:
* The House sometimes takes up "Senate File 593" and then prints the question as (H.F. 593). The bill taken up is
  the bill voted on, so the roll call goes to Senate File 593 (the House's own end-of-day summary lists
  "Senate File 639 - Aye" and "Amdt. H-8468 (S.F. 2480)" for the other two cases).
* When a House file is substituted for a Senate file (or the reverse), the journal prints the number of the bill
  that is voted on, and the roll call stays on that bill. Nothing is dropped.
"""

import logging
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ia.votes  # noqa: E402
from ia.votes import IAVoteScraper, bill_taken_up  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open951")


def scrape(name, monkeypatch):
    """(bill, motion, yes, no) of every roll call scrape_journal() reads from one saved journal excerpt."""
    path = os.path.join(FIXTURES, name)  # an absolute name (tmp_path) wins
    with open(path, "rb") as f:
        text = f.read()
    monkeypatch.setattr(ia.votes, "convert_pdf", lambda filename, type: text)
    scraper = IAVoteScraper.__new__(IAVoteScraper)
    scraper.urlretrieve = lambda url: (path, None)
    scraper.warning = scraper.error = lambda *a, **k: None
    scraper.logger = logging.getLogger("test_ia_vote_bill_number")
    out = []
    for vote in scraper.scrape_journal(
        "https://www.legis.iowa.gov/x.pdf", "lower", "2025-2026", datetime(2026, 1, 1)
    ):
        counts = {c["option"]: c["value"] for c in vote.counts}
        bill = vote.bill.split('"identifier": "')[1].split('"')[0]
        out.append((bill, vote.motion_text, counts["yes"], counts["no"]))
        assert vote.dedupe_key.endswith(f"#{bill}#{vote.motion_text}")
    return out


def test_senate_file_593_asked_as_house_file(monkeypatch):
    """House 2025-05-12: House File 985 is asked as H.F. 985 (right); Senate File 593 is taken up and asked as
    H.F. 593 (wrong), 89-0. It is Senate File 593's House vote."""
    assert scrape("house_20250512_sf593_after_hf985.txt", monkeypatch) == [
        ("HF 985", "Shall the bill pass?", 90, 0),
        ("SF 593", "Shall the bill pass?", 89, 0),
    ]


def test_senate_file_639_and_2480_asked_as_house_files(monkeypatch):
    """House 2026-05-02: Senate File 2480's second amendment (H-8468) and Senate File 639's passage (79-6) are
    asked as H.F. 2480 and H.F. 639; the other questions on those bills carry the right letter."""
    assert scrape("house_20260502_sf2480_sf639.txt", monkeypatch) == [
        ("SF 2480", "Shall amendment H-8467 be adopted?", 30, 55),
        ("SF 2480", "Shall amendment H-8468 be adopted?", 28, 57),
        ("SF 2480", "Shall the bill pass?", 67, 18),
        ("SF 639", "Shall amendment H-8456 be adopted?", 8, 77),
        ("SF 639", "Shall the bill pass?", 79, 6),
    ]


def test_house_file_correctly_asked_is_left_alone(monkeypatch):
    """House 2025-03-26: House File 639 taken up and asked as H.F. 639 (85-10) stays House File 639. The same
    number as Senate File 639 (a different bill) is not mixed up with it."""
    assert scrape("house_20250326_hf639.txt", monkeypatch) == [
        ("HF 639", "Shall the bill pass?", 85, 10)
    ]


def test_substituted_bill_keeps_its_roll_call(monkeypatch):
    """House 2025-02-27: Senate File 418 is substituted for House File 583 and passed 60-36. The journal prints
    S.F. 418, so the roll call is Senate File 418's (the legislature lists it there too); House File 583 has no
    passage roll call because the House never voted to pass it."""
    assert scrape("house_20250227_sf418_for_hf583.txt", monkeypatch) == [
        ("SF 418", "Shall the bill pass?", 60, 36)
    ]


def test_a_different_number_is_never_changed(monkeypatch, tmp_path):
    """Made-up journal text (no real journal asks about another number right after a bill is taken up): House
    File 100 is taken up and the question names S.F. 200. Only the letter is ever corrected, never the number."""
    text = (
        b"   House File 100, a bill for an act relating to roads, was taken up for\n"
        b"consideration.\n\n"
        b"   On the question \xe2\x80\x9cShall the bill pass?\xe2\x80\x9d (S.F. 200)\n\n"
        b"   The ayes were, 2:\n\nAdams   Baker\n\n"
        b"   The nays were, none.\n\n"
        b"   Absent or not voting, 1:\n\nCarter\n\n"
        b"  The bill having received a constitutional majority was declared to\n"
        b"have passed the House and the title was agreed to.\n"
    )
    path = tmp_path / "made_up.txt"
    path.write_bytes(text)
    assert scrape(str(path), monkeypatch) == [("SF 200", "Shall the bill pass?", 2, 0)]


def test_both_bills_of_one_number_in_one_journal_keep_their_own_votes(
    monkeypatch, tmp_path
):
    """Made-up journal text: Senate File 7 is taken up and voted as S.F. 7, then House File 7 (a different bill)
    is taken up and voted as H.F. 7. Each stays on its own bill; the later heading replaces the earlier one."""

    def one(opener, printed):
        return (
            f"   {opener}, a bill for an act relating to roads, was taken up for\n"
            "consideration.\n\n"
            f"   On the question \u201cShall the bill pass?\u201d ({printed})\n\n"
            "   The ayes were, 2:\n\nAdams   Baker\n\n"
            "   The nays were, none.\n\n"
            "   Absent or not voting, 1:\n\nCarter\n\n"
            "  The bill having received a constitutional majority was declared to\n"
            "have passed the House and the title was agreed to.\n\n"
        )

    path = tmp_path / "made_up_both.txt"
    path.write_text(one("Senate File 7", "S.F. 7") + one("House File 7", "H.F. 7"))
    assert [b for b, *_ in scrape(str(path), monkeypatch)] == ["SF 7", "HF 7"]


@pytest.mark.parametrize(
    "line,expected",
    [
        (
            "Senate File 593, a bill for an act providing for the preparation and",
            "SF 593",
        ),
        ("Senate File 639", "SF 639"),
        ("House File 2739", "HF 2739"),
        (
            "Senate File 660, A bill for an act relating to sports wagering and",
            "SF 660",
        ),
        ("Senate File 2464 be withdrawn from further consideration of the", None),
        ("House File 2739 be substituted for Senate File 2464.", None),
        ("SENATE FILE 418 SUBSTITUTED FOR HOUSE FILE 583", None),
        ("for consideration House File 2515 and Senate Files 2427 and 2464.", None),
        ("House Files 917, 2227, and 2583; and House Concurrent Resolution 6.", None),
    ],
)
def test_bill_taken_up(line, expected):
    assert bill_taken_up(line) == expected
