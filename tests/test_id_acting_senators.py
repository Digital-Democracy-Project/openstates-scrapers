"""OPEN-781: an Idaho acting (substitute) senator's vote is the acting senator's own.

A Senate roll call on an Idaho bill page prints an acting senator as "Acting(Senator)": the acting senator's surname,
then the senator whose seat they hold (Idaho Code 67-412). The scraper used to keep only the part before the
parenthesis, so an acting senator whose surname a sitting senator also has was matched to that senator:
"Bjerke(Bjerke)" (Lesli Bjerke for Sen. Carl Bjerke) and "Toews(Toews)" (Elisha Toews for Sen. Ben Toews) went to the
senator they replaced, and "Bjerke(Keyser)" (Garrett Bjerke for Sen. Josh Keyser) and "Keyser(Galloway)" (Steve Keyser
for Sen. Codi Galloway) went to a different sitting senator, who then had two votes on one roll call. The printed form
is now kept, and the people data gives each acting senator that form as a dated other name, so only they match it.

House rows are unchanged: the House prints "Member(Substitute)" ("Hall(Stone)") and is outside this ticket.

The fixtures are legislature.idaho.gov's own 2026 bill pages, read 2026-11-23 (tests/fixtures/id_open781; S 1221
from id_open770). Who sat for whom is from the 2026 Senate Final Journal's designation letters.
"""
import json
import os
import re
import sys
import types
from collections import Counter, defaultdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from id.bills import IDBillScraper  # noqa: E402

from openstates.scrape import VoteEvent  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def page(name):
    folder = "id_open770" if name == "s1221_2026" else "id_open781"
    return os.path.join(FIXTURES, folder, name + ".html")


@pytest.fixture
def scraper(tmp_path, monkeypatch):
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text("id: {}\n")
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    scraper = IDBillScraper.__new__(IDBillScraper)
    scraper._subjects = defaultdict(list)
    scraper.warning = lambda *a, **k: None
    return scraper


def roll_calls(scraper, name, bill_id):
    text = open(page(name), encoding="utf-8").read()
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(text=text)
    chamber = "lower" if bill_id[0] == "H" else "upper"
    return [
        v
        for v in scraper.scrape_bill(chamber, "2026", bill_id)
        if isinstance(v, VoteEvent)
    ]


def chamber_of(vote):
    return json.loads(vote.organization[1:])["classification"]


def roll_call(scraper, name, bill_id, chamber, date):
    (vote,) = [
        v
        for v in roll_calls(scraper, name, bill_id)
        if chamber_of(v) == chamber and v.start_date == date
    ]
    return vote


def names(vote):
    return Counter(v["voter_name"] for v in vote.votes)


# (page, bill, Senate roll call's day, printed acting senator, the sitting senator the bare surname used to match)
ACTING = [
    ("s1221_2026", "S 1221", "2026-02-03", "Toews(Toews)", "Toews"),
    ("s1240_2026", "S 1240", "2026-02-13", "Bjerke(Keyser)", "Bjerke"),
    ("s1300_2026", "S 1300", "2026-03-02", "Bjerke(Bjerke)", "Bjerke"),
    ("s1285_2026", "S 1285", "2026-03-06", "Keyser(Galloway)", "Keyser"),
]


@pytest.mark.parametrize("name,bill_id,date,printed,surname", ACTING)
def test_acting_senator_keeps_the_printed_form(
    scraper, name, bill_id, date, printed, surname
):
    vote = roll_call(scraper, name, bill_id, "upper", date)
    voters = names(vote)
    assert voters[printed] == 1
    # the voter id asks for the printed form only, which no sitting senator carries
    (acting,) = [v for v in vote.votes if v["voter_name"] == printed]
    assert get_pseudo_id(acting["voter_id"]) == {"name": printed}
    # one voter per seat: 35 senators, none counted twice
    assert len(vote.votes) == 35
    assert max(voters.values()) == 1


def test_cross_name_acting_senators_no_longer_double_a_sitting_senator(scraper):
    # 02/13: Garrett Bjerke sat for Josh Keyser while Carl Bjerke sat in his own seat
    voters = names(roll_call(scraper, "s1240_2026", "S 1240", "upper", "2026-02-13"))
    assert voters["Bjerke"] == 1 and voters["Bjerke(Keyser)"] == 1
    assert "Keyser" not in voters
    # 03/06: Steve Keyser sat for Codi Galloway while Josh Keyser sat in his own seat
    voters = names(roll_call(scraper, "s1285_2026", "S 1285", "upper", "2026-03-06"))
    assert voters["Keyser"] == 1 and voters["Keyser(Galloway)"] == 1
    assert "Galloway" not in voters


def test_same_name_acting_senator_leaves_no_bare_surname(scraper):
    # 03/02: Lesli Bjerke for Carl Bjerke; 02/03: Elisha Toews for Ben Toews
    voters = names(roll_call(scraper, "s1300_2026", "S 1300", "upper", "2026-03-02"))
    assert "Bjerke" not in voters
    voters = names(roll_call(scraper, "s1221_2026", "S 1221", "upper", "2026-02-03"))
    assert "Toews" not in voters


@pytest.mark.parametrize(
    "name,bill_id,date,printed",
    [
        ("s1242_2026", "S 1242", "2026-02-18", {"Brooks(Lakey)", "Hawkins(Anthon)"}),
        ("s1232_2026", "S 1232", "2026-02-19", {"Hawkins(Anthon)", "Merrell(Lakey)"}),
        ("s1300_2026", "S 1300", "2026-03-02", {"Bruner(Adams)", "Bjerke(Bjerke)"}),
        # OPEN-681's acting senators
        (
            "s1224_2026",
            "S 1224",
            "2026-03-09",
            {"Coho(Lenney)", "Rundhaug(Carlson)", "Bjerke(Bjerke)"},
        ),
        ("s1227_2026", "S 1227", "2026-03-17", {"Woller(Rabe)", "Bjerke(Bjerke)"}),
    ],
)
def test_earlier_acting_senators_are_printed_the_same_way(
    scraper, name, bill_id, date, printed
):
    voters = names(roll_call(scraper, name, bill_id, "upper", date))
    acting = {v for v in voters if "(" in v}
    assert acting == printed
    # their bare surnames are gone too (the people data gives them the printed form as an other name)
    assert not {p.split("(")[0] for p in printed} & set(voters)


def test_house_rows_keep_dropping_the_parenthesis(scraper):
    # the House prints "Hall(Stone)" (Rep. Hall, substitute Stone): unchanged, still read as "Hall"
    house = [
        v
        for v in roll_calls(scraper, "s1240_2026", "S 1240")
        if chamber_of(v) == "lower"
    ]
    assert house
    for vote in house:
        voters = names(vote)
        # only OPEN-680's district numbers ("Crane(12)") keep a parenthesis
        assert not [v for v in voters if re.search(r"\(\D+\)$", v)]
        assert "Hall" in voters
