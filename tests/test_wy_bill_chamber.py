"""OPEN-820: a Wyoming bill's origin chamber comes from its number's first letter.

`"lower" if bill_json["bill"][0] else "upper"` was always "lower" (the letter is always truthy), so every Senate File
and Senate Joint Resolution of 2026 (135 of 335 bills) was stored as a House bill. HB/HJ are the House's, SF/SJ the
Senate's, as scrape_chamber already reads billType.

The fixtures are real lsoservice.wyoleg.gov/api/BillInformation/2026/<bill> answers: HB 10, SF 1 (wy_open769) and
HJ 1, SJ 4 (wy_open820, read 2026-11-24).
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill, VoteEvent  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def scraped(fixture_dir, bill):
    """scrape_bill() over one saved 2026 API answer: every object it yields."""
    with open(os.path.join(FIXTURES, fixture_dir, f"2026_{bill}.json"), "rb") as f:
        body = f.read()
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(content=body)
    return list(scraper.scrape_bill(bill, "2026"))


@pytest.mark.parametrize(
    "fixture_dir,bill,chamber",
    [
        ("wy_open769", "HB0010", "lower"),
        ("wy_open820", "HJ0001", "lower"),
        ("wy_open769", "SF0001", "upper"),
        ("wy_open820", "SJ0004", "upper"),
    ],
)
def test_origin_chamber_follows_the_bill_number(fixture_dir, bill, chamber):
    (stored,) = [o for o in scraped(fixture_dir, bill) if isinstance(o, Bill)]
    assert stored.identifier == bill
    assert stored.from_organization == '~{"classification": "%s"}' % chamber


def test_senate_joint_resolution_vote_keeps_its_own_chamber():
    """SJ 4's one roll call is the Senate's failed introduction (16-15); only the bill's origin changed."""
    (vote,) = [o for o in scraped("wy_open820", "SJ0004") if isinstance(o, VoteEvent)]
    assert vote.organization == '~{"classification": "upper"}'
    assert vote.result == "fail"
