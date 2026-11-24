"""OPEN-876 (Ramon, 2026-11-24: "Yes, count them"): in Nebraska's one chamber a General File or Select File roll call
advances (or stops) the whole bill, so it is a vote on the bill and is typed passage, lost or carried. The broker's
"latest passage vote per chamber replaces earlier ones" then lets the final reading (or an override) replace it.
A motion to return a bill to Select File, and every amendment or motion vote, stays uncounted.

Fixtures: three real bill pages from nebraskalegislature.gov, fetched 2026-11-24, unchanged. Every history row that has
a roll call is on them:
* LB 135 (2025): General File "Advanced ... Initial" (Mar 12), then "Failed to advance ... for Engrossment" (Mar 28).
* LB 1072 (2026): Initial, Engrossment, "Returned to Select File", "Motion to return ... failed", "Reengrossment", final.
* LB 287 (2025): Initial, "Returned to Select File", "Readvanced ... for Engrossment", final reading, then an override.
"""
import os
from unittest import mock

import lxml.html
import pytest
from openstates.scrape import Bill

from ne.bills import NEBillScraper

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "open876")


def votes(name, bill_id):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        page = lxml.html.fromstring(f.read())
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill(bill_id, "109", "A bill", chamber="legislature")
    with mock.patch.object(
        scraper, "lxmlize", return_value=lxml.html.fromstring("<div/>")
    ):
        return list(scraper.scrape_votes(bill, page, "legislature"))


def labelled(name, bill_id, text):
    (vote,) = [v for v in votes(name, bill_id) if v.motion_text.strip() == text]
    return vote


@pytest.mark.parametrize(
    "name,bill_id,text,result",
    [
        ("ne_LB135_2025.html", "LB 135", "Advanced to Enrollment and Review Initial", "pass"),
        ("ne_LB135_2025.html", "LB 135", "Failed to advance to Enrollment and Review for Engrossment", "fail"),
        ("ne_LB1072_2026.html", "LB 1072", "Advanced to Enrollment and Review for Engrossment", "pass"),
        ("ne_LB1072_2026.html", "LB 1072", "Advanced to Enrollment and Review for Reengrossment", "pass"),
        ("ne_LB287_2025.html", "LB 287", "Readvanced to Enrollment and Review for Engrossment", "pass"),
    ],
)
def test_advancement_roll_calls_count_lost_or_carried(name, bill_id, text, result):
    vote = labelled(name, bill_id, text)
    assert vote.motion_classification == ["passage"]
    assert vote.result == result


@pytest.mark.parametrize(
    "name,bill_id,text",
    [
        ("ne_LB1072_2026.html", "LB 1072", "Returned to Select File for specific amendment"),
        ("ne_LB1072_2026.html", "LB 1072", "Motion to return to Select File failed"),
        ("ne_LB287_2025.html", "LB 287", "Returned to Select File for specific amendment"),
        ("ne_LB135_2025.html", "LB 135", "Holdcroft AM779 adopted"),
    ],
)
def test_returns_and_amendments_stay_uncounted(name, bill_id, text):
    assert labelled(name, bill_id, text).motion_classification == []


def test_the_final_reading_and_override_on_the_same_pages_are_unchanged():
    assert labelled(
        "ne_LB1072_2026.html",
        "LB 1072",
        "Passed on Final Reading with Emergency Clause 35-13-1",
    ).motion_classification == ["passage"]
    assert labelled(
        "ne_LB287_2025.html",
        "LB 287",
        "Failed to become law notwithstanding the objections of the Governor 24-24-1",
    ).motion_classification == ["passage"]
