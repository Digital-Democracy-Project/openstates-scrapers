"""OPEN-534: Louisiana bill actions are stored oldest first.

The site lists a bill's history newest first, a day's actions included. The rows in
tests/fixtures/la_2026/history_rows.json are real: HB 1, HB 1000 and HB 1040 of the 2026
Regular Session as the Mac replica stores them (2026-11-14), which is the site's own row order
(date, chamber, action). The test puts them back in the bill page's history table and runs the
scraper's own reader over it. No test makes a live call.
"""
import json
import os
import sys
from html import escape
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from la.bills import LABillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "la_2026", "history_rows.json"
)
with open(FIXTURE) as f:
    SITE_ROWS = json.load(f)


def history_page(rows):
    """The bill page's history table: a header row with 'Journal', then one row per action."""
    body = "".join(
        f"<tr><td>{d}</td><td>{c}</td><td></td><td>{escape(t)}</td></tr>"
        for d, c, t in rows
    )
    return lxml.html.fromstring(
        "<html><body><table><tr><th>Date</th><th>Chamber</th><th>Journal Page</th>"
        f"<th>Action</th></tr>{body}</table></body></html>"
    )


def scrape(identifier):
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.start_year = "2026"
    bill = Bill(identifier, "2026", "A bill", chamber="lower")
    scraper.scrape_actions(bill, history_page(SITE_ROWS[identifier]))
    return bill.actions


def latest(actions):
    """openstates-core's rule (update_bill_fields): the last action, by order, on the latest date."""
    best = None
    for a in actions:
        if best is None or a["date"] >= best["date"]:
            best = a
    return best["description"]


@pytest.mark.parametrize("identifier", sorted(SITE_ROWS))
def test_stored_order_is_the_site_order_reversed(identifier):
    actions = scrape(identifier)
    assert [a["description"] for a in actions] == [
        t for _, _, t in reversed(SITE_ROWS[identifier])
    ]
    assert actions[0]["date"] < actions[-1]["date"]


def test_hb1_starts_with_the_prefile_and_ends_with_the_effective_date():
    actions = scrape("HB 1")
    assert actions[0]["description"] == "Prefiled."
    assert actions[0]["date"] == "2026-02-20"
    assert actions[-1]["description"] == "Effective date: 07/01/2026."
    # today (newest first) the replica's latest action is the signature, not the effective date
    assert latest(actions) == "Effective date: 07/01/2026."
    assert [a["date"] for a in actions] == sorted(a["date"] for a in actions)


def test_hb1_same_day_actions_run_in_the_order_they_happened():
    """05/29: called from the calendar, returned to it, then the concurrence vote. A stable
    date sort would keep the site's newest-first order inside the day."""
    day = [a["description"] for a in scrape("HB 1") if a["date"] == "2026-05-29"]
    assert day == [
        "Called from the calendar.",
        "Read by title, returned to the calendar.",
        "Read by title, roll called, yeas 101, nays 0, Senate amendments concurred in.",
    ]


def test_hb1000_house_passage_comes_before_senate_receipt_on_the_same_day():
    day = [a["description"] for a in scrape("HB 1000") if a["date"] == "2026-04-27"]
    assert day[0].startswith("Read third time by title, roll called on final passage")
    assert day[1].startswith("Received in the Senate.")
    assert latest(scrape("HB 1000")) == "Effective date: 05/29/2026."


def test_hb1040_keeps_the_site_sequence_where_a_journal_date_runs_back():
    """94 of the replica's 2,616 Louisiana bills have one row dated later than the next one
    (the President's signature is journaled on the day the Governor signs). The plain reverse
    keeps the site's sequence: enrolled, signed by the President, sent to the Governor, signed."""
    texts = [a["description"] for a in scrape("HB 1040")]
    tail = texts[-5:]
    assert tail == [
        "Enrolled and signed by the Speaker of the House.",
        "Signed by the President of the Senate on 5/7/2026.",
        "Sent to the Governor for executive approval.",
        "Signed by the Governor. Becomes Act No. 92.",
        "Effective date: 05/11/2026.",
    ]


def test_scrape_bill_page_stores_the_actions_oldest_first():
    """The bill page reader itself uses the reversed reader (only the history table is real)."""
    rows = SITE_ROWS["HB 1"]
    table = lxml.html.tostring(history_page(rows).xpath("//table")[0]).decode()
    page = lxml.html.fromstring(
        "<html><body>"
        "<a id='ctl00_PageBody_LinkAuthor'>McFarland</a>"
        "<span id='ctl00_PageBody_LabelShortTitle'>APPROPRIATIONS:  Provides</span>"
        "<span id='ctl00_PageBody_LabelBillID'>HB 1</span>"
        "<table><tr><td id='ctl00_PageBody_MenuDocumentsn0'>Authors</td></tr></table>"
        "<div id='ctl00_PageBody_MenuDocumentsn0Items'><a href='a'>McFarland (primary)</a></div>"
        f"{table}</body></html>"
    )
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.start_year = "2026"
    with mock.patch.object(scraper, "lxmlize", return_value=page):
        (bill,) = list(scraper.scrape_bill_page("lower", "2026", "u", "HB"))
    assert [a["description"] for a in bill.actions] == [t for _, _, t in reversed(rows)]
