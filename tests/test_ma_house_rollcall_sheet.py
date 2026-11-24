"""Tests for OPEN-443: a Massachusetts House roll call missing from the House journal's
year PDF is read from its own sheet.

The 2026 year PDF (https://malegislature.gov/Journal/House/194/2026/RollCalls) was last
built on 2026-07-27. It holds No. 117 to No. 236 (without No. 233) and nothing after, so
40 House votes from 2026-07-15 to 2026-10-21 were stored with a tally and no voters.
Each roll call also has its own sheet, .../RollCall/194/HouseRollCall<n>.pdf, in the same
layout. The fixture is one of those real sheets run through `pdftotext -layout` as the
scraper does: No. 275, printed "H. 5699 , as amended", the vote stored on H 5700, 152
YEAS 0 NAYS 5 N/V on 10/21/2026.
"""
import os
import sys
from unittest import mock

import lxml.html
from openstates.scrape import Bill, VoteEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
YEAR_PDF = "https://malegislature.gov/Journal/House/194/2026/RollCalls"
SHEET_275 = "https://malegislature.gov/RollCall/194/HouseRollCall275.pdf"


def _fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


# The year PDF as the site serves it today, for these tests: No. 221 is in it, No. 275
# is not.
YEAR_TEXT = _fixture("ma_house_rollcall_194_221.txt")
SHEET_TEXT = _fixture("ma_house_rollcall_sheet_194_275.txt")


def _scraper(pdfs):
    """A scraper whose House PDF fetch returns `pdfs[url]` (None when absent, as
    `get_house_pdf` does on a failed fetch), recording each URL asked for."""
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    scraper.get_house_pdf = mock.Mock(side_effect=lambda url: pdfs.get(url))
    return scraper


def _vote(yes, no):
    vote = VoteEvent(
        chamber="lower",
        start_date="2026-10-21",
        motion_text="Passed to be engrossed",
        result="pass",
        classification="passage",
        legislative_session="194th",
        bill="H 5700",
    )
    vote.set_count("yes", yes)
    vote.set_count("no", no)
    return vote


def _voters(vote, option):
    return sum(1 for v in vote.votes if v["option"] == option)


def _counts(vote):
    return {c["option"]: c["value"] for c in vote.counts}


def test_a_roll_call_in_the_year_pdf_is_read_there_and_no_sheet_is_fetched():
    scraper = _scraper({YEAR_PDF: YEAR_TEXT})
    vote = _vote(149, 0)
    assert scraper.scrape_house_voters(vote, YEAR_PDF, "194th", 221) == YEAR_PDF
    assert _voters(vote, "yes") == 149
    assert [c.args[0] for c in scraper.get_house_pdf.call_args_list] == [YEAR_PDF]


def test_a_roll_call_missing_from_the_year_pdf_is_read_from_its_own_sheet(
    tmp_path, monkeypatch
):
    """No. 275: the year PDF does not have it, its sheet does. The sheet's bill line
    says H. 5699 and the vote is on H 5700; that is not a reason to refuse it."""
    # OPEN-810: "Mr. Speaker" is named by the manifest only; a made-up Speaker here
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text(
        "ma:\n  votes:\n    house_speaker_by_session:\n      194th: Oswin Thackerberry\n"
    )
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    scraper = _scraper({YEAR_PDF: YEAR_TEXT, SHEET_275: SHEET_TEXT})
    vote = _vote(152, 0)
    assert scraper.scrape_house_voters(vote, YEAR_PDF, "194th", 275) == SHEET_275
    assert [c.args[0] for c in scraper.get_house_pdf.call_args_list] == [
        YEAR_PDF,
        SHEET_275,
    ]
    assert (_voters(vote, "yes"), _voters(vote, "no"), _voters(vote, "other")) == (
        152,
        0,
        5,
    )
    names = {v["voter_name"] for v in vote.votes}
    assert "Oswin Thackerberry" in names  # "Mr. Speaker", named as on the year PDF
    assert _counts(vote) == {"yes": 152, "no": 0}


def test_the_sheet_gets_the_same_totals_check_as_the_year_pdf():
    """The action said 150; the sheet and its voters say 152, so the sheet is the
    tally (OPEN-442's rule, unchanged)."""
    scraper = _scraper({YEAR_PDF: YEAR_TEXT, SHEET_275: SHEET_TEXT})
    vote = _vote(150, 0)
    scraper.scrape_house_voters(vote, YEAR_PDF, "194th", 275)
    assert _counts(vote) == {"yes": 152, "no": 0}


def test_a_sheet_whose_voters_disagree_with_its_totals_keeps_the_action_tally():
    sheet = SHEET_TEXT.replace("Y     Hogan ", "      Hogan ", 1)
    assert sheet != SHEET_TEXT
    scraper = _scraper({YEAR_PDF: YEAR_TEXT, SHEET_275: sheet})
    vote = _vote(150, 0)
    assert scraper.scrape_house_voters(vote, YEAR_PDF, "194th", 275) == SHEET_275
    assert _voters(vote, "yes") == 151
    assert _counts(vote) == {"yes": 150, "no": 0}


def test_the_sheet_url_carries_no_session_ordinal():
    scraper = _scraper({})
    scraper.scrape_house_voters(_vote(152, 0), YEAR_PDF, "194th", 275)
    assert scraper.get_house_pdf.call_args_list[-1].args[0] == SHEET_275


def test_a_roll_call_in_neither_reads_nobody_and_returns_none():
    # An error page or an unrelated sheet saved at the sheet URL: no "No. 275" in it.
    scraper = _scraper({YEAR_PDF: YEAR_TEXT, SHEET_275: "<html>Not Found</html>"})
    vote = _vote(152, 0)
    assert scraper.scrape_house_voters(vote, YEAR_PDF, "194th", 275) is None
    assert vote.votes == []
    assert _counts(vote) == {"yes": 152, "no": 0}


def _house_votes(pdfs):
    """Run H 5700's real No. 275 bill-history row through `scrape_action_page`."""
    scraper = _scraper(pdfs)
    bill = Bill(
        "H5700", legislative_session="194th", title="test bill", classification="bill"
    )
    page = lxml.html.fromstring(
        "<table><tbody><tr><td>10/21/2026</td><td>House</td><td>"
        "Passed to be engrossed - 152 YEAS to 0 NAYS (See YEA and NAY No. 275 )"
        "</td></tr></tbody></table>"
    )
    votes = [
        item
        for item in scraper.scrape_action_page(bill, page)
        if type(item).__name__ == "VoteEvent"
    ]
    assert len(votes) == 1
    return votes[0]


def test_a_vote_read_from_its_sheet_keeps_its_dedupe_key_and_cites_the_sheet():
    """The dedupe key stays on the year PDF's URL, so the stored tally-only vote is
    filled in place on the next import rather than duplicated."""
    vote = _house_votes({YEAR_PDF: YEAR_TEXT, SHEET_275: SHEET_TEXT})
    assert vote.dedupe_key == YEAR_PDF + "#275#H5700"
    assert [s["url"] for s in vote.sources] == [SHEET_275]
    assert "voters_unavailable" not in vote.extras
    assert _voters(vote, "yes") == 152


def test_a_vote_read_from_neither_is_labelled_and_cites_the_year_pdf_as_before():
    vote = _house_votes({YEAR_PDF: YEAR_TEXT})
    assert vote.dedupe_key == YEAR_PDF + "#275#H5700"
    assert [s["url"] for s in vote.sources] == [YEAR_PDF]
    assert vote.extras["voters_unavailable"] == "house-rollcall-unreadable"
    assert vote.votes == []
