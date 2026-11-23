"""OPEN-680: Idaho House roll-call names in a form the importer can match.

The fixture is the 02/11 House vote row of S 1222 (2026), saved from
https://legislature.idaho.gov/sessioninfo/2026/legislation/S1222/ on 2026-11-20. It
prints "Crane(12)", "Crane(13)", "Tanner(13)", "Tanner(14)" and "Mr. Speaker"; the House
seats in the people data are Jaron Crane 12B, Brent Crane 13A, Steve Tanner 13B and Josh
Tanner 14B.
"""
import os
import re
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from id.bills import IDBillScraper  # noqa: E402
from id.voter_names import voter_pseudo_id  # noqa: E402

from openstates.utils import get_pseudo_id  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "id_open680",
    "s1222_2026_house_third_reading_row.html",
)

DISTRICT_NAMES = {"Crane(12)", "Crane(13)", "Tanner(13)", "Tanner(14)"}


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    """Point the manifest reader at a file holding `text` (a new file each time: the
    reader caches a file by its modification time)."""
    written = []

    def write(text):
        written.append(text)
        path = tmp_path / "jurisdictions{}.yaml".format(len(written))
        path.write_text(text)
        monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(path))

    return write


def house_vote():
    row = lxml.html.fromstring(open(FIXTURE).read()).xpath("//tr")[0]
    scraper = IDBillScraper.__new__(IDBillScraper)
    (vote,) = scraper.parse_vote(
        "lower", "2026-02-11", row[2], "2026", "S 1222", "upper", "https://x"
    )
    return {v["voter_name"]: get_pseudo_id(v["voter_id"]) for v in vote.votes}


def seat_matches(spec, label):
    return re.search(spec["memberships__post__label__regex"], label) is not None


def test_district_names_ask_for_that_surname_in_that_district(manifest):
    manifest("id: {}\n")
    voters = house_vote()
    assert DISTRICT_NAMES <= set(voters)
    assert voters["Crane(12)"]["family_name__iexact"] == "Crane"
    assert voters["Tanner(14)"]["family_name__iexact"] == "Tanner"
    # the people data's seats: each name picks exactly its own member's seat
    seats = {"Jaron Crane": "12B", "Brent Crane": "13A"}
    assert [n for n, s in seats.items() if seat_matches(voters["Crane(12)"], s)] == [
        "Jaron Crane"
    ]
    assert [n for n, s in seats.items() if seat_matches(voters["Crane(13)"], s)] == [
        "Brent Crane"
    ]
    seats = {"Steve Tanner": "13B", "Josh Tanner": "14B"}
    assert [n for n, s in seats.items() if seat_matches(voters["Tanner(13)"], s)] == [
        "Steve Tanner"
    ]
    assert [n for n, s in seats.items() if seat_matches(voters["Tanner(14)"], s)] == [
        "Josh Tanner"
    ]
    for name in DISTRICT_NAMES:
        assert set(voters[name]) == {
            "family_name__iexact",
            "memberships__post__label__regex",
        }


def test_district_number_matches_whole_seat_number_only():
    spec = get_pseudo_id(voter_pseudo_id("Smith(1)", "lower", "2026"))
    assert [
        s for s in ("1A", "1B", "1", "10A", "11B", "21A", "12") if seat_matches(spec, s)
    ] == [
        "1A",
        "1B",
        "1",
    ]


def test_speaker_comes_from_the_manifest(manifest):
    manifest("id:\n  votes:\n    house_speaker_by_session:\n      2026: Mike Moyle\n")
    assert house_vote()["Mr. Speaker"] == {"name": "Mike Moyle"}


def test_speaker_left_as_printed_when_the_manifest_has_no_session(manifest):
    manifest("id:\n  votes:\n    house_speaker_by_session:\n      2025: Mike Moyle\n")
    assert house_vote()["Mr. Speaker"] == {"name": "Mr. Speaker"}
    manifest("id: {}\n")
    assert house_vote()["Mr. Speaker"] == {"name": "Mr. Speaker"}


def test_speaker_is_a_house_name_only(manifest):
    manifest("id:\n  votes:\n    house_speaker_by_session:\n      '2026': Mike Moyle\n")
    assert get_pseudo_id(voter_pseudo_id("Mr. Speaker", "upper", "2026")) == {
        "name": "Mr. Speaker"
    }


def test_every_other_name_is_unchanged(manifest):
    manifest("id: {}\n")
    voters = house_vote()
    # 69 ayes + 1 absent, as the row prints them; the substitutes keep their printed form
    # (OPEN-787: "Hall(Stone)" is Grayson Stone, "Mathias(Carlson)" is Jeff Carlson)
    assert len(voters) == 70
    assert "Hall(Stone)" in voters and "Mathias(Carlson)" in voters
    assert "Hall" not in voters and "Mathias" not in voters
    for name, spec in voters.items():
        if name not in DISTRICT_NAMES:
            assert spec == {"name": name}
