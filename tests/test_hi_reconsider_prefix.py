"""OPEN-856: Hawaii's "Reconsider: " motion prefix goes on the chamber's first vote AFTER its reconsideration.

The status page lists actions newest first, and the scraper used to read it that way, so the prefix went on the
chamber's vote BEFORE the reconsideration. 109 stored roll calls carried it (Mac replica openstates_rds_repl_20260911,
2026-11-24; replaying the old rule over every stored Hawaii bill gives exactly those 109). Read oldest first, all 109
lose it and 59 roll calls gain it.

Pages: HB 1705 is the real saved status page of tests/fixtures/hi_open709 (read 2026-11-20) with its people data. SB 2383
and SB 3334 are their status tables rebuilt from the actions stored on the replica (tests/fixtures/hi_open856),
because data.capitol.hawaii.gov blocks automated reads. On SB 2383, PSM recommended "PASSED, WITH AMENDMENTS" on 02-02-26,
announced on 02-06-26 that it would reconsider that decision, and voted "HELD" on 02-11-26: the 02-11 vote is the
reconsidered one. The replica stores the prefix on the 02-02 vote.
"""
import json
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi import members as hi_members  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="module")
def members():
    os.environ[hi_members.PEOPLE_DIR_ENV] = os.path.join(
        FIXTURES, "hi_open709", "people"
    )
    try:
        return hi_members.load_members(None)
    finally:
        del os.environ[hi_members.PEOPLE_DIR_ENV]


def votes(path, members=None):
    """(date, chamber, motion text, row index from the dedupe_key) of each vote, in the order yielded."""
    bill_id = os.path.basename(path).split("-")[0].replace(".html", "")
    chamber = "upper" if bill_id.startswith("S") else "lower"
    page = lxml.html.fromstring(open(os.path.join(FIXTURES, path), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = members
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber=chamber)
    return [
        (
            v.start_date,
            json.loads(v.organization[1:])["classification"],
            v.motion_text,
            int(v.dedupe_key.split("#", 1)[0]),
        )
        for v in scraper.parse_bill_actions_table(
            bill, table, bill_id, "2026 Regular Session", "https://example/", chamber
        )
    ]


def prefixed(vs):
    return [
        (date, chamber, motion)
        for date, chamber, motion, _ in vs
        if motion.startswith("Reconsider: ")
    ]


def test_sb2383_the_committees_revote_carries_the_prefix():
    vs = votes("hi_open856/SB2383-2026-status.html")
    assert prefixed(vs) == [
        (
            "2026-02-11",
            "upper",
            "Reconsider: The committee(s) on  PSM recommend(s) that the measure be HELD.",
        )
    ]
    # the decision it reconsidered does not
    assert ("2026-02-02", "upper") in [
        (d, c) for d, c, m, _ in vs if not m.startswith("Reconsider: ")
    ]


def test_hb1705_the_houses_vote_after_its_reconsideration_carries_the_prefix(members):
    # the House reconsidered its disagreement (04-22-26), then agreed and passed Final Reading (04-23-26)
    vs = votes("hi_open709/HB1705.html", members)
    [(date, chamber, motion)] = prefixed(vs)
    assert (date, chamber) == ("2026-04-23", "lower")
    assert motion.startswith(
        "Reconsider: Passed Final Reading as amended in SD 2 with "
    )
    # stored with the prefix before: JHA's vote of 02-25-26, months before the reconsideration
    jha = [m for d, c, m, _ in vs if d == "2026-02-25"]
    assert jha == [
        "The committee on JHA recommend that the measure be PASSED, UNAMENDED."
    ]


def test_hb1705_without_people_data_no_vote_carries_it():
    # the Final Reading tally needs people data (OPEN-709); without it the prefix goes nowhere else
    assert prefixed(votes("hi_open709/HB1705.html")) == []


@pytest.mark.parametrize(
    "path",
    [
        "hi_open856/SB2383-2026-status.html",
        "hi_open856/SB3334-2026-status.html",
        "hi_open709/HB1705.html",
        "hi_open691/HB1800.html",
    ],
)
def test_votes_keep_the_tables_order_and_their_keys(path, members):
    # yielded in the page's order (row index ascending), each key holding its own row's index
    indexes = [i for *_, i in votes(path, members)]
    assert indexes == sorted(indexes) and len(set(indexes)) == len(indexes)


def test_sb3334_only_the_first_vote_after_the_reconsideration_carries_it():
    # WAM recommended passage on 03-02-26, announced on 03-03-26 that it would reconsider, and voted again on 03-05-26.
    # The Senate's Third Reading of 03-10-26 comes after that re-vote and is not a reconsideration.
    vs = votes("hi_open856/SB3334-2026-status.html")
    assert [(d, m) for d, c, m in prefixed(vs)] == [
        (
            "2026-03-05",
            "Reconsider: The committee(s) on  WAM recommend(s) that the measure be PASSED, WITH AMENDMENTS.",
        )
    ]
    third = [m for d, c, m, _ in vs if d == "2026-03-10"]
    assert len(third) == 1 and third[0].startswith(
        "Report Adopted; Passed Third Reading"
    )
