"""OPEN-924: Massachusetts votes carry their roll-call number, so two votes on one day have an order.

BROKER-617 (comment 23853): the House gives a vote its day only, so a conference report and the same day's
enactment tie, and both stayed counted on seven House bill-chambers (H 4000, H 4227, H 4237, H 4240, H 5555,
H 5620, H 5627). OPEN-685 gave Nebraska, Louisiana and New Mexico the answer: the scraper writes the roll-call
number under an extras key ending "rollcall-num" ("house-rollcall-num" / "senate-rollcall-num"), and the broker
reads it into Motion.rollcall_num to order same-day votes in one chamber. This is the same key, no second rule.
Massachusetts' number is in the action itself: "(See YEA and NAY No. 56 )" for the House, "Roll Call #52" for the
Senate; the numbers run on through the whole session and rise in the order the votes were taken.

The action lines are the real stored ones (Mac replica, 2026-11-26).
"""
import os
import sys
from unittest import mock

import lxml.html
import pytest
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper, senate_rollcall_number  # noqa: E402


def _votes(identifier, rows):
    """`rows`: (date, chamber, action line). The roll-call PDFs are not fetched."""
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    bill = Bill(identifier, legislative_session="194th", title="t", classification="bill")
    page = lxml.html.fromstring(
        "<table><tbody>{}</tbody></table>".format(
            "".join("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(*row) for row in rows)
        )
    )
    with mock.patch.object(scraper, "scrape_house_vote", return_value=True), mock.patch.object(
        scraper, "scrape_house_voters", return_value="pdf"
    ), mock.patch.object(scraper, "scrape_senate_vote", return_value=True):
        return [v for v in scraper.scrape_action_page(bill, page) if type(v).__name__ == "VoteEvent"]


# (bill, date, conference report or engrossment line, number, enactment line, number): the tie the broker saw
TIES = [
    ("H4227", "6/18/2025", "Committee of conference report accepted -\r\n150 YEAS to 3 NAYS (See YEA and NAY No. 56 )", "56", "Enacted -\r\n148 YEAS to 4 NAYS (See YEA and NAY No. 57 )", "57"),
    ("H4237", "6/30/2025", "Passed to be engrossed -\r\n143 YEAS to 1 NAYS (See YEA and NAY No. 59 )", "59", "Enacted -\r\n144 YEAS to 1 NAYS (See YEA and NAY No. 60 )", "60"),
    ("H4240", "6/30/2025", "Committee of conference report accepted -\r\n139 YEAS to 6 NAYS (See YEA and NAY No. 61 )", "61", "Enacted -\r\n139 YEAS to 6 NAYS (See YEA and NAY No. 62 )", "62"),
    ("H5555", "7/1/2026", "Committee of conference report accepted - 142 YEAS to 6\r\nNAYS (See YEA and NAY No. 223 )", "223", "Enacted - 142 YEAS to 6 NAYS (See YEA and NAY No. 224 )", "224"),
    ("H5620", "7/30/2026", "Committee of conference report accepted - 137 YEAS to 21 NAYS (See YEA and NAY No. 243 )", "243", "Enacted - 137 YEAS to 21 NAYS (See YEA and NAY No. 251 )", "251"),
    ("H5627", "7/31/2026", "Committee of conference report accepted - 157 YEAS to 0 NAYS (See YEA and NAY No. 259 )", "259", "Enacted - 157 YEAS to 0 NAYS (See YEA and NAY No. 260 )", "260"),
]


@pytest.mark.parametrize("bill,date,first,first_no,second,second_no", TIES)
def test_same_day_house_votes_carry_their_numbers_in_the_order_taken(bill, date, first, first_no, second, second_no):
    one, two = _votes(bill, [(date, "House", first), (date, "House", second)])
    assert one.start_date == two.start_date  # the tie the number breaks
    assert one.extras["house-rollcall-num"] == first_no
    assert two.extras["house-rollcall-num"] == second_no
    assert int(one.extras["house-rollcall-num"]) < int(two.extras["house-rollcall-num"])


def test_a_house_vote_has_exactly_one_key_the_broker_would_read():
    (vote,) = _votes("H4227", [("6/18/2025", "House", TIES[0][4])])
    assert [k for k in vote.extras if k.endswith("rollcall-num")] == ["house-rollcall-num"]


def test_the_senate_vote_carries_its_roll_call_number():
    """H 4227's Senate enactment, 2025-06-18: "Enacted -see Roll Call #52 (Yeas 40 to Nays 0)"."""
    (vote,) = _votes("H4227", [("6/18/2025", "Senate", "Enacted -see   Roll Call #52 (Yeas 40 to Nays 0)")])
    assert vote.extras["senate-rollcall-num"] == "52"
    assert "house-rollcall-num" not in vote.extras


@pytest.mark.parametrize(
    "action,number",
    [
        ("Amendment #1 (Tarr) rejected -see   Roll Call #105 (Yeas 5 to Nays 33)", "105"),
        ("Passed to be engrossed -see   Roll Call # 97 (Yeas 39 to Nays 0)", "97"),  # S 2710 spells it with a space
        ("Ordered to a third reading -- see Senate   Roll Call #25 and House Roll Call 56", "25"),
    ],
)
def test_senate_number_reads_the_number_the_action_gives_the_senate(action, number):
    assert senate_rollcall_number(action) == number


def test_an_ambiguous_senate_citation_gives_no_number():
    """Two unqualified numbers: guessing could order the wrong chamber's roll call (OPEN-176's rule)."""
    assert senate_rollcall_number("Passed -see Roll Call #5 and Roll Call #9 (Yeas 1 to Nays 0)") is None


def test_the_control_a_vote_still_has_its_other_fields():
    (vote,) = _votes("H4227", [("6/18/2025", "House", TIES[0][2])])
    assert vote.motion_text == "Committee of conference report accepted"
    assert vote.dedupe_key == "https://malegislature.gov/Journal/House/194/2025/RollCalls#56#H4227"
