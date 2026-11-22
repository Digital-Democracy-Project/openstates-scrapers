"""Tests for OPEN-771: Rhode Island yielded every bill on a search-range boundary twice.

The scraper lists a session's bills by number range on status.rilegislature.gov, 250 at a
time. The site's range includes both ends: "8250 to 8500" for 2026 lists 251 bills and
"8500 to 8750" starts with House Bill 8500 again (both read 2026-11-22). The old ranges
shared their end number, so HB 8500 (and 10 more 2026 boundary bills) was yielded twice and
the import stopped on it ("already imported as HB 8500").

tests/fixtures/ri_open771/bills_2026.html holds real 2026 bill entries cut from those search
results: one near the start of the House numbers (7001), each boundary the scraper's ranges
meet at (7250 ... 8500) and the bills either side of 8500. The fake site below answers a
range search the way the real one does: every entry whose number is in the range, both ends
included.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ri.bills as ri_bills  # noqa: E402
from ri.bills import RIBillScraper  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "ri_open771", "bills_2026.html"
)
ENTRY = re.compile(r"(?=<div>(?:House|Senate) [A-Za-z ]+No\. <a)")
TRAILER = "<br /><br /><div><table"
FROM = "ctl00$rilinContent$txtBillFrom"
TO = "ctl00$rilinContent$txtBillTo"


def _site():
    """(head, {number: entry html}, tail) of the fixture's results page."""
    page = open(FIXTURE, encoding="utf-8").read()
    head, *entries = ENTRY.split(page)
    cut = entries[-1].index(TRAILER)
    tail = entries[-1][cut:]
    entries[-1] = entries[-1][:cut]
    by_number = {int(re.search(r"No\. <a[^>]*>(\d+)", e).group(1)): e for e in entries}
    return head, by_number, tail


class _Response:
    def __init__(self, text):
        self.text = text


def _scrape(monkeypatch, chamber="lower", session="2026"):
    """scrape_bills against the fake site: (bills, ranges searched, scraper)."""
    head, by_number, tail = _site()
    searched = []

    def post(url, data):
        lo, hi = int(data[FROM]), int(data[TO])
        searched.append((lo, hi))
        hits = [by_number[n] for n in sorted(by_number) if lo <= n <= hi]
        return _Response(head + "".join(hits) + tail)

    monkeypatch.setattr(ri_bills, "get_default_headers", lambda page: {})
    scraper = object.__new__(RIBillScraper)
    scraper.info = scraper.warning = lambda *a, **k: None
    scraper.post = post
    scraper._bill_id_by_type = {}
    return list(scraper.scrape_bills(chamber, session, {})), searched, scraper


def test_fixture_is_the_real_boundary_entries():
    _, by_number, _ = _site()
    assert sorted(by_number) == [7001, 7250, 7500, 7750, 8000, 8250, 8499, 8500, 8501]


def test_each_bill_is_yielded_once(monkeypatch):
    bills, _, _ = _scrape(monkeypatch)
    ids = [b.identifier for b in bills]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    # nothing is dropped either: every entry on the site comes back
    assert sorted(ids) == [
        "HB7250",
        "HB7500",
        "HB7750",
        "HB8000",
        "HB8250",
        "HB8499",
        "HB8500",
        "HB8501",
        "HR7001",
    ]


def test_search_ranges_do_not_overlap(monkeypatch):
    _, searched, _ = _scrape(monkeypatch)
    numbers = [n for lo, hi in searched for n in range(lo, hi + 1)]
    assert len(numbers) == len(set(numbers))
    # and leave no gap between them
    for (_, hi), (lo, _) in zip(searched, searched[1:]):
        if lo != 7000:  # the House's second start number (bill_start_numbers)
            assert lo == hi + 1


def test_boundary_bill_keeps_its_version_actions_and_sponsors(monkeypatch):
    bills, _, scraper = _scrape(monkeypatch)
    (hb8500,) = [b for b in bills if b.identifier == "HB8500"]
    assert hb8500.title.endswith("OFFICE OF HEALTH AND HUMAN SERVICES")
    assert [v["note"] for v in hb8500.versions] == ["8500"]
    assert [a["date"] for a in hb8500.actions] == [
        "2026-05-01",
        "2026-05-22",
        "2026-05-28",
    ]
    assert hb8500.sponsorships[0]["name"] == "Donovan"
    # the votes pass still finds it
    assert scraper._bill_id_by_type[("lower", "8500")] == "HB8500"
