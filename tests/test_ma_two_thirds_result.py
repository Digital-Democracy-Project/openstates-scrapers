"""Tests for OPEN-561: a Massachusetts motion that needs two thirds was marked passed on
a simple majority.

Every MA roll call took its result from yeas > nays. A veto override, a suspension of
the rules or an emergency preamble needs two thirds of those present and voting, so it
can win a majority and still fail. The result of such a motion now comes from what its
own text says happened ("passed over veto", "does not prevail"), and when the text states
no outcome, from the two-thirds threshold. Every other motion keeps yeas > nays.

The action lines are real MA 194th bill-history lines (Mac replica, 2026-11-14) unless a
test says it changed the tally: no stored two-thirds roll call won a majority and failed,
so that case uses the real Tarr suspension line with its tally swapped for a majority.
"""
import logging
import os
import sys
from unittest import mock

import lxml.html
import pytest
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402
from ma.votes import HouseVoteRecordParser, SenateJournal, vote_result  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SEPARATOR = "MASSACHUSETTS HOUSE OF REPRESENTATIVES"


def _votes(action_line, chamber="House", date="10/8/2025"):
    """Run one bill-history row through `scrape_action_page` and return its votes.

    The roll-call PDFs are not fetched: voters are not what is under test.
    """
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    bill = Bill(
        "H 4240", legislative_session="194th", title="test bill", classification="bill"
    )
    page = lxml.html.fromstring(
        "<table><tbody><tr><td>{}</td><td>{}</td><td>{}</td></tr></tbody></table>".format(
            date, chamber, action_line
        )
    )
    with mock.patch.object(
        scraper, "scrape_house_vote", return_value=True
    ), mock.patch.object(scraper, "scrape_senate_vote", return_value=True):
        return [
            item
            for item in scraper.scrape_action_page(bill, page)
            if type(item).__name__ == "VoteEvent"
        ]


def _result(action_line, chamber="House"):
    votes = _votes(action_line, chamber)
    assert len(votes) == 1, action_line
    return votes[0].result


class TestTwoThirdsMotionsThroughTheScraper:
    def test_house_veto_override_that_passed(self):
        """H 4240, 2025 House roll call No. 77: 133-22 is above two thirds."""
        assert (
            _result(
                "Item 4000-0051 passed over veto - 133 YEAS to 22 NAYS "
                "(See YEA and NAY No. 77 )"
            )
            == "pass"
        )

    def test_senate_veto_override_that_passed(self):
        """H 4240, Senate Roll Call #78: 35-3."""
        assert (
            _result(
                "Item 4000-0051 passed over veto -see   Roll Call #78 (Yeas 35 to Nays 3)",
                chamber="Senate",
            )
            == "pass"
        )

    def test_senate_suspension_that_failed(self):
        """S 3083, Senate Roll Call #153: the real line, 5-35."""
        assert (
            _result(
                "Motion (Tarr) to suspend the rules does not prevail -- see   "
                "Roll Call #153 (Yeas 5 to Nays 35)",
                chamber="Senate",
            )
            == "fail"
        )

    def test_suspension_with_a_majority_that_did_not_prevail_fails(self):
        """The bug. The S 3083 line with its tally changed to a majority short of two
        thirds: yeas > nays called this passed, the text says it did not prevail."""
        assert (
            _result(
                "Motion (Tarr) to suspend the rules does not prevail -- see   "
                "Roll Call #153 (Yeas 22 to Nays 17)",
                chamber="Senate",
            )
            == "fail"
        )

    def test_override_with_a_majority_and_no_stated_outcome_uses_the_threshold(self):
        """A two-thirds motion whose text states no outcome: 100-55 is a majority but
        under two thirds of 155."""
        assert (
            _result(
                "Item 4000-0051 over veto - 100 YEAS to 55 NAYS (See YEA and NAY No. 77 )"
            )
            == "fail"
        )

    def test_ordinary_motions_keep_the_simple_majority(self):
        """Not two-thirds motions: the rule is unchanged (H 4000 No. 44, a sustained
        ruling of the Chair, is not a veto)."""
        assert (
            _result(
                "Decision of the Chair sustained on appeal - 132 YEAS to 25 NAYS "
                "(See YEA and NAY No. 44 )"
            )
            == "pass"
        )
        assert (
            _result(
                "Passed to be engrossed -see   Roll Call #70 (Yeas 39 to Nays 0)",
                chamber="Senate",
            )
            == "pass"
        )
        assert (
            _result(
                "Amendment #1 (Tarr) rejected -- see   Roll Call #20 (Yeas 9 to Nays 29)",
                chamber="Senate",
            )
            == "fail"
        )


class TestHouseJournalSheet:
    """The votes scraper reads the House journal's roll-call sheets. No. 77 (2025) is
    a real veto override: its motion, cut short on the sheet, is "H. 4240 Shall item
    4000-0051 (Family Resource Centers" and states no outcome, so the threshold decides.
    """

    def _sheet(self, header=None):
        with open(os.path.join(FIXTURES, "ma_house_rollcall_194_77.txt")) as f:
            text = f.read()
        if header:
            text = text.replace("133 YEAS          22 NAYS", header, 1)
        return HouseVoteRecordParser(text.split(SEPARATOR, 1)[1], session="194th")

    def test_real_override_above_two_thirds_passes(self):
        parser = self._sheet()
        assert (parser.total_yea, parser.total_nay) == (133, 22)
        assert parser.createVoteEvent(include_voters=False).result == "pass"

    def test_same_sheet_with_a_majority_under_two_thirds_fails(self):
        parser = self._sheet(header="100 YEAS          55 NAYS")
        assert parser.createVoteEvent(include_voters=False).result == "fail"


def _senate_journal_vote(question, yeas, nays):
    """One vote through `SenateJournal.parse_match`, in the journal's own layout:
    "... the question on <motion> was determined ... (yeas N - nays M) [Yeas and Nays
    No. n]: YEAS. <names> N. NAYS. <names> M." No Senate journal PDF is cached, so the
    text is built in that layout; the names are placeholders, one per vote counted."""

    def names(prefix, count):
        return "\n".join(
            "{}{}{}, A.".format(prefix, chr(65 + i // 26), chr(97 + i % 26))
            for i in range(count)
        )

    text = (
        "The bill (House, No. 4240) was returned by the Governor with objections. "
        + "x " * 400
        + "After debate, the question on {} was determined by a call of the yeas and "
        "nays, as follows, to wit (yeas {} - nays {}) [Yeas and Nays No. 12]:\n"
        "YEAS.\n{}\n{}.\nNAYS.\n{}\n{}.\n"
    ).format(question, yeas, nays, names("Yea", yeas), yeas, names("Nay", nays), nays)
    journal = object.__new__(SenateJournal)
    journal.text = text
    journal.vote_date = "2025-10-23"
    journal.session = "194th"
    journal.bill_id = None
    journal.logger = logging.getLogger(__name__)
    journal.source = mock.Mock(url="https://malegislature.gov/Journal/Senate/x.pdf")
    match = next(SenateJournal.total_vote_re.finditer(text))
    return journal.parse_match(match, 0)


class TestSenateJournal:
    OVERRIDE = "passing the item, notwithstanding the objections of His Excellency the Governor"

    def test_override_above_two_thirds_passes(self):
        assert _senate_journal_vote(self.OVERRIDE, 30, 8).result == "pass"

    def test_override_with_a_majority_under_two_thirds_fails(self):
        assert _senate_journal_vote(self.OVERRIDE, 24, 15).result == "fail"

    def test_ordinary_motion_keeps_the_margin_rule(self):
        vote = _senate_journal_vote("passing the bill to be engrossed", 24, 15)
        assert vote.result == "pass"


class TestVoteResult:
    @pytest.mark.parametrize(
        "yes,no,expected",
        [(26, 13, "pass"), (25, 13, "fail"), (0, 0, "fail"), (155, 0, "pass")],
    )
    def test_threshold_is_two_thirds_of_those_voting(self, yes, no, expected):
        assert vote_result("Motion (Tarr) to suspend the rules", yes, no) == expected

    def test_stated_outcome_wins_over_the_tally(self):
        assert vote_result("Emergency preamble adopted", 90, 60) == "pass"
        assert vote_result("Item 7004-0109 not passed over veto", 120, 35) == "fail"
        assert vote_result("Item 7004-0109, veto sustained", 100, 55) == "fail"

    def test_a_question_is_not_a_stated_outcome(self):
        """ "Shall ... be adopted?" names the proposition; the threshold decides."""
        motion = "H. 4240 Shall the emergency preamble be adopted?"
        assert vote_result(motion, 90, 60) == "fail"
        assert vote_result(motion, 120, 30) == "pass"

    def test_ordinary_motion_is_yeas_over_nays(self):
        assert vote_result("Passed to be engrossed", 80, 79) == "pass"
        assert vote_result("Amendment 12 adopted", 79, 80) == "fail"
