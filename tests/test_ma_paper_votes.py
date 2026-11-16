"""OPEN-568: a roll call in a Massachusetts amendment paper's history is recorded on the paper's real bill.

Ramon (2026-11-16): "Ship now; move votes later". OPEN-509 labels amendment papers as amendments, so they leave
Explore and search; 87 recorded votes sat on 16 of them (the Senate budget debates on S 3 and S 4 hold 45). The
OPEN-509 pre-pass already knows each paper's real bill, so the scraper records the paper's roll calls there.

The pages are the real OPEN-509 fixtures (S3178 is the Senate Ways and Means redraft of H5576). The roll-call rows
are written from the stored action text of the real S 3178 and S 2543 histories (194th session); the history page
holding them is not in the fixtures.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from test_ma_amendment_papers import (  # noqa: E402
    EMPTY_HISTORY,
    HISTORY,
    SESSION,
    URL,
    make_scraper,
)
from openstates.utils import _make_pseudo_id  # noqa: E402

SENATE_ROW = (
    "<tr><td>7/23/2026</td><td>Senate</td><td>Amendment #41 (Tarr) rejected -see "
    "<a href='/RollCall/194/SenateRollCall211.pdf'>Roll Call #211</a> (Yeas 5 to Nays 34)</td></tr>"
)
HOUSE_ROW = (
    "<tr><td>7/23/2026</td><td>House</td><td>"
    "Amendment 8 rejected - 30 YEAS to 129 NAYS (See YEA and NAY No. 63 )</td></tr>"
)


def history(*rows):
    return "<table><tbody>{}</tbody></table>".format("".join(rows))


def make(rows, bill_list=None):
    """A scraper whose pre-pass has run, and whose S3178 and H5576 histories hold `rows`."""
    s = make_scraper()
    if bill_list is not None:
        s.bill_list = bill_list
    s.scrape_amendment_papers(SESSION)
    pages = dict(HISTORY)
    pages[(URL.format("S3178"), 2)] = history(*rows)
    pages[(URL.format("H5576"), 1)] = history(*rows)
    # page 1 of S3178 says how many pages there are; 2 holds the roll calls
    s.get_action_page = lambda url, n: lxml.html.fromstring(
        pages.get((url, n), EMPTY_HISTORY)
    )
    s.action_pages = lambda url: (
        s.get_action_page(url, n) for n in (1, 2) if (url, n) in pages
    )
    s.scrape_senate_vote = lambda vote, url: False  # the voters are not under test
    s.scrape_house_voters = lambda vote, pdf, session, n: None
    return s


def votes_of(s, number, chamber):
    meta = next(row for row in s.bill_list if row["BillNumber"] == number)
    return [o for o in s.scrape_bill(SESSION, meta, chamber) if o._type == "vote_event"]


def bill_ref(identifier, chamber):
    return _make_pseudo_id(
        identifier=identifier,
        from_organization__classification=chamber,
        legislative_session__identifier=SESSION,
    )


@pytest.mark.parametrize("row", [SENATE_ROW, HOUSE_ROW])
def test_a_roll_call_in_a_papers_history_is_recorded_on_the_real_bill(row):
    s = make([row])
    assert s.paper_parents == {"S 3178": "H 5576", "S 3208": "H 5576"}
    (vote,) = votes_of(s, "S3178", "upper")
    assert vote.bill == bill_ref("H 5576", "lower")
    assert vote.bill_identifier == "H 5576"
    assert vote.legislative_session == SESSION
    assert vote.extras["ddp_amendment_paper"] == "S3178"
    vote.validate()


def test_the_dedupe_key_still_names_the_paper_so_the_stored_row_moves_instead_of_doubling():
    (vote,) = votes_of(make([SENATE_ROW]), "S3178", "upper")
    # the key the 11-15 run stored on S 3178's row (Mac replica)
    assert (
        vote.dedupe_key
        == "http://malegislature.gov/RollCall/194/SenateRollCall211.pdf#S3178"
    )
    assert vote.motion_text == "Amendment #41 (Tarr) rejected"
    # an amendment vote, not passage: scorecard eligibility is unchanged
    assert vote.motion_classification == []


def test_the_paper_keeps_its_own_actions():
    s = make([SENATE_ROW])
    meta = next(row for row in s.bill_list if row["BillNumber"] == "S3178")
    bill = list(s.scrape_bill(SESSION, meta, "upper"))[-1]
    assert "Amendment #41 (Tarr) rejected -see Roll Call #211 (Yeas 5 to Nays 34)" in [
        " ".join(a["description"].split()) for a in bill.actions
    ]


def test_a_real_bills_own_roll_call_stays_on_it():
    (vote,) = votes_of(make([SENATE_ROW]), "H5576", "lower")
    assert vote.bill_identifier == "H5576"
    assert "ddp_amendment_paper" not in vote.extras


def test_a_paper_whose_bill_is_not_in_the_session_list_keeps_its_votes():
    # the import finds a vote's bill by its number; a number it cannot find would stop the import
    bill_list = [
        {"BillNumber": "S3178", "DocketNumber": None},
        {"BillNumber": "S3208", "DocketNumber": None},
    ]
    s = make([SENATE_ROW], bill_list=bill_list)
    assert s.paper_parents == {}
    (vote,) = votes_of(s, "S3178", "upper")
    assert vote.bill_identifier == "S3178"


def test_a_paper_linked_to_no_bill_keeps_its_votes():
    s = make([SENATE_ROW])
    s.paper_parents.clear()  # as for S 2618, whose history names no bill
    (vote,) = votes_of(s, "S3178", "upper")
    assert vote.bill_identifier == "S3178"
    assert "ddp_amendment_paper" not in vote.extras


def test_a_senate_bill_parent_is_looked_up_in_the_senate():
    s = make([HOUSE_ROW])
    s.paper_parents["S 3178"] = "S 2543"  # as for H 4271, the House's paper on S 2543
    (vote,) = votes_of(s, "S3178", "upper")
    assert vote.bill == bill_ref("S 2543", "upper")


@pytest.mark.parametrize("parent", ["HD 12", "SR 3"])
def test_a_parent_that_is_not_an_h_or_s_number_leaves_the_vote_on_the_paper(parent):
    s = make([SENATE_ROW])
    s.paper_parents["S 3178"] = parent
    (vote,) = votes_of(s, "S3178", "upper")
    assert vote.bill_identifier == "S3178"
