"""OPEN-543: North Carolina bill actions are stored oldest first.

The fixtures are the History cards of two real ncleg.gov bill pages, saved 2026-11-15: HB 116 and HB 147
of the 2025 session in the page's default order (newest first, a day's actions included), and HB 116 in
the site's own oldest-first view (/BillLookUp/2025/H116/True), which is the independent reference: the
scraper reads the default page, and what it stores must equal what the site shows oldest first.
No test makes a live call.
"""
import os
from unittest import mock

import lxml.html

from nc.bills import NCBillScraper
from openstates.scrape import Bill

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nc_open543")


def page(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def site_rows(name):
    """(date, actor, text) of each History row, in the order the page lists them."""
    doc = lxml.html.fromstring(page(name))
    rows = []
    for row in doc.xpath('//div[@class ="card-body"]/div[contains(@class, "row")]'):
        cols = row.xpath("div")
        text = (cols[5].text or "").strip() or cols[5].text_content().strip()
        rows.append((cols[1].text, text))
    return rows


def scrape(name, identifier):
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    bill = Bill(identifier, "2025", "A bill", chamber="lower")
    scraper.scrape_actions(bill, lxml.html.fromstring(page(name)))
    return bill.actions


def latest(actions):
    """openstates-core's rule (update_bill_fields): the last action, by order, on the latest date."""
    best = None
    for a in actions:
        if best is None or a["date"] >= best["date"]:
            best = a
    return best["description"]


def test_hb116_is_stored_in_the_sites_own_oldest_first_order():
    stored = [a["description"] for a in scrape("history_2025_H116.html", "HB 116")]
    oldest_first = [t for _, t in site_rows("history_2025_H116_oldest_first.html")]
    assert len(stored) == 65
    assert stored == oldest_first
    assert stored[0] == "Filed"


def test_hb116_latest_action_is_the_chaptering_not_the_ratification():
    """Stored newest first, the latest action was "Ratified" (the first step of 08/06); govbot and the
    site say "Ch. SL 2026-56"."""
    actions = scrape("history_2025_H116.html", "HB 116")
    assert latest(actions) == "Ch. SL 2026-56"
    assert [a["date"] for a in actions] == sorted(a["date"] for a in actions)


def test_hb116_same_day_actions_run_in_the_order_they_happened():
    """07/02/2026: the House adopted the conference report (roll call at 12:08), report #1 was
    reconsidered and withdrawn, then the Senate passed it (12:18). A stable date sort would keep the
    page's newest-first order inside the day."""
    day = [
        a["description"]
        for a in scrape("history_2025_H116.html", "HB 116")
        if a["date"] == "2026-07-02"
    ]
    assert day == [
        "Conf Report Adopted 2nd",
        "Conf Rpt #1 Recon/withdrawn",
        "Conf Report Passed 2nd",
    ]


def test_hb147_is_the_page_order_reversed():
    actions = scrape("history_2025_H147.html", "HB 147")
    rows = site_rows("history_2025_H147.html")
    assert [a["description"] for a in actions] == [t for _, t in reversed(rows)]
    assert latest(actions) == "Ch. SL 2026-57"
    assert actions[0]["date"] < actions[-1]["date"]


def test_scrape_bill_stores_the_actions_oldest_first():
    """The bill page reader itself goes through the reversed reader (the page is only the History card,
    so there are no versions, sponsors or votes)."""
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    response = mock.Mock(text=page("history_2025_H116.html"))
    with mock.patch.object(scraper, "get", return_value=response):
        (bill,) = list(scraper.scrape_bill("lower", "2025", "H116", "B", "An act"))
    assert [a["description"] for a in bill.actions] == [
        t for _, t in site_rows("history_2025_H116_oldest_first.html")
    ]
