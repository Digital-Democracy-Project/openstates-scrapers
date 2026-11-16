"""OPEN-575: North Carolina roll-call times keep their a.m./p.m.

The pages are the real ncleg.gov vote cards in tests/fixtures/nc_votes (2025 session, saved 2026-11-15).
The times are checked against ncleg.gov's own roll-call lists (RollCallVoteHistory/2025/H and /S), which
print the same roll calls as "8/4/2026 5:51 PM". No 2025 roll call falls between midnight and 1 a.m. (0 of
1,503 on those lists), so the 12:xx a.m. case is the real HB 116 card with one time changed. No live call.
"""
import os
from unittest import mock

import lxml.html

from nc.bills import NCBillScraper
from openstates.scrape import Bill

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nc_votes")


def start_dates(name, edit=None):
    with open(os.path.join(FIXTURES, f"votes_2025_{name}.html"), encoding="utf-8") as f:
        text = f.read()
    if edit:
        text = text.replace(*edit)
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    bill = Bill("HB 1", "2025", "A bill", chamber="lower")
    transcript = mock.Mock(text="<html><body></body></html>")
    with mock.patch.object(scraper, "get", return_value=transcript):
        votes = scraper.scrape_votes(bill, lxml.html.fromstring(text))
        return {v.dedupe_key: v.start_date for v in votes}


def test_pm_vote():
    # HB 116, House roll call 794: "8/4/2026 5:51 p.m." (stored 05:51 before the fix)
    assert start_dates("H116")["[H]-794"] == "2026-08-04T17:51:00-04:00"


def test_am_vote():
    # HB 147, House roll call 802: "8/5/2026 11:26 a.m."
    assert start_dates("H147")["[H]-802"] == "2026-08-05T11:26:00-04:00"


def test_twelve_pm_vote_is_noon():
    # HB 116, House roll call 784: "7/2/2026 12:08 p.m."
    assert start_dates("H116")["[H]-784"] == "2026-07-02T12:08:00-04:00"


def test_twelve_am_vote_is_just_after_midnight():
    dates = start_dates("H116", edit=("7/2/2026 12:08 p.m.", "7/2/2026 12:08 a.m."))
    assert dates["[H]-784"] == "2026-07-02T00:08:00-04:00"
