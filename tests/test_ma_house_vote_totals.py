"""Tests for OPEN-427: the Massachusetts House roll-call reader checks what it read
against the tally the sheet declares.

Upstream #5843 reads each "<letter> <name>" cell of the roll grid together, so the
old "letters and names are the same length" check can no longer fail. Nothing then
compared the voters with the declared YEAS / NAYS / N/V, so a grid read wrongly
looked like a roll call read correctly. The fixtures are three real roll calls from
the House journal's 2025 RollCalls PDF (194th), run through `pdftotext -layout` as
the scraper does:

* star    -- No. 1, has votes marked "*" (cast after the roll closed)
* jones_x -- No. 25, has "--Jones--" and "--Whipps--" names and X (not voting) cells
* present -- No. 33, has a P (present) cell, which no declared total counts

On all 234 roll calls with a bill identifier in the 2025 and 2026 PDFs, the voters
read equal the declared totals (checked offline when this was written).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma.votes import HouseRollCall, HouseVoteRecordParser  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SEPARATOR = "MASSACHUSETTS HOUSE OF REPRESENTATIVES"


def _text(name):
    with open(os.path.join(FIXTURES, f"ma_house_rollcall_194_{name}.txt")) as f:
        return f.read()


def _parser(name):
    return HouseVoteRecordParser(_text(name).split(SEPARATOR, 1)[1], session="194th")


@pytest.mark.parametrize("name", ["star", "jones_x", "present"])
def test_real_roll_calls_match_their_declared_totals(name):
    assert _parser(name).totals_mismatch() is None


def test_present_is_not_compared_with_any_declared_total():
    parser = _parser("present")
    assert parser.votes.count("P") == 1
    assert parser.totals_mismatch() is None
    event = parser.createVoteEvent()
    other = [v["voter_name"] for v in event.votes if v["option"] == "other"]
    assert len(other) == 1


def test_marker_decorations_are_not_part_of_the_name():
    names = _parser("jones_x").names
    assert "Jones" in names and "Whipps" in names
    assert not any("--" in n or n.endswith("*") for n in names)


def test_a_dropped_cell_is_reported():
    """A cell the grid reader lost: one fewer Y than the sheet declares."""
    text = _text("jones_x").replace("Y    Arciero ", "     Arciero ", 1)
    parser = HouseVoteRecordParser(text.split(SEPARATOR, 1)[1], session="194th")
    assert parser.totals_mismatch() is not None
    assert "127" in parser.totals_mismatch()  # the declared yeas are named


def test_a_flipped_letter_is_reported():
    """The grid was read but one letter is the wrong one: yes-no counts move."""
    text = _text("jones_x").replace("Y    Arciero ", "N    Arciero ", 1)
    parser = HouseVoteRecordParser(text.split(SEPARATOR, 1)[1], session="194th")
    assert parser.totals_mismatch() is not None


def test_a_header_without_totals_is_skipped_with_a_warning():
    text = _text("jones_x").replace("127 YEAS", "").split(SEPARATOR, 1)[1]
    parser = HouseVoteRecordParser(text, session="194th")
    assert parser.total_yea is None
    assert "declared totals" in parser.get_warning()


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


def _scrape(text):
    page = HouseRollCall.__new__(HouseRollCall)
    page.session = "194th"
    page.logger = _Logger()
    page.text = text
    page.source = type("S", (), {"url": "https://malegislature.gov/test"})()
    return list(page.process_page()), page.logger.warnings


def test_a_clean_roll_call_keeps_its_voters_and_logs_nothing():
    events, warnings = _scrape(_text("jones_x"))
    assert warnings == []
    assert len(events) == 1
    assert len(events[0].votes) == 158
    assert "voters_unavailable" not in events[0].extras


def test_a_roll_call_that_disagrees_keeps_its_tally_and_loses_its_voters():
    text = _text("jones_x").replace("Y    Arciero ", "     Arciero ", 1)
    events, warnings = _scrape(text)
    assert len(events) == 1
    event = events[0]
    assert {c["option"]: c["value"] for c in event.counts} == {
        "yes": 127,
        "no": 23,
        "not voting": 8,
    }
    assert event.votes == []
    assert event.extras["voters_unavailable"] == "house-rollcall-totals"
    assert len(warnings) == 1 and "voters_unavailable" in warnings[0]


def test_one_bad_roll_call_does_not_stop_the_rest_of_the_pdf():
    bad = _text("jones_x").replace("Y    Arciero ", "     Arciero ", 1)
    events, warnings = _scrape(bad + _text("star") + _text("present"))
    assert len(events) == 3
    assert [bool(e.votes) for e in events] == [False, True, True]
    assert len(warnings) == 1
