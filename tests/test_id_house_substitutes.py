"""OPEN-787: an Idaho House substitute's vote is the substitute's own (Ramon, 2026-11-23, the OPEN-781 rule).

A House roll call on an Idaho bill page prints a substitute the other way round from the Senate: "Member(Substitute)",
the representative whose seat it is, then the substitute named under Idaho Code 67-412. "Hall(Stone)" is Grayson Stone
in Rep. Don Hall's seat, "Hill(Brown)" is Max Brown in Rep. Ted Hill's seat. The scraper used to keep only the part
before the parenthesis, so every such vote was credited to the representative who didn't cast it. The printed form is
now kept; the people data gives each substitute that form as a dated other name, so only they match it.

District names ("Crane(12)", OPEN-680) and "Mr. Speaker" are unchanged.

The fixtures are legislature.idaho.gov's own 2026 bill pages, read 2026-11-23 (tests/fixtures/id_open787). Who sat for
whom is from the 2026 House Final Journal's designation letters.
"""
import json
import os
import sys
import types
from collections import Counter, defaultdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from id.bills import IDBillScraper  # noqa: E402

from openstates.scrape import VoteEvent  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "id_open787")


@pytest.fixture
def scraper(tmp_path, monkeypatch):
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text(
        "id:\n  votes:\n    house_speaker_by_session:\n      '2026': Mike Moyle\n"
    )
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    scraper = IDBillScraper.__new__(IDBillScraper)
    scraper._subjects = defaultdict(list)
    scraper.warning = lambda *a, **k: None
    return scraper


def house_roll_call(scraper, name, bill_id, date):
    text = open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8").read()
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(text=text)
    (vote,) = [
        v
        for v in scraper.scrape_bill("lower", "2026", bill_id)
        if isinstance(v, VoteEvent)
        and json.loads(v.organization[1:])["classification"] == "lower"
        and v.start_date == date
    ]
    return vote


# (page, bill, House roll call's day, the substitutes it prints)
HOUSE = [
    ("h0491_2026", "H 491", "2026-01-26", {"Hall(Stone)"}),
    ("h0516_2026", "H 516", "2026-02-17", {"Hall(Stone)", "Redman(Zaken)"}),
    (
        "h0658_2026",
        "H 658",
        "2026-03-02",
        {"Hall(Stone)", "Haws(Woller)", "Hill(Brown)"},
    ),
    ("h0545_2026", "H 545", "2026-03-09", {"Hall(Stone)", "Erickson(Larsen)"}),
    (
        "h0516_2026",
        "H 516",
        "2026-04-02",
        {
            "Hall(Stone)",
            "Cannon(Cannon)",
            "Egbert(Beazer)",
            "Hill(Hill)",
            "Shirts(Batt)",
        },
    ),
]
DISTRICT_NAMES = {"Crane(12)", "Crane(13)", "Tanner(13)", "Tanner(14)"}


@pytest.mark.parametrize("name,bill_id,date,printed", HOUSE)
def test_house_substitutes_keep_the_printed_form(scraper, name, bill_id, date, printed):
    vote = house_roll_call(scraper, name, bill_id, date)
    voters = Counter(v["voter_name"] for v in vote.votes)
    # every non-district parenthesis on the row is a substitute, kept as printed
    assert {v for v in voters if "(" in v} - DISTRICT_NAMES == printed
    for v in vote.votes:
        if v["voter_name"] in printed:
            # the voter id asks for the printed form only, which no sitting member carries
            assert get_pseudo_id(v["voter_id"]) == {"name": v["voter_name"]}
    # the seat holder's bare surname is gone ("Hill(Hill)": Randolph J. Hill in Ted Hill's seat)
    assert not {p.split("(")[0] for p in printed} & set(voters)
    # one voter per seat: 70 representatives, none counted twice
    assert len(vote.votes) == 70
    assert max(voters.values()) == 1


def test_district_names_and_speaker_are_unchanged(scraper):
    vote = house_roll_call(scraper, "h0516_2026", "H 516", "2026-04-02")
    ids = {v["voter_name"]: get_pseudo_id(v["voter_id"]) for v in vote.votes}
    assert DISTRICT_NAMES <= set(ids)
    assert ids["Crane(12)"]["family_name__iexact"] == "Crane"
    assert "memberships__post__label__regex" in ids["Crane(12)"]
    assert ids["Mr. Speaker"] == {"name": "Mike Moyle"}
