"""OPEN-782: a Wyoming voter printed as "Surname, initials" is one voter, whether the initials have one letter or two.

lsoservice.wyoleg.gov joins each roll call's voters with commas and tells apart members who share a surname with
their initials: "Brown, G", "Brown, L", "Campbell, E", "Campbell, K", "Larsen, L" and "Larson, JT" (and, in its upper
case lists, "SMITH, S", "BROWN, G", ...). Those are every such form in the 2026 source (1,254 roll calls). Only one
letter was merged back onto the surname, so "Larson, JT" became two voters, "Larson" and "JT", on 498 roll calls,
and both resolved to J.T. Larson. Every surname the source prints has three letters or more ("Ide", "YIN").

The fixtures are the real API answers of tests/fixtures/wy_open769 (read 2026-11-22).
"""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import VoteEvent  # noqa: E402
from wy import Wyoming  # noqa: E402
from wy.bills import WYBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wy_open769")
TALLIES = (
    "yesVotesCount",
    "noVotesCount",
    "absentVotesCount",
    "excusedVotesCount",
    "conflictVotesCount",
)


def source(session, bill):
    with open(os.path.join(FIXTURES, f"{session}_{bill}.json"), encoding="utf-8") as f:
        return json.load(f)


def votes(session, bill):
    scraper = WYBillScraper(Wyoming(), "/tmp/")
    scraper.is_special = "S" in session
    body = json.dumps(source(session, bill)).encode("utf-8")
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(content=body)
    return [v for v in scraper.scrape_bill(bill, session) if isinstance(v, VoteEvent)]


def test_sf2_house_third_reading_has_one_larson_jt():
    """SF 2's "H 3rd Reading:Passed 55-2-5-0-0" (vote 5262): 62 representatives, J.T. Larson once."""
    (vote,) = [v for v in votes("2026", "SF0002") if v.dedupe_key.endswith("#5262")]
    names = [v["voter_name"] for v in vote.votes]
    assert names.count("Larson, JT") == 1
    assert "JT" not in names and "Larson" not in names
    assert len(names) == 62
    assert {"Brown, G", "Brown, L", "Campbell, E", "Campbell, K", "Larsen, L"} <= set(
        names
    )


@pytest.mark.parametrize(
    "session,bill",
    [("2026", "SF0001"), ("2026", "SF0002"), ("2026", "HB0010"), ("2021", "HB0001")],
)
def test_every_roll_call_has_as_many_voters_as_its_tally(session, bill):
    rollcalls = {rc["voteID"]: rc for rc in source(session, bill)["rollCalls"]}
    for vote in votes(session, bill):
        rc = rollcalls[int(vote.dedupe_key.rsplit("#", 1)[1])]
        assert len(vote.votes) == sum(rc[k] for k in TALLIES), vote.motion_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        # every "Surname, initials" form in the 2026 source
        (
            "Brown, G, Brown, L, Larson, JT, Lien",
            ["Brown, G", "Brown, L", "Larson, JT", "Lien"],
        ),
        (
            "Campbell, E, Campbell, K, Larsen, L",
            ["Campbell, E", "Campbell, K", "Larsen, L"],
        ),
        # the upper case lists: initials are merged, a three-letter surname is not
        ("SMITH, S, BEAR, IDE, YIN", ["SMITH, S", "BEAR", "IDE", "YIN"]),
        ("CAMPBELL, K, LIEN", ["CAMPBELL, K", "LIEN"]),
    ],
)
def test_split_voter_names(raw, expected):
    assert WYBillScraper._split_voter_names(raw) == expected
