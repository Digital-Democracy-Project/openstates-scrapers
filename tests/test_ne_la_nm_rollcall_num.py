"""OPEN-685: Nebraska, Louisiana and New Mexico give a vote its day only, so two roll calls on a bill in one chamber on
the same day tie. Each scraper now writes the number that puts them in the order they were taken, under the extras key
the broker reads into Motion.rollcall_num (any key ending "rollcall-num"; OPEN-628 did the same for MI, WA, VA, AZ).

Real cases, checked against each legislature's own record (2026-11-20):
- Nebraska LB 48, 2025-05-30: "Failed on Final Reading with Emergency Clause 26-22*-1" (KeyID 12956), then "Passed on
  Final Reading with Emergency Clause stricken 27-21*-1" (KeyID 12957).
- Louisiana SB 487, House, 2026-05-19: FINAL PASSAGE (#1393), 3:37 PM, then FINAL PASSAGE (#1400), 4:01 PM.
- New Mexico HB 253, Senate, 2026-02-18: RCS 158 (without the emergency clause, 26-15), then RCS 173 (with it, 39-0);
  the PDFs in fixtures/nm_open685 are nmlegis.gov's own, unchanged. HB 164's House PDF prints "RCS# 128" on one line.
"""
import json
import os
import sys
from unittest import mock

import fitz
import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from la.bills import LABillScraper  # noqa: E402
from ne.bills import NEBillScraper  # noqa: E402
from nm.votes import NMVoteScraper, rollcall_number  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _chamber(vote):
    return json.loads(vote.organization[1:])["classification"]


# --- Nebraska -----------------------------------------------------------------------------------------------------


def test_ne_lb48_same_day_votes_carry_their_key_id_in_order():
    page = lxml.html.fromstring(
        '<table class="history">'
        '<tr><td>May 30, 2025</td><td>Failed on Final Reading with Emergency Clause 26-22*-1</td>'
        '<td><a href="https://nebraskalegislature.gov/bills/view_votes.php?KeyID=12956">v</a></td></tr>'
        '<tr><td>May 30, 2025</td><td>Passed on Final Reading with Emergency Clause stricken 27-21*-1</td>'
        '<td><a href="https://nebraskalegislature.gov/bills/view_votes.php?KeyID=12957">v</a></td></tr>'
        "</table>"
    )
    scraper = NEBillScraper(jurisdiction="x", datadir="/tmp")
    bill = Bill("LB 48", "109", "A bill", chamber="legislature")
    with mock.patch.object(scraper, "lxmlize", return_value=lxml.html.fromstring("<div/>")):
        votes = list(scraper.scrape_votes(bill, page, "legislature"))
    assert [(v.result, v.extras.get("legislature-rollcall-num")) for v in votes] == [
        ("fail", "12956"),
        ("pass", "12957"),
    ]
    assert votes[0].start_date == votes[1].start_date  # the tie the number breaks


# --- Louisiana ----------------------------------------------------------------------------------------------------

PDF_BODY = lxml.html.fromstring("<html><body>Date: 5/19/2026\nYEAS\nSmith\nNAYS\nTotal\n</body></html>")


def _la_votes(name):
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.urlretrieve = mock.Mock()
    scraper.pdf_to_lxml = mock.Mock(return_value=PDF_BODY)
    bill = Bill("SB 487", "2026", "x", chamber="upper")
    return list(scraper.scrape_vote(bill, name, "https://www.legis.la.gov/Legis/ViewDocument.aspx?d=1"))


@pytest.mark.parametrize(
    "name,key,number",
    [
        ("House Vote on SB 487, FINAL PASSAGE (#1393)", "house-rollcall-num", "1393"),
        ("House Vote on SB 487, FINAL PASSAGE (#1400)", "house-rollcall-num", "1400"),
        ("Senate Vote on SB 487, CONCUR (#1432)", "senate-rollcall-num", "1432"),
    ],
)
def test_la_vote_carries_its_roll_call_number(name, key, number):
    (vote,) = _la_votes(name)
    assert vote.extras == {key: number}


def test_la_vote_without_a_number_gets_no_key():
    (vote,) = _la_votes("House Vote on SB 487, FINAL PASSAGE")
    assert not any(k.endswith("rollcall-num") for k in vote.extras)


def test_la_fixture_bills_all_carry_their_numbers():
    """The real "Votes" lists of four 2026 bills (fixtures/la_open583, OPEN-583): every vote gets its own number."""
    with open(os.path.join(FIXTURES, "la_open583", "SB149_votes.html"), encoding="utf-8") as f:
        text = f.read()
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.get = mock.Mock(return_value=mock.Mock(text=text))
    scraper.urlretrieve = mock.Mock()
    scraper.pdf_to_lxml = mock.Mock(return_value=PDF_BODY)
    votes = list(scraper.scrape_votes(Bill("SB 149", "2026", "x", chamber="upper"), "https://legis.la.gov/x"))
    assert votes
    for vote in votes:
        key = "senate-rollcall-num" if _chamber(vote) == "upper" else "house-rollcall-num"
        assert vote.motion_text.endswith(f"(#{vote.extras[key]})")


# --- New Mexico ---------------------------------------------------------------------------------------------------


def _nm_vote(fname, chamber):
    doc = fitz.open(os.path.join(FIXTURES, "nm_open685", fname))
    scraper = NMVoteScraper(jurisdiction="x", datadir="/tmp")
    return scraper.parse_vote(doc, f"https://www.nmlegis.gov/Sessions/26%20Regular/votes/{fname}", "2026", "HB 253", chamber)


def test_nm_hb253_same_day_senate_votes_carry_their_rcs_in_order():
    first, second = _nm_vote("HB0253SVOTE.PDF", "upper"), _nm_vote("HB0253SVOTE2.PDF", "upper")
    assert first.start_date == second.start_date == "2026-02-18"  # the tie the number breaks
    assert first.extras == {"senate-rollcall-num": "158"}
    assert second.extras == {"senate-rollcall-num": "173"}


def test_nm_house_pdf_rcs_on_one_line():
    vote = _nm_vote("HB0164HVOTE.PDF", "lower")
    assert vote.extras == {"house-rollcall-num": "128"}


@pytest.mark.parametrize("text,expected", [("RCS# 128\nOFFICIAL", "128"), ("RCS#\n 173\nHOUSE", "173"), ("no number", None)])
def test_nm_rollcall_number(text, expected):
    assert rollcall_number(text) == expected
