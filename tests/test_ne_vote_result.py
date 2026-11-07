from unittest import mock

import lxml.html
import pytest
from openstates.scrape import Bill

from ne.bills import NEBillScraper, vote_passed

# OPEN-504: every text below is a real Nebraska history-row text stored on the replica
# (2026-11-07), except the three marked "not seen", which guard the near-misses the ticket names.

PASSES = [
    "Advanced to Enrollment and Review Initial",
    "Advanced to Enrollment and Review for Engrossment",
    "Readvanced to Enrollment and Review for Engrossment",
    "Passed on Final Reading 49-0-0",
    "Passed on Final Reading 47-1*-1",
    "Passed on Final Reading with Emergency Clause 49-0-0",
    "Passed on Final Reading with Emergency Clause stricken 27-21*-1",
    # Amendments and motions: stored as fail before OPEN-504.
    "Adopted",
    "Cavanaugh, J. AM1007 adopted",
    "Bosn FA1146 adopted",
    "Government, Military and Veterans Affairs AM1008 adopted",
    "Banking, Commerce and Insurance AM1187 adopted",
    "Meyer, G. AM2562 adopted",
    "von Gillern AM1020 adopted",
    "Ballard MO137 prevailed",
    "Cavanaugh, M. MO206 prevailed",
    # A motion to return that carried (Ramon, 2026-11-07).
    "Returned to Select File for specific amendment",
]

FAILS = [
    "Failed to advance to Enrollment and Review Initial",
    "Failed to advance to Enrollment and Review for Engrossment",
    "Failed on Final Reading 31-17*-1",
    "Failed on Final Reading with Emergency Clause 27-21*-1",
    "Failed to become law notwithstanding the objections of the Governor 24-24-1",
    "Motion to return to Select File failed",
    "Hansen AM1097 lost",
    "Raybould FA27 lost",
    "Brandt MO275 failed",
    "Hansen AM1097 not adopted",  # not seen
    "Hansen AM1097 withdrawn",  # not seen
    "Hansen MO101 withdrawn",  # not seen
]


@pytest.mark.parametrize("text", PASSES)
def test_pass_texts(text):
    assert vote_passed(text) is True


@pytest.mark.parametrize("text", FAILS)
def test_fail_texts(text):
    assert vote_passed(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Bosn FA1146 adopted",
        "Ballard MO137 prevailed",
        "Returned to Select File for specific amendment",
    ],
)
def test_scrape_votes_stores_adopted_and_prevailed_as_pass(text):
    """The scraper itself must use the rule, not only the helper."""
    page = lxml.html.fromstring(
        f'<table class="history"><tr><td>Mar 4, 2025</td><td>{text}</td>'
        '<td><a href="https://nebraskalegislature.gov/view_votes.php?KeyID=1">v</a></td></tr></table>'
    )
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill("LB1", "2025-2026", "A bill", chamber="legislature")
    with mock.patch.object(
        scraper, "lxmlize", return_value=lxml.html.fromstring("<div/>")
    ):
        (vote,) = list(scraper.scrape_votes(bill, page, "legislature"))
    assert vote.result == "pass"
