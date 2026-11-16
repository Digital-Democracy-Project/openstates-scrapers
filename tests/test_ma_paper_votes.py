"""OPEN-568: a roll call in a Massachusetts amendment paper's history is recorded on the paper's real bill.

Ramon (2026-11-16): "Ship now; move votes later". OPEN-509 labels amendment papers as amendments, so they leave
Explore and search; 87 recorded votes sat on 16 of them (the Senate budget debates on S 3 and S 4 hold 45). The
OPEN-509 pre-pass already knows each paper's real bill, so the scraper records the paper's roll calls there.

The import deletes every stored vote of a bill that gets any vote in the run unless the run brings it again, so a
paper and its real bill are always scraped together, and a paper's vote goes on the real bill only once that bill
has been yielded in the same run (review of 2026-11-16, findings 1-3).

The pages are the real OPEN-509 fixtures (S3178 is the Senate Ways and Means redraft of H5576; S3208 a floor
amendment to it). The roll-call rows are written from the stored action text of the real S 3178 and S 2543
histories (194th session); the history page holding them is not in the fixtures.
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
from openstates.scrape import Bill  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

SENATE_ROW = (
    "<tr><td>7/23/2026</td><td>Senate</td><td>Amendment #41 (Tarr) rejected -see "
    "<a href='/RollCall/194/SenateRollCall211.pdf'>Roll Call #211</a> (Yeas 5 to Nays 34)</td></tr>"
)
HOUSE_ROW = (
    "<tr><td>7/23/2026</td><td>House</td><td>"
    "Amendment 8 rejected - 30 YEAS to 129 NAYS (See YEA and NAY No. 63 )</td></tr>"
)
# the real bill's own roll call, a different one
PARENT_ROW = (
    "<tr><td>7/23/2026</td><td>House</td><td>"
    "Passed to be engrossed - 136 YEAS to 23 NAYS (See YEA and NAY No. 65 )</td></tr>"
)
SENATE_KEY = "http://malegislature.gov/RollCall/194/SenateRollCall211.pdf#{}"
HOUSE_KEY = "https://malegislature.gov/Journal/House/194/2026/RollCalls#63#{}"


def history(*rows):
    return "<table><tbody>{}</tbody></table>".format("".join(rows))


def make(paper_rows, parent_rows=(PARENT_ROW,), bill_list=None, failing=()):
    """A scraper whose pre-pass has run; S3178's history holds `paper_rows`, H5576's `parent_rows`."""
    s = make_scraper()
    if bill_list is not None:
        s.bill_list = bill_list
    s.scrape_amendment_papers(SESSION)
    s.scrape_amendment_papers = lambda session: None  # scrape() would run it again
    s.scrape_bill_list = lambda session, start=None: None
    pages = dict(HISTORY)
    pages[(URL.format("S3178"), 2)] = history(*paper_rows)
    pages[(URL.format("H5576"), 1)] = history(*parent_rows)
    s.get_action_page = lambda url, n: lxml.html.fromstring(
        pages.get((url, n), EMPTY_HISTORY)
    )
    s.action_pages = lambda url: (
        s.get_action_page(url, n) for n in (1, 2) if (url, n) in pages
    )
    s.scrape_senate_vote = lambda vote, url: False  # the voters are not under test
    s.scrape_house_voters = lambda vote, pdf, session, n: None
    fetch = s.fetch_bill_page
    for (
        number
    ) in failing:  # a bill whose page fails this run (scrape_bill returns quietly)
        s.prefetched_pages.pop(URL.format(number), None)
    s.fetch_bill_page = lambda url: (
        None if url.rsplit("/", 1)[1] in failing else fetch(url)
    )
    return s


def run(s, **kwargs):
    out = list(s.scrape(session=SESSION, **kwargs))
    bills = [o.identifier for o in out if o._type == "bill"]
    votes = [o for o in out if o._type == "vote_event"]
    return bills, votes


def on(votes, identifier):
    return [v for v in votes if v.bill_identifier == identifier]


def paper_ref(s, votes):
    """The votes that name the paper S3178 by its scraped Bill (as before OPEN-568)."""
    return [v for v in votes if v.bill_identifier == "S3178"]


def bill_ref(identifier, chamber):
    return _make_pseudo_id(
        identifier=identifier,
        from_organization__classification=chamber,
        legislative_session__identifier=SESSION,
    )


# --- the move ---


@pytest.mark.parametrize("row,key", [(SENATE_ROW, SENATE_KEY), (HOUSE_ROW, HOUSE_KEY)])
def test_a_roll_call_in_a_papers_history_is_recorded_on_the_real_bill(row, key):
    s = make([row])
    bills, votes = run(s)
    assert s.paper_parents == {"S 3178": "H 5576", "S 3208": "H 5576"}
    (moved,) = [v for v in votes if "ddp_amendment_paper" in v.extras]
    assert moved.bill == bill_ref("H 5576", "lower")
    assert moved.legislative_session == SESSION
    assert moved.extras["ddp_amendment_paper"] == "S3178"
    # the key the 11-15 run stored on the paper's row: the import moves that row, it does not add one
    assert moved.dedupe_key == key.format("S3178")
    # an amendment vote, not passage: scorecard eligibility is unchanged
    assert moved.motion_classification == []
    moved.validate()
    assert len(on(votes, "H5576")) == 1  # the real bill's own vote, still on it
    assert paper_ref(s, votes) == []


def test_the_paper_keeps_its_own_actions():
    s = make([SENATE_ROW])
    out = list(s.scrape(session=SESSION))
    (paper,) = [o for o in out if o._type == "bill" and o.identifier == "S3178"]
    assert "Amendment #41 (Tarr) rejected -see Roll Call #211 (Yeas 5 to Nays 34)" in [
        " ".join(a["description"].split()) for a in paper.actions
    ]


# --- finding 1: a paper and its real bill are scraped together ---


@pytest.mark.parametrize("bill_no", ["S3178", "H5576", "S3208"])
def test_a_single_bill_run_scrapes_the_whole_paper_group(bill_no):
    bills, votes = run(make([SENATE_ROW]), bill_no=bill_no)
    assert sorted(bills) == ["H5576", "S3178", "S3208"]
    assert len(on(votes, "H5576")) == 1  # the real bill's own vote is brought again
    assert len(on(votes, "H 5576")) == 1  # and the moved one


def test_a_single_bill_run_of_an_ordinary_bill_scrapes_only_it():
    bills, _ = run(make([SENATE_ROW]), bill_no="H1")
    assert bills == ["H1"]


def test_a_one_chamber_run_adds_the_real_bill_from_the_other_chamber():
    bills, votes = run(make([SENATE_ROW]), chamber="upper")
    assert sorted(bills) == ["H5576", "S3178", "S3208"]
    assert len(on(votes, "H 5576")) == 1


# --- findings 1c and 2: the real bill is not yielded in this run ---


def test_a_real_bill_whose_page_fails_leaves_the_vote_on_the_paper():
    s = make([SENATE_ROW], failing=("H5576",))
    bills, votes = run(s)
    assert "H5576" not in bills
    (vote,) = votes
    assert vote.bill_identifier == "S3178"  # on the paper, as before OPEN-568
    assert "ddp_amendment_paper" not in vote.extras
    assert vote.dedupe_key == SENATE_KEY.format("S3178")  # the moved row comes back
    vote.validate()


def test_a_real_bill_missing_from_the_list_leaves_the_vote_on_the_paper():
    bill_list = [
        {"BillNumber": "S3178", "DocketNumber": None},
        {"BillNumber": "S3208", "DocketNumber": None},
    ]
    s = make([SENATE_ROW], bill_list=bill_list)
    bills, votes = run(s)
    assert "H5576" not in bills
    assert [v.bill_identifier for v in votes] == ["S3178"]


def test_a_paper_linked_to_no_bill_keeps_its_votes():
    s = make([SENATE_ROW])
    s.paper_parents.clear()  # as for S 2618, whose history names no bill
    _, votes = run(s)
    assert [v.bill_identifier for v in votes if v.bill_identifier != "H5576"] == [
        "S3178"
    ]


@pytest.mark.parametrize("parent", ["HD 12", "SR 3"])
def test_a_parent_that_is_not_an_h_or_s_number_leaves_the_vote_on_the_paper(parent):
    s = make([SENATE_ROW])
    s.paper_parents["S 3178"] = parent
    _, votes = run(s)
    assert "S3178" in [v.bill_identifier for v in votes]


def test_a_senate_bill_parent_is_looked_up_in_the_senate():
    s = make([])
    s.paper_parents["S 3178"] = "S 2543"  # as for H 4271, the House's paper on S 2543
    paper = Bill("S3178", legislative_session=SESSION, chamber="upper", title="x")
    vote = s.paper_vote_event(
        paper,
        chamber="lower",
        start_date="2025-07-16",
        motion_text="Amendment 8 rejected",
        result="fail",
        classification=[],
    )
    assert vote.bill == bill_ref("S 2543", "upper")


# --- finding 3: one roll call cited by both histories ---


@pytest.mark.parametrize("bill_no", [None, "S3178"])  # real bill first; paper first
def test_a_roll_call_both_histories_cite_is_kept_once_on_the_real_bill(bill_no):
    s = make([SENATE_ROW], parent_rows=[SENATE_ROW])
    _, votes = run(s, bill_no=bill_no)
    (vote,) = votes
    assert vote.bill_identifier == "H5576"
    assert vote.dedupe_key == SENATE_KEY.format("H5576")


def test_a_real_bill_whose_history_fails_leaves_the_vote_on_the_paper():
    # its own votes were not read again, so a vote moved onto it would make the import delete them
    s = make([SENATE_ROW])
    get_page, pages = s.get_action_page, s.action_pages
    s.get_action_page = lambda url, n: None if "H5576" in url else get_page(url, n)
    s.action_pages = lambda url: (
        MABillScraper.action_pages(s, url) if "H5576" in url else pages(url)
    )
    bills, votes = run(s)
    assert "H5576" in bills
    assert [v.bill_identifier for v in votes] == ["S3178"]


# a Senate roll call whose action gives no number: keyed by the bill's own page (never seen in the 194th)
UNNUMBERED_ROW = (
    "<tr><td>7/23/2026</td><td>Senate</td><td>Amendment #41 (Tarr) rejected -see "
    "Roll Call (Yeas 5 to Nays 34)</td></tr>"
)


@pytest.mark.parametrize("bill_no", [None, "S3178"])
def test_a_roll_call_without_a_number_is_never_taken_for_another(bill_no):
    # nothing says the two entries are one roll call (two votes on one day can share a tally), so both are kept
    s = make([UNNUMBERED_ROW], parent_rows=[UNNUMBERED_ROW])
    _, votes = run(s, bill_no=bill_no)
    assert sorted(v.bill_identifier for v in votes) == ["H 5576", "H5576"]
    assert len({v.dedupe_key for v in votes}) == 2
