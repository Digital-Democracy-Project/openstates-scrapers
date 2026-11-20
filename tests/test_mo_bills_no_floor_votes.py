"""OPEN-702: the Missouri bills scraper makes no floor votes.

The House bill XML's RollCall nodes carry totals only, with no member names, and the
"Truly Agreed To and Finally Passed" roll call (the Senate's vote on a House bill) carries no
chamber marker, so it was filed under the House. Every floor vote now comes, with names, from
the votes scraper (OPEN-696). Committee reports ("Reported Do Pass (H)") have no other source
and still become votes here. Fixtures are real 2026 files in tests/fixtures/mo_2026/ (the SB 835
bill page and its BillText and Amendments pages were saved on 2026-11-20 for this ticket).
"""
import os
import sys
from unittest import mock

import lxml.etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from mo.bills import MOBillScraper  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mo_2026")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def scrape_hb2885():
    scraper = MOBillScraper(jurisdiction="x", datadir="/tmp")
    xml = lxml.etree.fromstring(fixture("HB2885.xml"))
    out = list(scraper.parse_house_bill(xml, "HB 2885", "2026", "R", "2026"))
    bills = [o for o in out if isinstance(o, Bill)]
    votes = [o for o in out if isinstance(o, VoteEvent)]
    assert len(bills) == 1 and len(bills) + len(votes) == len(out)
    return bills[0], votes


def test_hb2885_floor_roll_calls_make_no_vote():
    _, votes = scrape_hb2885()
    motions = [v.motion_text for v in votes]
    assert motions == [
        "Reported Do Pass (H) - AYES: 12 NOES: 1 PRESENT: 0",
        "Reported Do Pass (H) - AYES: 11 NOES: 0 PRESENT: 0",
        "Reported Do Pass (H) - AYES: 7 NOES: 0 PRESENT: 0",
    ]
    for v in votes:
        assert v.organization == '~{"classification": "lower"}'
        assert v.counts == [] and v.votes == []
    # The House's 112-27 and the Senate's 27-0 belong to the votes scraper alone.
    assert not any("Third Read" in m or "Truly Agreed" in m for m in motions)


def test_hb2885_floor_actions_keep_their_text_and_totals():
    bill, _ = scrape_hb2885()
    descriptions = [a["description"] for a in bill.actions]
    assert len(descriptions) == 42
    assert "Third Read and Passed (H) - AYES: 112 NOES: 27 PRESENT: 0" in descriptions
    final = [a for a in bill.actions if a["description"].startswith("Truly Agreed")]
    assert [(a["description"], a["organization_id"]) for a in final] == [
        (
            "Truly Agreed To and Finally Passed - AYES: 27 NOES: 0 PRESENT: 0",
            '~{"classification": "lower"}',
        )
    ]
    assert final[0]["classification"] == ["passage"]


def test_sb835_bill_page_makes_no_vote():
    """SB 835 through the Senate bill path the scraper runs (_parse_senate_billpage, which
    fetches the bill page, then its Actions, BillText and Amendments handlers). Only the bill
    comes back. The old _get_votes (totals read from action text) had no caller and is gone."""
    assert not hasattr(MOBillScraper, "_get_votes")
    url = "https://www.senate.mo.gov/BillTracking/Bills/BillInformation?year=2026&billid=417"
    pages = {
        url: "SB835.html",
        f"{url}&handler=Actions": "SB835_actions.html",
        f"{url}&handler=BillText": "SB835_billtext.html",
        f"{url}&handler=Amendments": "SB835_amendments.html",
    }

    def get(u):
        body = fixture(pages[u])
        return mock.Mock(content=body, text=body.decode("utf-8"))

    scraper = MOBillScraper(jurisdiction="x", datadir="/tmp")
    scraper._session_id = "2026"
    with mock.patch.object(scraper, "get", side_effect=get) as fetched:
        out = list(scraper._parse_senate_billpage(url, "SB 835", "", "2026"))
    assert sorted(c.args[0] for c in fetched.call_args_list) == sorted(pages)
    assert [type(o) for o in out] == [Bill]
    bill = out[0]
    assert bill.identifier == "SB 835"
    assert bill.actions[-1]["description"] == "Signed by Governor"
