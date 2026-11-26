"""OPEN-901: a North Dakota roll call's result comes from its bill action row when the row states one.

SB 2158's House roll call (04/04/2025, 59-31-4) was stored as failed. Its action row reads "Second reading,
passed, yeas 59 nays 31" and the next row "Emergency clause failed"; the governor signed the bill (04/15). The
bill-actions page puts one roll call on the passage row, and its modal says "Failed in House" because the
emergency clause needs two thirds of the House (63 of 94) and 59 fell short. The bill passed; its roll call
did not fail.

The other failed roll calls with more yeas than nays (HB 1242, HB 1358, HB 1590, HCR 3012, HB 1457, HB 1594)
are rows that say "failed ... lacks constitutional majority" or "failed to pass" with their own tally, so
the row and the modal agree there (see the tests of the row reader below).

The fixtures (tests/fixtures/nd_open901_result/), saved from ndlegis.gov on 2026-11-26:

* ba2158.html: the bill-actions page of SB 2158 cut to its vote-modal rows and its "Emergency clause" row;
* bills_69-2025.json: api/assembly/69-2025/data/bills.json cut to SB 2158.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import nd.bills as nd_bills  # noqa: E402
from nd.bills import result_from_action_row  # noqa: E402
from openstates.scrape import VoteEvent  # noqa: E402
from spatula import URL  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nd_open901_result")


class _Response:
    def __init__(self, content):
        self.content = content

    def json(self):
        return json.loads(self.content)


def votes(monkeypatch, page=None):
    def fake_get(url):
        if "/biography/" in url:
            return _Response(b"<html><body><h1>Senator A Member</h1></body></html>")
        return _Response(page or open(os.path.join(FIXTURES, "ba2158.html"), "rb").read())

    monkeypatch.setattr(nd_bills.requests, "get", fake_get)
    bill_list = nd_bills.BillList(
        {"session": "69", "assembly": "69-2025", "site_session_id": "202501"}
    )
    bill_list.members_cache = {}
    bill_list.source = URL(bill_list.source)
    bill_list.response = _Response(
        open(os.path.join(FIXTURES, "bills_69-2025.json"), "rb").read()
    )
    return [o for o in bill_list.process_page() if isinstance(o, VoteEvent)]


def test_sb_2158_house_roll_call_passed_like_its_action_row(monkeypatch):
    assert [
        (str(v.start_date)[:10], v.motion_text, v.result, [c["value"] for c in v.counts])
        for v in votes(monkeypatch)
    ] == [
        ("2025-01-23", "Motion for Consideration of Amendments on SB 2158", "fail", [12, 35, 0]),
        ("2025-01-23", "Motion for Final Passage on SB 2158", "pass", [38, 9, 0]),
        # the modal says "Failed in House" (the emergency clause); the row says "passed, yeas 59 nays 31"
        ("2025-04-04", "Motion for Final Passage on SB 2158", "pass", [59, 31, 4]),
    ]


def test_a_roll_call_whose_row_has_no_matching_tally_keeps_the_modal_status(monkeypatch):
    page = open(os.path.join(FIXTURES, "ba2158.html"), "rb").read().replace(
        b"Second reading, passed, yeas 59 nays 31", b"Second reading, passed, yeas 58 nays 31"
    )
    assert [v.result for v in votes(monkeypatch, page=page)][-1] == "fail"


@pytest.mark.parametrize(
    "row,yes,no,expected",
    [
        # SB 2158, House 04/04: the row passes it
        ("Second reading, passed, yeas 59 nays 31", 59, 31, "pass"),
        # real failed rows with more yeas than nays (read 2026-11-26): the row agrees with the modal
        ("Second reading, failed, lacks constitutional majority yeas 47 nays 37", 47, 37, "fail"),  # 2025 HB 1242
        ("Second reading, failed, lacks constitutional majority yeas 45 nays 44", 45, 44, "fail"),  # 2025 HB 1358
        ("Second reading, failed, lacks constitutional majority yeas 47 nays 40", 47, 40, "fail"),  # 2025 HB 1590
        ("Second reading, failed, lacks constitutional majority yeas 43 nays 42", 43, 42, "fail"),  # 2025 HCR 3012
        ("Second reading, failed to pass, yeas 45 nays 42", 45, 42, "fail"),  # 2025 HB 1457 (45 < 48)
        ("Second reading, failed to pass, yeas 23 nays 22", 23, 22, "fail"),  # 2025 HB 1594, Senate (23 < 24)
        ("Second reading, adopted yeas 24 nays 23", 24, 23, "pass"),  # 2025 SCR 4008, Senate
        ("Second reading, passed as amended, yeas 28 nays 18", 28, 18, "pass"),  # 2025 HB 1298, Senate
        # no verdict: another tally, no tally, or no result word
        ("Second reading, passed, yeas 59 nays 31", 59, 30, None),
        ("Emergency clause failed", 59, 31, None),
        ("Laid over three legislative days", 59, 31, None),
    ],
)
def test_row_reader(row, yes, no, expected):
    assert result_from_action_row(row, yes, no) == expected
