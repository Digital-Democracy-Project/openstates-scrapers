"""OPEN-760: every Montana roll call keeps its own identity at the import (North Dakota's OPEN-757 pattern).

The vote importer (openstates-core `vote_events.py`, `get_object()`) matches a vote on its `dedupe_key` alone when it
has one; otherwise on session + bill + `identifier`, or with no identifier on motion text + start date + chamber.

* Bills API (2025 on): the scraper's identifier was "<session>-<bill>-<API vote id>", but floor votes
  (bills/v1/votes) and committee votes (committees/v1/executiveActions) are numbered separately (in the saved 2025
  pages, floor ids run 355-5632 and committee ids 398-6986), so one bill's floor and committee vote can share an id
  and so an identifier. The key is the page address (which endpoint, which bill) plus the API's vote id.
* Archive API (2023 and before): a floor vote carries its chamber's roll-call number for the session ("H2534",
  "S1204"); the key is the bill's page (session, bill) plus that number. A committee vote has none and keeps the
  importer's own match.

No collision is in the saved pages (8 bills of 2025, 47 votes; 2023 HB 95), nor in 400 bills of the 2023 archive read
on 2026-11-22, so the colliding pairs below are built from saved rows: a committee row given a floor row's id, and a
second "Motion to Amend Carried" in the same minute with its own number. A vote the source lists twice is kept once.
The fixtures are tests/fixtures/mt_open694 (bills API answers read 2026-11-20, archive 2023 HB 95).
"""
import collections
import copy
import json
import os
import sys

import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from mt.bills import MTBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mt_open694")
FLOOR = "https://api.legmt.gov/bills/v1/votes/findByBillId?billId=1"
CMTE = "https://api.legmt.gov/committees/v1/executiveActions/findByBillId?billId=1"


class _Names(dict):
    def __missing__(self, key):
        return "member %s" % key


class _Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def api_votes(slug, floor=None, cmte=None):
    """scrape_votes() then scrape_committee_votes() for one saved 2025 bill, with its pages optionally replaced."""
    scraper = MTBillScraper.__new__(MTBillScraper)
    scraper.info = scraper.warning = lambda *a, **k: None
    scraper.legislators_by_id = _Names()
    scraper.actions_by_id = {
        str(a["id"]): a["billStatusCode"]["name"]
        for a in load("%s-bill.json" % slug)["draft"]["billStatuses"]
    }
    pages = {
        "floor": floor if floor is not None else load("%s-floor.json" % slug),
        "cmte": cmte if cmte is not None else load("%s-cmte.json" % slug),
    }
    scraper.get = lambda url: _Resp(
        pages["floor" if "/bills/v1/votes/" in url else "cmte"]
    )
    bill = Bill(slug, legislative_session="2025", chamber="lower", title="t")
    bill.add_source("https://bills.legmt.gov/")
    return list(scraper.scrape_votes(bill, "1")) + list(
        scraper.scrape_committee_votes(bill, "1")
    )


def archive_votes(row):
    scraper = MTBillScraper.__new__(MTBillScraper)
    scraper.tz = pytz.timezone("America/Denver")
    bill = Bill("HB 95", legislative_session="2023", chamber="lower", title="t")
    bill.add_source("https://bills.legmt.gov/#/bill/20231/LC0123")
    return list(scraper.scrape_archive_actions(bill, row))


def import_match_key(vote):
    """What the importer matches a vote on (session and bill are the same for one bill)."""
    if getattr(vote, "dedupe_key", None):
        return vote.dedupe_key
    if vote.identifier:
        return vote.identifier
    return (vote.motion_text, str(vote.start_date), str(vote.organization))


def test_api_votes_are_keyed_on_their_page_and_api_id():
    votes = api_votes("HB228")
    floor_ids = [r["id"] for r in load("HB228-floor.json")]
    cmte_ids = [r["id"] for r in load("HB228-cmte.json")]
    assert [v.dedupe_key for v in votes] == [
        "%s#%s" % (FLOOR, i) for i in floor_ids
    ] + ["%s#%s" % (CMTE, i) for i in cmte_ids]
    # the identifier is left as it was
    assert votes[0].identifier == "2025-HB228-%s" % floor_ids[0]


def test_a_floor_and_a_committee_vote_with_the_same_api_id_stay_apart():
    floor = load("HB228-floor.json")
    cmte = load("HB228-cmte.json")
    cmte[0]["id"] = floor[0][
        "id"
    ]  # the two series overlap, so this can happen on a real bill
    votes = api_votes("HB228", floor=floor, cmte=cmte)
    first_floor, first_cmte = votes[0], votes[len(floor)]
    # the old identifier would have matched the committee vote to the floor vote
    assert first_floor.identifier == first_cmte.identifier
    assert first_floor.dedupe_key == "%s#%s" % (FLOOR, floor[0]["id"])
    assert first_cmte.dedupe_key == "%s#%s" % (CMTE, floor[0]["id"])
    keys = collections.Counter(import_match_key(v) for v in votes)
    assert [k for k, n in keys.items() if n > 1] == []


def test_an_api_vote_listed_twice_is_kept_once():
    floor = load("HB228-floor.json")
    votes = api_votes("HB228", floor=floor[:2] + [copy.deepcopy(floor[0])] + floor[2:])
    assert len(votes) == len(floor) + len(load("HB228-cmte.json"))
    assert len({v.dedupe_key for v in votes}) == len(votes)


def test_archive_floor_votes_are_keyed_on_the_bill_page_and_roll_call_number():
    votes = archive_votes(load("archive-2023-HB95.json"))
    page = "https://bills.legmt.gov/#/bill/20231/LC0123"
    assert [(getattr(v, "dedupe_key", None), v.motion_text) for v in votes] == [
        (page + "#H2534", "(H) 3rd Reading Passed as Amended by Senate"),
        (page + "#H2484", "(H) 2nd Reading Senate Amendments Concurred"),
        (page + "#S1265", "(S) 3rd Reading Concurred"),
        (page + "#S1205", "(S) 2nd Reading Concurred as Amended"),
        (page + "#S1204", "(S) 2nd Reading Motion to Amend Carried"),
        # committee votes carry no roll-call number: the importer's own match, as before
        (None, "(S) Committee Executive Action--Bill Concurred as Amended"),
        (page + "#H343", "(H) 3rd Reading Passed"),
        (page + "#H307", "(H) 2nd Reading Passed"),
        (None, "(H) Committee Executive Action--Bill Passed as Amended"),
    ]


def test_two_archive_roll_calls_with_the_same_motion_and_minute_get_their_own_keys():
    row = load("archive-2023-HB95.json")
    (amend,) = [a for a in row["billActions"] if a["voteSeq"] == "S1204"]
    second = dict(amend, voteSeq="S1203", yesVotes="31", noVotes="19")
    row["billActions"].append(second)
    votes = [
        v
        for v in archive_votes(row)
        if v.motion_text == "(S) 2nd Reading Motion to Amend Carried"
    ]
    assert len(votes) == 2
    assert str(votes[0].start_date) == str(votes[1].start_date)
    assert [v.dedupe_key.rsplit("#", 1)[1] for v in votes] == ["S1204", "S1203"]


def test_an_archive_roll_call_listed_twice_is_kept_once():
    row = load("archive-2023-HB95.json")
    (amend,) = [a for a in row["billActions"] if a["voteSeq"] == "S1204"]
    row["billActions"].append(copy.deepcopy(amend))
    votes = archive_votes(row)
    assert len(votes) == 9
    assert [v.dedupe_key for v in votes if getattr(v, "dedupe_key", None)].count(
        "https://bills.legmt.gov/#/bill/20231/LC0123#S1204"
    ) == 1
