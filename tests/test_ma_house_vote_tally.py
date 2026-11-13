"""Tests for OPEN-442: a Massachusetts House roll call's tally comes from its own
sheet when the voters read from that sheet equal the totals it declares.

bills.py sets the tally from the House action text ("... - 139 YEAS to 0 NAYS (See
YEA and NAY No. 221)"), which for 16 of the 234 roll calls read in the 194th
disagrees with the roll-call sheet and with the voters on it. The fixture is the real
No. 221 (S 3106 On Engrossment, 2026-07-01) from the House journal's 2026 RollCalls
PDF, run through `pdftotext -layout` as the scraper does: the sheet declares 149
YEAS, 0 NAYS, 9 N/V; the action text said 139 YEAS.
"""
import os
import sys
from unittest import mock

from openstates.scrape import VoteEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "ma_house_rollcall_194_221.txt"
)
PDF_URL = "https://malegislature.gov/Journal/House/194/2026/RollCalls"


def _sheet():
    with open(FIXTURE) as f:
        return f.read()


def _scrape(yes, no, sheet=None, result=None):
    """Run scrape_house_vote on No. 221 for a vote whose action text said
    `yes` YEAS to `no` NAYS, as the caller sets it."""
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    scraper.get_house_pdf = mock.Mock(return_value=sheet or _sheet())
    vote = VoteEvent(
        chamber="lower",
        start_date="2026-07-01",
        motion_text="Ordered to be engrossed",
        result=result or ("pass" if yes > no else "fail"),
        classification="passage",
        legislative_session="194th",
        bill="S 3106",
    )
    vote.set_count("yes", yes)
    vote.set_count("no", no)
    read = scraper.scrape_house_vote(vote, PDF_URL, 221)
    return read, vote


def _counts(vote):
    return {c["option"]: c["value"] for c in vote.counts}


def _voters(vote, option):
    return sum(1 for v in vote.votes if v["option"] == option)


def test_the_sheet_replaces_an_action_tally_that_disagrees_with_it():
    read, vote = _scrape(139, 0)
    assert read is True
    assert _voters(vote, "yes") == 149 and _voters(vote, "no") == 0
    # the tally now agrees with its own voters and the sheet's 149 YEAS 0 NAYS
    assert _counts(vote) == {"yes": 149, "no": 0}


def test_an_action_tally_that_agrees_is_unchanged_and_gains_no_counts():
    read, vote = _scrape(149, 0)
    assert read is True
    assert _counts(vote) == {"yes": 149, "no": 0}
    assert vote.result == "pass"


def test_not_voting_cells_stay_other_and_are_not_added_to_the_tally():
    _, vote = _scrape(139, 0)
    assert _voters(vote, "other") == 9  # the sheet's 9 N/V, recorded as before
    assert "not voting" not in _counts(vote)


def test_the_result_is_not_recomputed_from_the_sheet_tally():
    """A two-thirds motion (veto override, suspension of rules, emergency
    preamble) can fail with more yeas than nays. The result the caller set stays;
    only the counts come from the sheet."""
    read, vote = _scrape(139, 0, result="fail")
    assert read is True
    assert _counts(vote) == {"yes": 149, "no": 0}
    assert vote.result == "fail"


def test_an_agreeing_vote_keeps_its_counts_and_its_result():
    _, vote = _scrape(149, 0, result="fail")
    assert _counts(vote) == {"yes": 149, "no": 0}
    assert vote.result == "fail"


def test_voters_that_disagree_with_the_sheet_keep_the_action_tally():
    """A cell the grid reader lost: the sheet is not proven, so it is not used."""
    sheet = _sheet().replace("Y     Arciero ", "      Arciero ", 1)
    read, vote = _scrape(139, 0, sheet)
    assert read is True
    assert _voters(vote, "yes") == 148
    assert _counts(vote) == {"yes": 139, "no": 0}


def test_a_sheet_without_declared_totals_keeps_the_action_tally():
    sheet = _sheet().replace("149 YEAS", "", 1)
    read, vote = _scrape(139, 0, sheet)
    assert read is True
    assert _voters(vote, "yes") == 149
    assert _counts(vote) == {"yes": 139, "no": 0}


def test_a_missing_roll_call_keeps_the_action_tally_and_reads_nobody():
    read, vote = _scrape(139, 0, sheet=_sheet().replace("No. 221", "No. 999"))
    assert read is False
    assert vote.votes == []
    assert _counts(vote) == {"yes": 139, "no": 0}
