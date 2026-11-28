"""OPEN-954: a Maryland Senate floor amendment taken on a bill at its third reading is an amendment,
not the third reading; and every roll call carries the legislature's own sequence number.

The fixtures (md_open954/) are real 2026RS Senate roll-call PDFs as pdftotext -layout gives them (what
convert_pdf(type="text") returns), run through the votes scraper's scrape_vote() and the bills scraper's
parse_vote_pdf() with no network. Read off the PDFs by hand:
- 1372: HB 1222, "Floor Amendment" printed above "Bill is on Third Reading for Final Passage." (15 yeas,
  29 nays; the legislature's bill page calls it a rejected floor amendment); 1374: the third reading
  itself, same bill, same day (41, 0).
- 1126 and 1156: HB 1430's third reading (34, 8), "Motion Reconsider Third Reading", then the third
  reading again (33, 8): same day, no time.
- 0241: an ordinary amendment, "Floor Amendment Folden /943023/1" as the last line.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import md.bills  # noqa: E402
import md.votes  # noqa: E402
from md.bills import MDBillScraper  # noqa: E402
from md.votes import MDVoteScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "md_open954")


def _convert_pdf(filename, type="xml"):
    assert type == "text"
    session, _, chamber, seq = filename.lower().rsplit("/", 4)[-4:]
    name = f"{session}_{chamber}_{seq.replace('.pdf', '.txt')}"
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


@pytest.fixture(autouse=True)
def offline_pdfs(monkeypatch):
    monkeypatch.setattr(md.votes, "convert_pdf", _convert_pdf)
    monkeypatch.setattr(md.bills, "convert_pdf", _convert_pdf)


class _Votes(MDVoteScraper):
    def __init__(self):
        pass

    def urlretrieve(self, url):
        return url, None

    def warning(self, msg, *args):
        pass


class _Bills(MDBillScraper):
    def __init__(self):
        pass

    def urlretrieve(self, url):
        return url, None


def url_of(seq, folder="senate"):
    return f"http://mgaleg.maryland.gov/2026RS/votes/{folder}/{seq}.pdf"


def votes_scraper_vote(seq):
    (vote,) = _Votes().scrape_vote(url_of(seq), "2026")
    return vote


def bills_scraper_vote(seq):
    bill = Bill("HB 1", "2026", "t")
    # the bill pages link the chamber folder capitalised ("votes/Senate/"), which parse_vote_pdf reads
    return _Bills().parse_vote_pdf(url_of(seq, "Senate"), bill)


PARSERS = [votes_scraper_vote, bills_scraper_vote]


@pytest.mark.parametrize("parse", PARSERS)
def test_floor_amendment_above_the_third_reading_question_is_an_amendment(parse):
    vote = parse("1372")
    assert re.sub(r"\s+", " ", vote.motion_text) == (
        "Floor Amendment Bill is on Third Reading for Final Passage."
    )
    assert vote.motion_classification == ["amendment"]
    assert vote.result == "fail"


@pytest.mark.parametrize("parse", PARSERS)
def test_the_third_reading_on_the_same_bill_stays_passage(parse):
    vote = parse("1374")
    assert vote.motion_text == "Bill is on Third Reading for Final Passage."
    assert vote.motion_classification == ["passage"]


@pytest.mark.parametrize("parse", PARSERS)
def test_amendment_naming_its_sponsor_is_unchanged(parse):
    vote = parse("0241")
    assert vote.motion_text == "Floor Amendment Folden /943023/1"
    assert vote.motion_classification == ["amendment"]


@pytest.mark.parametrize("parse", PARSERS)
def test_amend_tag_on_a_third_reading_stays_passage(parse):
    # "(Amend)" alone on a line above the question is a tag, not an amendment vote
    vote = parse("1126")
    assert vote.motion_classification == ["passage"]


@pytest.mark.parametrize("parse", PARSERS)
def test_roll_call_carries_the_sequence_number_in_its_chambers_key(parse):
    assert parse("1126").extras == {"senate-rollcall-num": "1126"}
    assert parse("1156").extras == {"senate-rollcall-num": "1156"}
    # a number below 1000 is stored without its leading zero
    assert parse("0241").extras == {"senate-rollcall-num": "241"}


def test_house_roll_call_uses_the_house_key():
    assert md.votes.rollcall_number_extras(
        "lower", "http://mgaleg.maryland.gov/2026RS/votes/house/0076.pdf"
    ) == {"house-rollcall-num": "76"}


def test_the_later_of_two_same_day_third_readings_has_the_higher_number():
    first, second = votes_scraper_vote("1126"), votes_scraper_vote("1156")
    assert first.start_date == second.start_date
    assert int(first.extras["senate-rollcall-num"]) < int(
        second.extras["senate-rollcall-num"]
    )


@pytest.mark.parametrize("seq", ["0241", "1126", "1156", "1372", "1374"])
def test_the_number_is_the_pdfs_own_seq_no_header(seq):
    with open(os.path.join(FIXTURES, f"2026rs_senate_{seq}.txt")) as f:
        header = re.match(r"SEQ NO\. (\d+)", f.readline()).group(1)
    assert votes_scraper_vote(seq).extras["senate-rollcall-num"] == header
