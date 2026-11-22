"""OPEN-769: every Wyoming roll call keeps its own identity at the import (North Dakota's OPEN-757 pattern).

North Dakota's first load stopped on two roll calls with the same motion text, chamber and minute: with no `dedupe_key`
the vote importer (openstates-core `vote_events.py`, `get_object()`) matches on session + bill + motion text + start
date + organization. lsoservice.wyoleg.gov numbers every roll call ("voteID": Senate floor votes in the hundreds, House
floor votes from 5000 up, committee votes negative). The numbers restart every year (House 5144 in 2021, 5043 in
2026) and run on through a year's special session (2021 House 5294 in March, 6007 in the October special), so the key
is the bill's page (Legislation/<session>/<bill>: session, bill) plus that number. The API's chamber is left out: it is
sometimes wrong (OPEN-675, SF 2's Senate introduction vote comes back "H").

No two roll calls in the saved bills share a motion text, time and chamber (105 roll calls), so the colliding pair
below is built from SF 2's real Senate third reading: a copy with its own number and tally. A roll call the API lists
twice for one bill is kept once.

The fixtures are lsoservice.wyoleg.gov/api/BillInformation answers (tests/fixtures/wy_open769, read 2026-11-22), with
the long *HTML text fields emptied to keep them small; every other field, the roll calls included, is as served.
"""
import collections
import copy
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import VoteEvent  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wy_open769")
PAGE = "https://lso.wyoleg.gov/Legislation/{}/{}"
BILLS = [
    ("2026", "SF0001"),
    ("2026", "SF0002"),
    ("2026", "HB0010"),
    ("2021", "HB0001"),
    ("2021S1", "HB1001"),
]


def bill_json(session, bill):
    with open(os.path.join(FIXTURES, f"{session}_{bill}.json"), encoding="utf-8") as f:
        return json.load(f)


def votes(session, bill, data=None):
    """scrape_bill() over one saved API answer: its votes, in the API's order."""
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    scraper.is_special = "S" in session
    body = json.dumps(data or bill_json(session, bill)).encode("utf-8")
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(content=body)
    return [v for v in scraper.scrape_bill(bill, session) if isinstance(v, VoteEvent)]


def import_match_key(vote):
    """What the importer matches a vote on: its dedupe_key alone when it has one, otherwise session + bill + motion
    text + start date + organization (Wyoming's votes have no identifier)."""
    return getattr(vote, "dedupe_key", None) or (
        vote.legislative_session,
        str(vote.bill),
        vote.motion_text,
        str(vote.start_date),
        str(vote.organization),
    )


def test_each_roll_call_is_keyed_on_its_bill_page_and_vote_id():
    page = PAGE.format("2026", "SF0002")
    assert [(v.dedupe_key, v.motion_text) for v in votes("2026", "SF0002")] == [
        (page + "#102", "S Introduced and Referred to S02 - Appropriations 31-0-0-0-0"),
        (page + "#-1", "S02 - Appropriations:Recommend Do Pass 5-0-0-0-0"),
        (page + "#205", "SF0002S2001: Amendment failed 3-28-0-0-0"),
        (page + "#206", "SF0002S2002: Amendment failed 14-17-0-0-0"),
        (page + "#231", "S 3rd Reading:Passed 31-0-0-0-0"),
        (page + "#-122", "H02 - Appropriations:Recommend Do Pass 7-0-0-0-0"),
        (page + "#5262", "H 3rd Reading:Passed 55-2-5-0-0"),
    ]


def test_keys_are_unique_across_sessions_and_bills():
    found = [v for session, bill in BILLS for v in votes(session, bill)]
    keys = [v.dedupe_key for v in found]
    assert len(keys) == len(set(keys)) == 105
    # a year's regular and special sessions are told apart by the page, not the number
    assert PAGE.format("2021", "HB0001") + "#5294" in keys
    assert PAGE.format("2021S1", "HB1001") + "#6007" in keys
    keys = collections.Counter(import_match_key(v) for v in found)
    assert [k for k, n in keys.items() if n > 1] == []


def test_the_same_number_in_another_year_is_another_vote():
    """voteIDs restart each year; the session in the page address keeps them apart."""
    data = bill_json("2026", "SF0002")
    (vote_2026,) = [
        v for v in votes("2026", "SF0002", data) if v.dedupe_key.endswith("#231")
    ]
    (vote_2025,) = [
        v for v in votes("2025", "SF0002", data) if v.dedupe_key.endswith("#231")
    ]
    assert vote_2026.dedupe_key != vote_2025.dedupe_key


def test_two_roll_calls_with_the_same_motion_and_time_get_their_own_keys():
    data = bill_json("2026", "SF0002")
    (third,) = [rc for rc in data["rollCalls"] if rc["voteID"] == 231]
    again = copy.deepcopy(third)
    again["voteID"] = 232
    again["yesVotesCount"] = 30
    data["rollCalls"].append(again)
    found = votes("2026", "SF0002", data)
    a, b = [v for v in found if v.motion_text == "S 3rd Reading:Passed 31-0-0-0-0"]
    # without a key the importer would take the second for the first
    assert (a.start_date, a.organization) == (b.start_date, b.organization)
    page = PAGE.format("2026", "SF0002")
    assert [a.dedupe_key, b.dedupe_key] == [page + "#231", page + "#232"]
    assert [a.counts[0]["value"], b.counts[0]["value"]] == [31, 30]
    keys = collections.Counter(import_match_key(v) for v in found)
    assert [k for k, n in keys.items() if n > 1] == []


def test_a_roll_call_listed_twice_is_kept_once():
    data = bill_json("2026", "SF0002")
    data["rollCalls"].insert(1, copy.deepcopy(data["rollCalls"][0]))
    assert [v.dedupe_key.rsplit("#", 1)[1] for v in votes("2026", "SF0002", data)] == [
        "102",
        "-1",
        "205",
        "206",
        "231",
        "-122",
        "5262",
    ]


def test_which_votes_count_as_passage_is_unchanged():
    """OPEN-675's chambers, OPEN-677's labels and OPEN-684's results stand (the same as clean main gives)."""
    assert [
        (
            json.loads(v.organization[1:])["classification"],
            v.motion_text,
            v.motion_classification,
            v.result,
        )
        for v in votes("2026", "SF0002")
    ] == [
        (
            "upper",
            "S Introduced and Referred to S02 - Appropriations 31-0-0-0-0",
            ["reading-1"],
            "pass",
        ),
        (
            "upper",
            "S02 - Appropriations:Recommend Do Pass 5-0-0-0-0",
            ["committee-passage"],
            "pass",
        ),
        ("upper", "SF0002S2001: Amendment failed 3-28-0-0-0", ["amendment"], "fail"),
        ("upper", "SF0002S2002: Amendment failed 14-17-0-0-0", ["amendment"], "fail"),
        ("upper", "S 3rd Reading:Passed 31-0-0-0-0", ["passage"], "pass"),
        (
            "lower",
            "H02 - Appropriations:Recommend Do Pass 7-0-0-0-0",
            ["committee-passage"],
            "pass",
        ),
        ("lower", "H 3rd Reading:Passed 55-2-5-0-0", ["passage"], "pass"),
    ]
