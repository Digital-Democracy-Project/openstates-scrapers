"""OPEN-922: a Massachusetts Senate journal entry with no tally is not a counted passage vote.

BROKER-617 (comment 23853) found nine Senate bill-chambers whose counted "passage" vote came from the Senate
journal with no tally and no member votes: S 137, S 1034, S 1884, S 2551, S 2561, S 2603, S 2608, S 3014 and
H 4003 (a House bill's Senate step). The legislature shows no Senate passage on those numbers.

Why: ma/votes.py's SenateJournal builds a vote event from every "(yeas N - nays M) [Yeas and Nays No. n]" line
but never sets the counts or the voters, and gave "passing the bill to be engrossed" the label "passage". The
same roll call is also stored by ma/bills.py, with its tally and voters, on the number the legislature files
it under. Checked against malegislature.gov (2026-11-26), for each of the nine the journal's roll call is a
real one filed on another bill:

  journal bill   roll call   legislature files it on
  S 2551         No. 60      S 2559  (journal: "printed as amended, see Senate, No. 2559"; excerpt below)
  S 137          No. 61      S 2563  (S 137: "Reprinted as amended, see S2563")
  S 1034         No. 62      S 2564  (S 1034: "Reprinted as amended, see S2564")
  S 2561         No. 66      S 2581  (S 2561: "Reprinted, as amended, see S2581")
  S 2603         No. 69      S 2616  (S 2603: "Reprinted, as amended see S2616")
  H 4003         No. 70      H 4530  (H 4003: "Reported, in part, by H4530")
  S 2608         No. 71      S 2619  (the only other roll call that day; S 2608's page 2 was not read)
  S 3014         No. 142     S 3028  (S 3014: "Reprinted, as amended, see S3028")
  S 1884         No. 187     H 4361  (H 4361: "Also based on S1884", "Passed to be engrossed -see Roll Call #187")

The journal text is a real excerpt (fixtures/ma_senate_journal_20250717_s2551.txt).
"""
import logging
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
from ma.votes import SenateJournal  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _journal_votes(text, date="2025-07-17"):
    journal = object.__new__(SenateJournal)
    journal.text = text
    journal.vote_date = date
    journal.session = "194th"
    journal.bill_id = None
    journal.logger = logging.getLogger(__name__)
    journal.source = mock.Mock(url="https://malegislature.gov/Journal/Senate/194/1002/sj07172025_1200PM.pdf")
    return [journal.parse_match(m, i) for i, m in enumerate(SenateJournal.total_vote_re.finditer(text))]


def _real_excerpt():
    with open(os.path.join(FIXTURES, "ma_senate_journal_20250717_s2551.txt"), encoding="utf-8") as f:
        return f.read().replace("–", "-")


def test_the_journals_passage_of_s2551_is_not_labelled_passage():
    (vote,) = _journal_votes(_real_excerpt())
    assert '"S 2551"' in vote.bill  # the journal names it as it stood, not S 2559 where the legislature files it
    assert vote.motion_text == "Passing the bill to be engrossed"
    assert vote.motion_classification == []


def test_that_journal_vote_carries_no_tally_and_no_voters():
    """The reason it cannot count: parse_match reads the numbers but never records them."""
    (vote,) = _journal_votes(_real_excerpt())
    assert vote.counts == [] and vote.votes == []


def _question_text(question):
    names = "\n".join("Yea{}, A.".format(chr(97 + i)) for i in range(5))
    return (
        "The bill (Senate, No. 1) was read. "
        + "x " * 400
        + "After debate, the question on {} was determined by a call of the yeas and nays, as follows, to wit "
        "(yeas 5 - nays 0) [Yeas and Nays No. 12]:\nYEAS.\n{}\n5.\nNAYS.\n0.\n"
    ).format(question, names)


def test_the_other_passage_questions_are_not_labelled_passage_either():
    for question in ("passing it to be enacted", "approving the plan"):
        (vote,) = _journal_votes(_question_text(question))
        assert vote.motion_classification == [], question
        assert vote.counts == [] and vote.votes == [], question  # the same no-tally property, so the same rule


def test_an_amendment_question_keeps_its_label():
    (vote,) = _journal_votes(_question_text("the adoption of the amendment"))
    assert vote.motion_classification == ["amendment"]


def test_the_real_roll_call_is_still_passage():
    """The control: the same roll call as ma/bills.py reads it on S 2559 (Roll Call #60, 39-0)."""
    assert classify_motion("ma", "Passed to be engrossed") == ["passage"]
