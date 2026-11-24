"""Tests for OPEN-868: a Hawaii committee's decision-making vote takes its result from its tally (more ayes than noes),
not from the "PASSED" in the recommendation it voted on.

Saved pages (data.capitol.hawaii.gov session/measure_indiv.aspx, read 2026-11-24): SB 3000 of 2026 (WAM's 4-9 vote on
03-04, followed by "The recommendation was not adopted.", and JDC's 5-0 the same day) and SB 95 of 2025 (JDC's 2-2
with 1 excused, also "not adopted"). Both failed votes were stored as "pass" before this rule.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi.bills import HIBillScraper, vote_result  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open868")


def _committee_votes(name, session):
    bill_id = name.split("-")[0]
    page = lxml.html.fromstring(open(os.path.join(FIX, name), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = {}
    bill = Bill(bill_id, session, "title", chamber="upper")
    out = []
    for v in scraper.parse_bill_actions_table(
        bill, table, bill_id, session, "https://example/", "upper"
    ):
        if "recommend" in v.motion_text:
            counts = {c["option"]: c["value"] for c in v.counts}
            committee = v.motion_text.split(" on ")[1].split()[0]
            out.append(
                (
                    v.start_date,
                    committee,
                    counts["yes"],
                    counts["no"],
                    counts["not voting"],
                    v.result,
                )
            )
    return out


def test_sb3000_wam_vote_that_lost_is_fail_and_jdc_vote_is_pass():
    votes = _committee_votes("SB3000-2026.html", "2026")
    assert ("2026-03-04", "WAM", 4, 9, 0, "fail") in votes
    assert ("2026-03-04", "JDC", 5, 0, 0, "pass") in votes
    # every committee vote on the page: pass exactly when the ayes outnumber the noes
    assert all(
        result == ("pass" if yes > no else "fail") for *_, yes, no, _x, result in votes
    )


def test_sb95_tied_jdc_vote_is_fail():
    votes = _committee_votes("SB95-2025.html", "2025")
    assert ("2025-02-21", "JDC", 2, 2, 1, "fail") in votes
    assert all(
        result == ("pass" if yes > no else "fail") for *_, yes, no, _x, result in votes
    )


# the recommendation forms stored on the Mac replica (2026-11-24), each with a vote that lost and one that won
COMMITTEE_TEXTS = [
    (
        "upper",
        "The committee(s) on  WAM recommend(s) that the measure be PASSED, WITH AMENDMENTS.  The votes in WAM were as follows: 4 Aye(s) ...",
    ),
    (
        "upper",
        "The committee(s) on CPN recommend(s) that the measure be PASSED, UNAMENDED.",
    ),
    (
        "upper",
        "The committee(s) on JDC recommend(s) that the measure be PASSED, WITH AMENDMENTS and be recommitted.",
    ),
    (
        "lower",
        "The committee on JHA recommend that the measure be PASSED, WITH AMENDMENTS. The votes were as follows: 5 Ayes ...",
    ),
    ("lower", "The committee on FIN recommend that the measure be PASSED, UNAMENDED."),
    (
        "lower",
        "The Conference Committee recommends that the measure be Passed, with Amendments.",
    ),
    (
        "upper",
        "The Conference committee recommends that the measure be PASSED, WITH AMENDMENTS.",
    ),
    (
        "lower",
        "The committee recommends that the measure pass with amendments, for recommittal for further consideration.",
    ),
    (
        "upper",
        "The recommendation of the committee(s) on HHS is to ADVISE AND CONSENT to the nomination(s).",
    ),
    ("upper", "The committee(s) on WLA recommend(s) that the measure be HELD."),
]


@pytest.mark.parametrize("chamber,text", COMMITTEE_TEXTS)
@pytest.mark.parametrize(
    "yes,no,expected", [(4, 9, "fail"), (2, 2, "fail"), (2, 1, "pass"), (5, 0, "pass")]
)
def test_a_committee_vote_is_decided_by_its_tally(chamber, text, yes, no, expected):
    assert vote_result(chamber, text, yes, no) == expected


@pytest.mark.parametrize(
    "text",
    [
        # floor lines that name a committee keep the stated outcome (they say what the chamber did)
        "Report adopted; referred to the committee(s) on FIN with none voting aye with reservations ...",
        "Passed Second Reading as amended in HD 1 and referred to the committee(s) on CPC with none voting no ...",
        # a recommendation named after the first sentence does not make the line a committee vote
        "Passed Third Reading. Ayes, 23. The committee recommends nothing.",
    ],
)
def test_floor_lines_keep_their_stated_outcome(text):
    assert vote_result("lower", text, 0, 10) == "pass"
