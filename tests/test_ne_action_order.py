"""OPEN-535: Nebraska bill actions are stored oldest first.

The site lists a bill's history newest first, a day's actions included. The rows in
tests/fixtures/ne_109/history_rows.json are real: LB 1, LB 1105 and LR 384 of the 109th
Legislature as the Mac replica stores them (2026-11-14), which is the site's own row order
(date, action). The test puts them back in the bill page's history table and runs the scraper's
own reader over it. No test makes a live call.
"""
import json
import os
import sys
from html import escape
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ne.bills import NEBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "ne_109", "history_rows.json"
)
with open(FIXTURE) as f:
    SITE_ROWS = json.load(f)


def history_table(rows):
    body = "".join(f"<tr><td>{d}</td><td>{escape(t)}</td></tr>" for d, t in rows)
    return (
        '<table class="history"><thead><tr><th>Date</th><th>Action</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def scrape(identifier):
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill(identifier, "109", "A bill", chamber="legislature")
    page = lxml.html.fromstring(
        f"<html><body>{history_table(SITE_ROWS[identifier])}</body></html>"
    )
    scraper.scrape_actions(bill, page)
    return bill


def latest(actions):
    """openstates-core's rule (update_bill_fields): the last action, by order, on the latest date."""
    best = None
    for a in actions:
        if best is None or a["date"] >= best["date"]:
            best = a
    return best["description"]


@pytest.mark.parametrize("identifier", sorted(SITE_ROWS))
def test_stored_order_is_the_site_order_reversed_and_dates_never_go_down(identifier):
    actions = scrape(identifier).actions
    assert [a["description"] for a in actions] == [
        t for _, t in reversed(SITE_ROWS[identifier])
    ]
    dates = [a["date"] for a in actions]
    assert dates == sorted(dates)
    assert actions[0]["description"] == "Date of introduction"


def test_lb1_same_day_actions_run_in_the_order_they_happened():
    """02-21-2025: passed, signed by the President/Speaker, presented to the Governor. A stable
    date sort would keep the site's newest-first order inside the day."""
    actions = scrape("LB 1").actions
    day = [a["description"] for a in actions if a["date"] == "2025-02-21"]
    assert day == [
        "Passed on Final Reading with Emergency Clause 48-0-1",
        "President/Speaker signed",
        "Presented to Governor on  February 21, 2025",
    ]
    assert latest(actions) == "Approved by Governor on February 25, 2025"
    assert actions[-1]["organization_id"] == '~{"classification": "executive"}'


def test_lb1105_ends_on_its_postponement():
    """Read newest first, the end-of-session postponement came first and the stage rule saw
    the bill fail, then move on (988 bills on the replica)."""
    actions = scrape("LB 1105").actions
    assert actions[-1]["description"] == "Indefinitely postponed"
    assert latest(actions) == "Indefinitely postponed"


def test_lr384_same_day_hearing_notice_then_its_cancellation():
    actions = scrape("LR 384").actions
    day = [a["description"] for a in actions if a["date"] == "2026-08-14"]
    assert day == [
        "Notice of hearing for October 30, 2026",
        "Notice of hearing for October 30, 2026 (cancel)",
    ]
    assert latest(actions) == "Notice of hearing for November 05, 2026"


def test_lr384_extras_hold_the_latest_referral_and_hearing_notice():
    """The extras are set by the last matching row read, so they now name the latest referral
    and hearing notice (they named the earliest when the rows were read newest first)."""
    extras = scrape("LR 384").extras
    assert extras["NE_REF_COM"] == "Government, Military and Veterans Affairs Committee"
    assert extras["NE_REF_DATE"] == "November 05, 2026"


def bill_page(rows):
    """A minimal bill page around the real history table: the title and introducer sit where
    bill_info's xpaths look, and one vote link sits on the history's passage row."""
    table = history_table(rows).replace(
        "<td>Passed on Final Reading with Emergency Clause 48-0-1</td>",
        "<td><a href='https://nebraskalegislature.gov/view_votes.php?KeyID=1'>"
        "Passed on Final Reading with Emergency Clause 48-0-1</a></td>",
    )
    return lxml.html.fromstring(
        "<html><body><div></div><div></div><div>"
        "<div></div><div><div></div><div><div>"
        "<div></div><div></div><div><div><ul><li><a>Hallstrom</a></li></ul></div></div>"
        "</div></div></div></div>"
        f"<div class='main-content'><h2>LB1 - Change provisions</h2>{table}</div>"
        "</body></html>"
    )


def test_bill_info_stores_oldest_first_and_votes_stay_with_the_legislature():
    """bill_info itself uses the reversed reader. Votes took the oldest action's actor (always
    "legislature"); read oldest first that would be the Governor's row, so it is now fixed."""
    rows = SITE_ROWS["LB 1"]
    page = bill_page(rows)
    vote_page = lxml.html.fromstring("<div/>")
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    with mock.patch.object(scraper, "lxmlize", side_effect=[page, vote_page]):
        bill, vote = list(scraper.bill_info("u", "109", "m"))
    assert [a["description"] for a in bill.actions] == [t for _, t in reversed(rows)]
    assert vote.organization == '~{"classification": "legislature"}'
