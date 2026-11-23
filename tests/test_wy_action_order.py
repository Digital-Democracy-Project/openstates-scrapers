"""OPEN-780: Wyoming's bill actions are stored oldest first (Alabama's OPEN-528 pattern).

lsoservice.wyoleg.gov/api/BillInformation/<session>/<bill> lists "billActions" newest first, and every one of the 335
bills of 2026 was stored in that order. The scraper reads the list backwards: a stable sort by date alone would scramble
same-day actions (215 of the 335 bills of 2026), and reversing keeps the source's own sequence within a day.

The fixtures are the real API answers of tests/fixtures/wy_open769 (read 2026-11-22); their "billActions" match the
service's answer of 2026-11-23.
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wy_open769")


def source(bill):
    with open(os.path.join(FIXTURES, f"2026_{bill}.json"), encoding="utf-8") as f:
        return json.load(f)


def stored_actions(bill):
    """scrape_bill() over one saved 2026 API answer: the bill's actions in the order they are stored."""
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    body = json.dumps(source(bill)).encode("utf-8")
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(content=body)
    (stored,) = [b for b in scraper.scrape_bill(bill, "2026") if isinstance(b, Bill)]
    return stored.actions


def test_sf2_actions_run_from_numbering_to_chapter():
    actions = stored_actions("SF0002")
    texts = [a["description"] for a in actions]
    assert texts[:3] == [
        "Bill Number Assigned",
        "S Received for Introduction",
        "S Introduced and Referred to S02 - Appropriations 31-0-0-0-0",
    ]
    assert texts[-3:] == [
        "H Speaker Signed SEA No. 0001",
        "Governor Signed SEA No. 0001 ",
        "Assigned Chapter Number 23",
    ]
    dates = [a["date"] for a in actions]
    assert dates == sorted(dates)


def test_same_day_actions_keep_the_source_sequence():
    """SF 1, HB 10 and SF 2 each have days with several actions: the stored order is exactly the source's reversed."""
    for bill in ("SF0001", "SF0002", "HB0010"):
        expected = [a["statusMessage"] for a in source(bill)["billActions"]][::-1]
        assert [a["description"] for a in stored_actions(bill)] == expected
    # SF 2's 2026-02-19: the House passes it just after midnight, it is numbered, then the President signs it
    feb19 = [
        a["description"]
        for a in stored_actions("SF0002")
        if a["date"].date().isoformat() == "2026-02-19"
    ]
    assert feb19 == [
        "H 3rd Reading:Passed 55-2-5-0-0",
        "Assigned Number SEA No. 0001",
        "S President Signed SEA No. 0001",
    ]
