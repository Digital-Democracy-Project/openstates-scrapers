"""Tests for OPEN-900: a Hawaii roll call that fails the whole measure on Third or Final Reading is passage.

The six status pages in fixtures/hi_open900 are the real ones (data.capitol.hawaii.gov, read 2026-11-25) of the
six measures whose only or last floor vote was such a roll call; the texts below are what the stored votes hold.
"""
import json
import os
import re
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import _config, classify_motion  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from hi import members as hi_members  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open900")
# the seated members the House tally needs: the OPEN-709 fixture (2026 session)
PEOPLE = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open709", "people")


@pytest.fixture(scope="module")
def members():
    os.environ[hi_members.PEOPLE_DIR_ENV] = PEOPLE
    try:
        return hi_members.load_members(None)
    finally:
        del os.environ[hi_members.PEOPLE_DIR_ENV]


# (page, bill, chamber the measure started in, chamber that voted, start of the failed vote's text)
SIX = [
    ("HB1516-2026.html", "HB1516", "lower", "upper", "Failed to pass Final Reading."),
    ("HB1550-2026.html", "HB1550", "lower", "upper", "Failed to pass Final Reading."),
    ("SB3263-2026.html", "SB3263", "upper", "upper", "Failed to pass Final Reading."),
    ("HB1919-2026.html", "HB1919", "lower", "lower", "Failed to pass Third Reading with Representative(s)"),
    ("HB2413-2026.html", "HB2413", "lower", "upper", "Failed to pass Third Reading."),
    ("SB319-2026.html", "SB319", "upper", "upper", "Failed to pass Third Reading."),
]


def _votes(name, bill_id, chamber, members):
    page = lxml.html.fromstring(open(os.path.join(FIXTURES, name), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = members
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber=chamber)
    return list(
        scraper.parse_bill_actions_table(
            bill, table, bill_id, "2026 Regular Session", "https://example/" + name, chamber
        )
    )


@pytest.mark.parametrize("name,bill_id,bill_chamber,voter,text", SIX)
def test_the_failed_final_vote_of_each_real_bill_is_passage(name, bill_id, bill_chamber, voter, text, members):
    failed = [v for v in _votes(name, bill_id, bill_chamber, members) if v.motion_text.startswith("Failed to pass")]
    assert len(failed) == 1
    vote = failed[0]
    assert vote.motion_text.startswith(text)
    assert json.loads(vote.organization[1:])["classification"] == voter
    assert vote.result == "fail"
    assert vote.motion_classification == ["passage"]


POSITIVE = [
    "Failed to pass Third Reading.",
    "Failed to pass Final Reading.",
    "Failed to pass Third Reading with Representative(s) Amato, Grandinetti voting aye with reservations; "
    "Representative(s) Belatti, Chun voting no (2) and none excused (0).",
    "Reconsider: Failed to pass Third Reading.",
    "failed to pass final reading.",
]

# what the rule leaves alone, each on purpose
NEGATIVE = [
    "Nominee(s) failed to be confirmed.",  # a confirmation, not a bill reading
    "Failed to pass Second Reading.",  # moves the bill on, like "Passed Second Reading"
    "Failed to pass.",  # no reading named
    "The committee(s) on WAM recommend(s) that the measure be PASSED, WITH AMENDMENTS.",  # committee, even when it fails
    "Failed to adopt the amendment.",
    "Motion to recommit failed.",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_failed_reading_is_passage(text):
    assert classify_motion("hi", text) == ["passage"]


@pytest.mark.parametrize("text", NEGATIVE[:3] + NEGATIVE[4:])
def test_other_failed_texts_stay_unlabelled(text):
    assert classify_motion("hi", text) == []


def test_committee_vote_stays_committee_passage():
    assert classify_motion("hi", NEGATIVE[3]) == ["committee-passage"]


def test_rule_is_in_the_passage_list_and_names_no_bill_or_member():
    patterns = _config["jurisdictions"]["hi"]["passage"]
    assert any(re.search(p, "failed to pass final reading.") for p in patterns)
    assert not any(re.search(r"\b[hs][bcmr]\s?\d|amato|belatti", p, re.I) for p in patterns)
