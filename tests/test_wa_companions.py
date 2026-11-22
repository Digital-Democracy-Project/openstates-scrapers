"""OPEN-647: Washington lists each bill's companion (wa:Companions in the legislature's web service; "Companion bill:"
on the bill page), and the scraper stores it as a companion link with the legislature's label.

The fixtures are the legislature's own answers, fetched 2026-11-22 04:15 UTC from wslwebservices.leg.wa.gov, unchanged except that
the bulk list (GetLegislationIntroducedSince, 5,245 records) is cut to the records of five bills, in their real order:
* HB 1024 / SB 5300: the companion is on the original version's record only (SHB 1024, 2SHB 1024, SSB 5300 list none);
* HB 1052 / SB 5038: HB 1052's first record lists no companion, its engrossed record does (13 bills are like this);
* HB 1003: no companion.
GetLegislation_2025-26_1198.xml is the per-bill answer for HB 1198 (the operating budget; companion SB 5167), which
the scraper reads when a bill is not in the bulk list. The expected links are written out by hand from those files.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from wa import Washington  # noqa: E402
from wa.bills import WABillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wa_open647")
BULK = "GetLegislationIntroducedSince_2024-11-01_trimmed.xml"


class _Response:
    def __init__(self, name):
        with open(os.path.join(FIXTURES, name), "rb") as f:
            self.content = f.read()


def make_scraper():
    s = WABillScraper(Washington(), "/tmp/")
    s.biennium = "2025-26"
    s._start_dt = None
    s._legislation = None
    s.versions, s.documents = {}, {}
    s.fetched = []

    def get(url, *args, **kwargs):
        s.fetched.append(url)
        if "GetLegislationIntroducedSince" in url:
            return _Response(BULK)
        if "GetLegislation?" in url and url.endswith("=1198"):
            return _Response("GetLegislation_2025-26_1198.xml")
        raise AssertionError(f"unexpected fetch {url}")

    s.get = get
    s.scrape_sponsors = lambda bill: None
    s.scrape_actions = lambda *a, **k: None
    s.scrape_votes = lambda bill: iter(())
    return s


def related(s, bill_id):
    [bill] = list(s.scrape_bill("lower", "2025-2026", bill_id, 2025))
    return [
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    ]


def test_the_companion_on_the_original_version_is_kept():
    s = make_scraper()
    assert related(s, "HB 1024") == [
        ("SB 5300", "2025-2026", "companion", "Companion bill")
    ]
    assert related(s, "SB 5300") == [
        ("HB 1024", "2025-2026", "companion", "Companion bill")
    ]


def test_a_companion_listed_only_on_a_later_record_is_kept():
    s = make_scraper()
    assert related(s, "HB 1052") == [
        ("SB 5038", "2025-2026", "companion", "Companion bill")
    ]
    assert related(s, "SB 5038") == [
        ("HB 1052", "2025-2026", "companion", "Companion bill")
    ]


def test_a_bill_with_no_companion_gets_no_link():
    assert related(make_scraper(), "HB 1003") == []


def test_a_bill_read_one_at_a_time_keeps_its_companion():
    s = make_scraper()
    assert related(s, "HB 1198") == [
        ("SB 5167", "2025-2026", "companion", "Companion bill")
    ]
    assert any(u.endswith("=1198") for u in s.fetched)
