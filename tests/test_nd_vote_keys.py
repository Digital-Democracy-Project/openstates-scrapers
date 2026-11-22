"""OPEN-757: every North Dakota roll call keeps its own identity at the import.

North Dakota's first load (2026-11-22) stopped on HB 1015: its two Senate division roll calls on 04/22/2025
("Division A lost", 23-24, and "Division B adopted", 32-15) have the same modal title ("Consideration of
Amendments"), the same chamber and the same time to the minute (01:47 PM). With no `dedupe_key` the vote
importer (openstates-core `vote_events.py`, `get_object()`) matches on session + bill + motion text + start
date + organization, so the second matched the first and the load raised a duplicate. Each vote modal's id is
ndlegis.gov's own roll-call id ("vote-modal-202501S01000": session, chamber, roll-call number), so the scraper
keys each vote on the page URL plus that id (unique across assemblies, sessions and bills, PRIMITIVES.md).

SB 2400's page really lists one roll call (202501S00396, Senate 02/21/2025, 25-22) twice, word for word:
that one is a true repeat and is kept once.

The fixtures (tests/fixtures/nd_open757/), saved from ndlegis.gov on 2026-11-22:

* ba1015.html, ba2400.html: assembly/69-2025/regular/bill-actions/ba1015.html and ba2400.html cut to their
  vote modals (4 and 3);
* bills_69-2025.json: api/assembly/69-2025/data/bills.json cut to HB 1015 and SB 2400.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import nd.bills as nd_bills  # noqa: E402
from openstates.scrape import VoteEvent  # noqa: E402
from spatula import URL  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nd_open757")
PAGES = "https://ndlegis.gov/assembly/69-2025/regular/bill-actions/"


class _Response:
    def __init__(self, content):
        self.content = content

    def json(self):
        return json.loads(self.content)


def votes(monkeypatch):
    def fake_get(url):
        if "/biography/" in url:
            return _Response(b"<html><body><h1>Senator A Member</h1></body></html>")
        name = url.rsplit("/", 1)[-1]
        return _Response(open(os.path.join(FIXTURES, name), "rb").read())

    monkeypatch.setattr(nd_bills.requests, "get", fake_get)
    bill_list = nd_bills.BillList(
        {"session": "69", "assembly": "69-2025", "site_session_id": "202501"}
    )
    bill_list.members_cache = {}
    bill_list.source = URL(bill_list.source)  # as spatula's do_scrape does
    bill_list.response = _Response(
        open(os.path.join(FIXTURES, "bills_69-2025.json"), "rb").read()
    )
    return [o for o in bill_list.process_page() if isinstance(o, VoteEvent)]


def import_match_key(vote):
    """What openstates-core's vote importer matches a vote on: its dedupe_key alone when it has one,
    otherwise session + bill + motion text + start date + organization (it has no identifier)."""
    return getattr(vote, "dedupe_key", None) or (
        vote.legislative_session,
        str(vote.bill),
        vote.motion_text,
        str(vote.start_date),
        str(vote.organization),
    )


def test_hb_1015_keeps_all_four_roll_calls_each_under_its_own_key(monkeypatch):
    hb1015 = [v for v in votes(monkeypatch) if PAGES + "ba1015.html" in v.dedupe_key]
    assert [
        (
            v.dedupe_key.rsplit("#", 1)[1],
            str(v.start_date),
            v.result,
            [c["value"] for c in v.counts],
        )
        for v in hb1015
    ] == [
        ("vote-modal-202501H00671", "2025-02-25 22:13:00-06:00", "pass", [83, 6, 4]),
        # the two division roll calls that collided: same title, chamber and minute
        ("vote-modal-202501S01000", "2025-04-22 13:47:00-05:00", "fail", [23, 24, 0]),
        ("vote-modal-202501S01001", "2025-04-22 13:47:00-05:00", "pass", [32, 15, 0]),
        ("vote-modal-202501S01002", "2025-04-22 14:04:00-05:00", "pass", [31, 16, 0]),
    ]
    assert hb1015[1].motion_text == hb1015[2].motion_text
    assert {v.dedupe_key for v in hb1015} == {
        PAGES + "ba1015.html#vote-modal-2025" + rc
        for rc in ("01H00671", "01S01000", "01S01001", "01S01002")
    }


def test_no_two_votes_share_an_import_match_key(monkeypatch):
    keys = collections.Counter(import_match_key(v) for v in votes(monkeypatch))
    assert [k for k, n in keys.items() if n > 1] == []
    assert sum(keys.values()) == 6  # HB 1015's 4 and SB 2400's 2


def test_a_roll_call_the_page_lists_twice_is_kept_once(monkeypatch):
    sb2400 = [v for v in votes(monkeypatch) if PAGES + "ba2400.html" in v.dedupe_key]
    assert [v.dedupe_key.rsplit("#", 1)[1] for v in sb2400] == [
        "vote-modal-202501S00396",
        "vote-modal-202501H01162",
    ]


def test_which_votes_count_as_passage_is_unchanged(monkeypatch):
    """OPEN-679's rule stands: Final Passage is passage, Consideration of Amendments is an amendment."""
    assert [(v.motion_text, v.motion_classification) for v in votes(monkeypatch)] == [
        ("Motion for Final Passage on HB 1015", ["passage"]),
        ("Motion for Consideration of Amendments on HB 1015", ["amendment"]),
        ("Motion for Consideration of Amendments on HB 1015", ["amendment"]),
        ("Motion for Final Passage on HB 1015", ["passage"]),
        ("Motion for Final Passage on SB 2400", ["passage"]),
        ("Motion for Final Passage on SB 2400", ["passage"]),
    ]
