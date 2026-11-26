"""OPEN-901: North Dakota's veto-override votes are stored.

ndlegis.gov publishes a veto-override vote only as a bill action with its tally and a journal page ("Veto
sustained, yeas 45 nays 48"), never as a vote modal, so the scraper stored none: 5 votes on 4 bills in 2025
(HB 1540, SB 2160, SB 2261, SB 2307). The journal (House Journal, 70th day, p. 1411) confirms HB 1540's:
"45 YEAS, 48 NAYS, 1 ABSENT OR EXCUSED AND NOT VOTING ... The House sustained the Governor's veto".

The fixtures (tests/fixtures/nd_open901_override/), saved from ndlegis.gov on 2026-11-26:

* ba1540.html, ba2160.html, ba2261.html, ba2307.html: the bill-actions pages cut to the action rows that hold a vote
  modal or mention a veto;
* bills_69-2025.json: api/assembly/69-2025/data/bills.json cut to HB 1540, SB 2160, SB 2261 and SB 2307.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import nd.bills as nd_bills  # noqa: E402
from openstates.scrape import VoteEvent  # noqa: E402
from spatula import URL  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nd_open901_override")
PAGES = "https://ndlegis.gov/assembly/69-2025/regular/bill-actions/"


class _Response:
    def __init__(self, content):
        self.content = content

    def json(self):
        return json.loads(self.content)


def votes(monkeypatch, bills_json=None):
    def fake_get(url):
        if "/biography/" in url:
            return _Response(b"<html><body><h1>Senator A Member</h1></body></html>")
        return _Response(open(os.path.join(FIXTURES, url.rsplit("/", 1)[-1]), "rb").read())

    monkeypatch.setattr(nd_bills.requests, "get", fake_get)
    bill_list = nd_bills.BillList(
        {"session": "69", "assembly": "69-2025", "site_session_id": "202501"}
    )
    bill_list.members_cache = {}
    bill_list.source = URL(bill_list.source)
    bill_list.response = _Response(
        bills_json or open(os.path.join(FIXTURES, "bills_69-2025.json"), "rb").read()
    )
    return [o for o in bill_list.process_page() if isinstance(o, VoteEvent)]


def overrides(monkeypatch, **kw):
    return [
        v for v in votes(monkeypatch, **kw) if "Veto Override" in v.motion_text
    ]


def chamber_of(vote):
    """The chamber a vote is filed under: its organization is the pseudo-id {"classification": "lower"}."""
    return json.loads(vote.organization.replace("~", "").replace("'", '"'))["classification"]


def test_each_override_action_is_stored_with_its_chamber_tally_and_result(monkeypatch):
    assert [
        (
            v.motion_text,
            chamber_of(v),
            str(v.start_date),
            v.result,
            sorted((c["option"], c["value"]) for c in v.counts),
            v.motion_classification,
        )
        for v in overrides(monkeypatch)
    ] == [
        # HB 1540, House 04/25: "Veto sustained, yeas 45 nays 48"
        ("Motion for Veto Override on HB 1540", "lower", "2025-04-25", "fail", [("no", 48), ("yes", 45)], ["passage"]),
        # SB 2160, Senate 05/01: "Veto sustained, yeas 31 nays 15" (31 is under two thirds of 47)
        ("Motion for Veto Override on SB 2160", "upper", "2025-05-01", "fail", [("no", 15), ("yes", 31)], ["passage"]),
        # SB 2261: the Senate voted to override (03/27, 45-2), then the House sustained the veto (04/03, 15-78)
        ("Motion for Veto Override on SB 2261", "upper", "2025-03-27", "pass", [("no", 2), ("yes", 45)], ["passage"]),
        ("Motion for Veto Override on SB 2261", "lower", "2025-04-03", "fail", [("no", 78), ("yes", 15)], ["passage"]),
        # SB 2307, Senate 04/25: "Veto sustained, yeas 25 nays 20"
        ("Motion for Veto Override on SB 2307", "upper", "2025-04-25", "fail", [("no", 20), ("yes", 25)], ["passage"]),
    ]
    assert len(overrides(monkeypatch)) == 5


def test_each_override_has_its_own_key_and_the_page_as_source(monkeypatch):
    all_votes = votes(monkeypatch)
    keys = [v.dedupe_key for v in all_votes]
    assert len(keys) == len(set(keys))
    assert {v.dedupe_key for v in overrides(monkeypatch)} == {
        PAGES + "ba1540.html#veto-override-lower-2025-04-25",
        PAGES + "ba2160.html#veto-override-upper-2025-05-01",
        PAGES + "ba2261.html#veto-override-upper-2025-03-27",
        PAGES + "ba2261.html#veto-override-lower-2025-04-03",
        PAGES + "ba2307.html#veto-override-upper-2025-04-25",
    }
    assert all(
        [s["url"] for s in v.sources] == [v.dedupe_key.split("#")[0]]
        for v in overrides(monkeypatch)
    )


def test_the_override_is_the_latest_passage_vote_of_its_chamber(monkeypatch):
    """Ramon's 11-24 rule: the latest full roll call replaces earlier ones. Offline, with the broker's own rule."""
    by = {}
    for v in votes(monkeypatch):
        if v.motion_classification == ["passage"] and v.motion_text.endswith("HB 1540"):
            by.setdefault(chamber_of(v), []).append(str(v.start_date)[:10])
    assert max(by["lower"]) == "2025-04-25"


def test_an_override_on_a_bill_with_a_line_item_veto_does_not_count_as_passage(monkeypatch):
    bills = json.load(open(os.path.join(FIXTURES, "bills_69-2025.json")))
    for bill in bills["bills"].values():
        if bill["name"] == "HB 1540":
            bill["actions"].append(
                {"date": "2025-04-24T23:59:59", "chamber": "House", "description": "Signed by Governor, but item veto 04/24"}
            )
    found = [v for v in overrides(monkeypatch, bills_json=json.dumps(bills).encode()) if v.motion_text.endswith("HB 1540")]
    assert [v.motion_classification for v in found] == [["veto-override"]]


def test_other_action_texts_make_no_override_vote():
    for text in (
        "Vetoed by Governor 04/23",
        "Consideration of Governor's veto",
        "Veto sustained",
        "Second reading, passed, yeas 49 nays 43",
        "Signed by Governor, but item veto 05/19",
    ):
        assert nd_bills.OVERRIDE_ACTION.match(text) is None
