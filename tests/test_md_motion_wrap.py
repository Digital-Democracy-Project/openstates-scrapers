"""OPEN-832: a Maryland roll call whose motion runs over two lines keeps the whole motion.

The fixtures (md_open832/) are real 2026RS roll-call PDFs
(mgaleg.maryland.gov/2026RS/votes/<chamber>/<seq>.pdf) as pdftotext -layout gives them, which is
what convert_pdf(type="text") returns. They run through the votes scraper's own scrape_vote() with
no network. Read off the PDFs by hand:
- house 1280: HB 1372, "On Third Reading and Final Passage (Hse concurred)", then "(Emerg)" on the
  next line (131 Yeas, 1 Nays, 4 Not Voting, 0 Excused, 5 Absent).
- senate 1341: HB 139, "Bill is on Third Reading for Final Passage.", then the conferees line
  "Del. ..." (43, 0, 4, 0, 0).
- senate 0066: SB 5, "On Third Reading" with "(Const)" at the end of the line and again alone on
  the next line.
- house 0076: a one-line "On Third Reading"; house 0025: an amendment, "FLA Del. ... /613520/1".
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import md.votes  # noqa: E402
from md.votes import MDVoteScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "md_open832")


@pytest.fixture(autouse=True)
def offline_pdfs(monkeypatch):
    def convert_pdf(filename, type="xml"):
        assert type == "text"
        # ".../2026RS/votes/senate/1341.pdf" -> "2026rs_senate_1341.txt"
        session, _, chamber, seq = filename.lower().rsplit("/", 4)[-4:]
        name = f"{session}_{chamber}_{seq.replace('.pdf', '.txt')}"
        with open(os.path.join(FIXTURES, name), "rb") as f:
            return f.read()

    monkeypatch.setattr(md.votes, "convert_pdf", convert_pdf)


class _Votes(MDVoteScraper):
    def __init__(self):
        self.warnings = []

    def urlretrieve(self, url):
        return url, None

    def warning(self, msg, *args):
        self.warnings.append(msg)


def scrape_vote(chamber, seq):
    url = f"https://mgaleg.maryland.gov/2026RS/votes/{chamber}/{seq}.pdf"
    (vote,) = _Votes().scrape_vote(url, "2026")
    # the PDF's own spacing between a motion and a tag on the same line is not under test
    return vote.bill_identifier, re.sub(r"\s+", " ", vote.motion_text), vote


def test_tag_on_its_own_line_joins_the_motion():
    bill, motion, vote = scrape_vote("house", "1280")
    assert bill == "HB 1372"
    assert motion == "On Third Reading and Final Passage (Hse concurred) (Emerg)"
    assert vote.motion_classification == ["passage"]


def test_conferee_line_under_the_motion_is_not_the_motion():
    bill, motion, vote = scrape_vote("senate", "1341")
    assert bill == "HB 139"
    assert motion == "Bill is on Third Reading for Final Passage."
    assert vote.motion_classification == ["passage"]


def test_tag_the_motion_line_already_prints_is_not_repeated():
    bill, motion, vote = scrape_vote("senate", "0066")
    assert bill == "SB 5"
    assert motion == "On Third Reading (Const)"
    assert vote.motion_classification == ["passage"]


def test_one_line_motion_is_unchanged():
    bill, motion, vote = scrape_vote("house", "0076")
    assert motion == "On Third Reading"
    assert vote.motion_classification == ["passage"]


def test_amendment_motion_naming_a_delegate_is_kept():
    bill, motion, vote = scrape_vote("house", "0025")
    assert motion == "FLA Del. Buckel /613520/1"
    assert vote.motion_classification == ["amendment"]
