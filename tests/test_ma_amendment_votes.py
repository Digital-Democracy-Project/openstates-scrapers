"""OPEN-921: a Massachusetts amendment vote is not the bill's passage.

BROKER-617 (comment 23853) found five House bill-chambers whose counted "passage" vote was an amendment:

* H 4271, H 5349 and H 5478 (amendment papers) and H 61 (the House's concurrence in the Senate's amendment to
  H 58, filed under the amendment paper): rows written by the separate votes scraper (ma/votes.py), which
  labelled every House roll-call sheet "passage". The sheet names the paper first, then the question ("H. 4271 On
  adoption of amendment #8").
* H 4000 (the budget): ma/bills.py read a wrapped action ("Consolidated amendment C (Public Safety, Judiciary and
  Housing)\\r\\nadopted -\\r\\n154 YEAS to 2 NAYS") one line at a time, kept only "adopted", and the label rules
  read that as a resolution's adoption.

The texts are the real stored ones (Mac replica, 2026-11-26). The sheet text is the real fixture
(fixtures/ma_house_rollcall_194_221.txt) with its question line replaced.
"""
import os
import sys
from unittest import mock

import lxml.html
import pytest
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402
from ma.votes import HouseVoteRecordParser  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SEPARATOR = "MASSACHUSETTS HOUSE OF REPRESENTATIVES"


def _sheet_vote(question):
    with open(os.path.join(FIXTURES, "ma_house_rollcall_194_221.txt")) as f:
        text = f.read().replace("S. 3106 On Engrossment", question)
    parser = HouseVoteRecordParser(text.split(SEPARATOR, 1)[1], session="194th")
    return parser.createVoteEvent()


@pytest.mark.parametrize(
    "question",
    [
        "H. 4271 On adoption of amendment #8",
        "H. 4271 On adoption of amendment #6, changed",
        "H. 5349 On adoption of Consolidated Amendment A",
        "H. 5478 on adoption of amendment",
        "H. 61 Text of a further amendment to H.58",
    ],
)
def test_a_sheet_vote_on_an_amendment_is_not_passage(question):
    assert _sheet_vote(question).motion_classification == []


@pytest.mark.parametrize(
    "question",
    [
        "H. 4994 On passing to be engrossed",
        "S. 3106 On Engrossment",
        "H. 5699 , as amended On passing to be engrossed",
    ],
)
def test_a_sheet_vote_on_the_bills_own_passage_stays_passage(question):
    assert _sheet_vote(question).motion_classification == ["passage"]


def _house_votes(identifier, date, action_line):
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    bill = Bill(identifier, legislative_session="194th", title="t", classification="bill")
    page = lxml.html.fromstring(
        "<table><tbody><tr><td>{}</td><td>House</td><td>{}</td></tr></tbody></table>".format(
            date, action_line
        )
    )
    with mock.patch.object(scraper, "scrape_house_vote", return_value=True), mock.patch.object(
        scraper, "scrape_house_voters", return_value="pdf"
    ):
        votes = [v for v in scraper.scrape_action_page(bill, page) if type(v).__name__ == "VoteEvent"]
    return votes, bill


H4000_CONSOLIDATED_C = (
    "Consolidated amendment C (Public Safety, Judiciary and Housing)\r\nadopted -\r\n"
    "154 YEAS to 2 NAYS (See YEA and NAY No. 40 )"
)
H4000_CONSOLIDATED_B = (
    "Consolidated amendment B (Health and Human Services and\r\nAging and Independence) adopted -\r\n"
    "144 YEAS to 12 NAYS (See YEA and NAY No. 33 )"
)


def test_a_wrapped_budget_amendment_keeps_its_whole_motion_and_is_not_passage():
    (vote,), _ = _house_votes("H4000", "4/29/2025", H4000_CONSOLIDATED_C)
    assert vote.motion_text == "Consolidated amendment C (Public Safety, Judiciary and Housing) adopted"
    assert vote.motion_classification == []
    (vote,), _ = _house_votes("H4000", "4/28/2025", H4000_CONSOLIDATED_B)
    assert vote.motion_text == "Consolidated amendment B (Health and Human Services and Aging and Independence) adopted"
    assert vote.motion_classification == []


def test_the_action_is_still_recorded_as_the_source_wrote_it():
    _, bill = _house_votes("H4000", "4/29/2025", H4000_CONSOLIDATED_C)
    assert [a["description"] for a in bill.actions] == [H4000_CONSOLIDATED_C]


def test_a_wrapped_passage_vote_is_still_passage():
    """The control: the conference report's wrapped line (H 4227, 2025-06-18) reads the same on one line."""
    (vote,), _ = _house_votes(
        "H4227",
        "6/18/2025",
        "Committee of conference report accepted -\r\n150 YEAS to 3 NAYS (See YEA and NAY No. 56 )",
    )
    assert vote.motion_text == "Committee of conference report accepted"
    assert vote.motion_classification == ["passage"]


def test_a_resolution_adoption_is_still_passage():
    assert classify_motion("ma", "Adopted") == ["passage"]
