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


PAGINATOR = '<ul class="pagination pagination-sm"><li><a onclick="return reloadAjaxContent(2);">2</a></li></ul>'


def make(
    paper_rows,
    parent_rows=(PARENT_ROW,),
    bill_list=None,
    failing=(),
    failing_history=(),
    parent_pages=1,
):
    """A scraper whose pre-pass has run; S3178's history holds `paper_rows` (on its page 2 of 5), H5576's
    `parent_rows` (on page 1 of `parent_pages`). `failing` bills' pages and `failing_history` (bill, page) history
    pages fail this run, the way the site fails: scrape_bill and action_pages return quietly."""
    s = make_scraper()
    if bill_list is not None:
        s.bill_list = bill_list
    s.scrape_amendment_papers(SESSION)
    s.scrape_amendment_papers = lambda session: None  # scrape() would run it again
    s.scrape_bill_list = lambda session, start=None: None
    pages = dict(HISTORY)
    pages[(URL.format("S3178"), 2)] = history(*paper_rows)
    pages[(URL.format("H5576"), 1)] = history(*parent_rows) + (
        PAGINATOR if parent_pages > 1 else ""
    )
    failing_history = {(URL.format(n), page) for n, page in failing_history}
    s.get_action_page = lambda url, n: (
        None
        if (url, n) in failing_history
        else lxml.html.fromstring(pages.get((url, n), EMPTY_HISTORY))
    )
    s.scrape_senate_vote = lambda vote, url: False  # the voters are not under test
    s.scrape_house_voters = lambda vote, pdf, session, n: None
    fetch = s.fetch_bill_page
    for number in failing:
        s.prefetched_pages.pop(URL.format(number), None)
    s.fetch_bill_page = lambda url: (
        None if url.rsplit("/", 1)[1] in failing else fetch(url)
    )
    return s


def deleted_by_import(stored, votes):
    """openstates-core's delete rule (importers/vote_events.py): a stored vote is deleted when the run brings any
    vote for the bill it is stored on, and does not bring that vote again (matched by dedupe key)."""
    bills = {v.bill_identifier.replace(" ", "") for v in votes}
    brought = {v.dedupe_key for v in votes}
    return {key for key, bill in stored.items() if bill in bills and key not in brought}


# what the database holds after a clean run with this change: the moved vote and the real bill's own
PARENT_KEY = "https://malegislature.gov/Journal/House/194/2026/RollCalls#65#H5576"
STORED = {SENATE_KEY.format("S3178"): "H5576", PARENT_KEY: "H5576"}


def run(s, **kwargs):
    out = list(s.scrape(session=SESSION, **kwargs))
    bills = [o.identifier for o in out if o._type == "bill"]
    votes = [o for o in out if o._type == "vote_event"]
    return bills, votes


def on(votes, identifier):
    return [v for v in votes if v.bill_identifier == identifier]


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
    assert on(votes, "S3178") == []
    stored = {key.format("S3178"): "H5576", PARENT_KEY: "H5576"}
    assert deleted_by_import(stored, votes) == set()


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


# --- a member of the group cannot be read whole: none of the group's votes is sent, so none is deleted ---

GROUP_FAILURES = {
    "the real bill's page": dict(failing=("H5576",)),
    "the real bill's history, page 1": dict(failing_history=[("H5576", 1)]),
    "the real bill's history, page 2": dict(
        failing_history=[("H5576", 2)], parent_pages=2
    ),
    "the paper's page": dict(failing=("S3178",)),
    "the paper's history, page 1": dict(failing_history=[("S3178", 1)]),
    "the paper's history, page 2": dict(failing_history=[("S3178", 2)]),
    "the other paper's page": dict(failing=("S3208",)),
}


@pytest.mark.parametrize("failure", sorted(GROUP_FAILURES))
@pytest.mark.parametrize("bill_no", [None, "S3178"])
def test_when_any_member_fails_no_vote_of_the_group_is_sent_and_none_is_deleted(
    failure, bill_no
):
    s = make([SENATE_ROW], **GROUP_FAILURES[failure])
    bills, votes = run(s, bill_no=bill_no)
    assert votes == []
    assert deleted_by_import(STORED, votes) == set()


def test_the_clean_run_deletes_nothing_and_a_one_sided_run_would():
    # the simulation itself: what the import would do with the real bill's votes alone (before this round)
    s = make([SENATE_ROW])
    _, votes = run(s)
    assert deleted_by_import(STORED, votes) == set()
    own_only = [v for v in votes if "ddp_amendment_paper" not in v.extras]
    assert deleted_by_import(STORED, own_only) == {SENATE_KEY.format("S3178")}


def test_a_real_bill_whose_second_history_page_fails_is_recorded_as_failed():
    s = make([SENATE_ROW], failing_history=[("H5576", 2)], parent_pages=2)
    run(s)
    assert URL.format("H5576") in s.failed_histories
    assert "H 5576" not in s.group_read_whole


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
    s.group_of = {"S 3178": "S 2543", "S 2543": "S 2543"}  # as for H 4271 and S 2543
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


def test_two_unnumbered_roll_calls_of_one_paper_are_both_kept():
    # stripped of the bill, both keys would read as the paper's page: the guard in rollcall_of keeps them apart
    other = UNNUMBERED_ROW.replace(
        "#41 (Tarr) rejected", "#14 (Lewis) adopted"
    ).replace("Yeas 5 to Nays 34", "Yeas 31 to Nays 8")
    _, votes = run(make([UNNUMBERED_ROW, other]))
    assert len(on(votes, "H 5576")) == 2


def test_a_history_the_pre_pass_failed_to_read_but_this_pass_reads_counts_as_read():
    s = make([SENATE_ROW])
    s.failed_histories.add(
        URL.format("S3178")
    )  # as left by a pre-pass page that failed (the paper still linked)
    _, votes = run(s)
    assert len(on(votes, "H 5576")) == 1


def test_the_known_gap_a_paper_whose_page_fails_twice_is_not_recognised():
    # documented in PRIMITIVES and RUNBOOK: failing in the pre-pass too, S3178 is not known to be a paper, so it is
    # in no group; the real bill sends its own votes and the import deletes the vote moved from S3178 until the
    # next run brings it back. The run log names S3178 in a "Server Error on" line.
    s = make_scraper()
    fetch = s.fetch_bill_page
    s.fetch_bill_page = lambda url: None if url.endswith("/S3178") else fetch(url)
    s.scrape_amendment_papers(SESSION)
    assert "S 3178" not in s.paper_parents
    s.scrape_amendment_papers = lambda session: None
    s.scrape_bill_list = lambda session, start=None: None
    pages = {(URL.format("H5576"), 1): history(PARENT_ROW)}
    s.get_action_page = lambda url, n: lxml.html.fromstring(
        pages.get((url, n), EMPTY_HISTORY)
    )
    s.scrape_house_voters = lambda vote, pdf, session, n: None
    _, votes = run(s)
    assert [v.bill_identifier for v in votes] == ["H5576"]
    assert deleted_by_import(STORED, votes) == {SENATE_KEY.format("S3178")}
