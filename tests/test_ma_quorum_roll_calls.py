"""Tests for OPEN-567: a Massachusetts quorum roll call is not a vote on a bill.

A quorum roll call counts who is present. The two in the 194th were stored as House
votes on bills (No. 249 on H 5620, No. 154 on S 2581) and showed on the site as
unanimous "yes" votes, because their text also says "YEA and NAY", the House
trigger. OPEN-176 had already kept them out of the Senate branch.

The action lines are the real stored lines (Mac replica, 2026-11-15).
"""
import os
import sys
from unittest import mock

import lxml.html
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

H5620_QUORUM = "Quorum Roll Call - 149 YEAS to 0 NAYS (See YEA and NAY No. 249 )"
S2581_QUORUM = "Quorum Roll Call - 154 YEAS to 0 NAYS (See YEA and NAY No. 154 )"


def _scrape_row(identifier, date, action_line, chamber="House"):
    """Run one bill-history row through `scrape_action_page`; return (votes, bill).

    The roll-call PDFs are not fetched: voters are not what is under test.
    """
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    bill = Bill(
        identifier,
        legislative_session="194th",
        title="test bill",
        classification="bill",
    )
    page = lxml.html.fromstring(
        "<table><tbody><tr><td>{}</td><td>{}</td><td>{}</td></tr></tbody></table>".format(
            date, chamber, action_line
        )
    )
    with mock.patch.object(
        scraper, "scrape_house_vote", return_value=True
    ), mock.patch.object(scraper, "scrape_senate_vote", return_value=True):
        votes = [
            item
            for item in scraper.scrape_action_page(bill, page)
            if type(item).__name__ == "VoteEvent"
        ]
    return votes, bill


class TestQuorumRollCallsMakeNoVote:
    def test_h5620_quorum_roll_call_249_is_not_a_vote(self):
        votes, _ = _scrape_row("H 5620", "7/30/2026", H5620_QUORUM)
        assert votes == []

    def test_s2581_quorum_roll_call_154_is_not_a_vote(self):
        votes, _ = _scrape_row("S 2581", "4/8/2026", S2581_QUORUM)
        assert votes == []

    def test_the_quorum_action_itself_is_still_recorded(self):
        """Only the vote is dropped; the bill's history keeps the line."""
        _, bill = _scrape_row("H 5620", "7/30/2026", H5620_QUORUM)
        assert [a["description"] for a in bill.actions] == [H5620_QUORUM]

    def test_a_real_house_roll_call_on_the_same_bill_still_makes_a_vote(self):
        """The control: H 5620's enactment roll call, the same day, same sheet."""
        votes, _ = _scrape_row(
            "H 5620",
            "7/30/2026",
            "Enacted - 137 YEAS to 21 NAYS (See YEA and NAY No. 251 )",
        )
        assert len(votes) == 1
        assert votes[0].motion_text == "Enacted"

    def test_a_real_senate_roll_call_still_makes_a_vote(self):
        votes, _ = _scrape_row(
            "S 2581",
            "7/31/2025",
            "Passed to be engrossed -see   Roll Call #66 (Yeas 38 to Nays 2)",
            chamber="Senate",
        )
        assert len(votes) == 1
