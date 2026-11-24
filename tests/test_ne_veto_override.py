"""BROKER-579 (Ramon, 2026-11-22: "Count overrides too"): a Nebraska whole-bill veto override vote is passage, so it
counts on the scorecard (and, as the chamber's latest passage vote, replaces the earlier final reading, the rule every
override state follows). Other motions and amendment votes still do not count.

Fixtures: the two real bill pages from nebraskalegislature.gov, fetched 2026-11-22 (19:54 UTC), unchanged. The expected
labels are written out by hand from each page's history:
* LB 1256 (2026): "Passed on Final Reading 49-0-0" (Apr 9), then the override roll call on the motion's own row,
  "Cavanaugh, J. MO585 failed" (Apr 17), whose filed row reads "MO585 That LB1256 becomes law notwithstanding the
  objections of the Governor filed".
* LB 319 (2025): the override roll call on the result row, "Failed to become law notwithstanding the objections of the
  Governor 24-24-1" (May 19); its motion, MO259, has no roll call of its own.
"""
import os
from unittest import mock

import lxml.html
from openstates.scrape import Bill

from ne.bills import NEBillScraper

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "broker579")


def votes(name, bill_id):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        page = lxml.html.fromstring(f.read())
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill(bill_id, "109", "A bill", chamber="legislature")
    with mock.patch.object(
        scraper, "lxmlize", return_value=lxml.html.fromstring("<div/>")
    ):
        return {
            v.motion_text.strip(): v.motion_classification
            for v in scraper.scrape_votes(bill, page, "legislature")
        }


def test_2026_the_override_on_its_motion_row_counts():
    labels = votes("ne_LB1256_2026.html", "LB 1256")
    assert labels["Cavanaugh, J. MO585 failed"] == ["passage"]
    assert labels["Passed on Final Reading 49-0-0"] == ["passage"]
    assert labels["Advanced to Enrollment and Review Initial"] == ["passage"]  # OPEN-876


def test_2025_the_override_on_its_result_row_counts():
    labels = votes("ne_LB319_2025.html", "LB 319")
    assert labels[
        "Failed to become law notwithstanding the objections of the Governor 24-24-1"
    ] == ["passage"]
    # every other roll call on the page that is not final reading or an advancement (OPEN-876) stays uncounted
    others = {
        text: label
        for text, label in labels.items()
        if "Final Reading" not in text
        and "notwithstanding" not in text
        and "dvanced to" not in text
    }
    assert others and all(label == [] for label in others.values()), others


def test_a_motion_vote_that_is_not_an_override_does_not_count():
    page = lxml.html.fromstring(
        '<table class="history">'
        "<tr><td>Apr 30, 2025</td><td>Cavanaugh, M. MO220 Bracket until June 9, 2025 filed</td><td></td></tr>"
        "<tr><td>Apr 30, 2025</td><td>Cavanaugh, M. MO220 failed</td>"
        '<td><a href="https://nebraskalegislature.gov/view_votes.php?KeyID=1">v</a></td></tr></table>'
    )
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill("LB 1", "109", "A bill", chamber="legislature")
    with mock.patch.object(
        scraper, "lxmlize", return_value=lxml.html.fromstring("<div/>")
    ):
        (vote,) = list(scraper.scrape_votes(bill, page, "legislature"))
    assert vote.motion_classification == []


def test_a_motion_filed_as_that_but_not_an_override_does_not_count():
    # Not seen: every "MO... That ..." motion stored for Nebraska (6, 2025-2026) is an override. This near-miss guards
    # the rule: only a motion that the bill "becomes law notwithstanding the objections of the Governor" counts.
    page = lxml.html.fromstring(
        '<table class="history">'
        "<tr><td>Apr 30, 2026</td><td>Smith MO999 That LB1 be placed on General File filed</td><td></td></tr>"
        "<tr><td>Apr 30, 2026</td><td>Smith MO999 prevailed</td>"
        '<td><a href="https://nebraskalegislature.gov/view_votes.php?KeyID=1">v</a></td></tr></table>'
    )
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill("LB 1", "109", "A bill", chamber="legislature")
    with mock.patch.object(
        scraper, "lxmlize", return_value=lxml.html.fromstring("<div/>")
    ):
        (vote,) = list(scraper.scrape_votes(bill, page, "legislature"))
    assert vote.motion_classification == []
