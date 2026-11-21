"""OPEN-738: "MR SPEAKER" on a Missouri House roll call is the session's Speaker.

The fixture is a real House roll-call PDF, 2026 HB 2885 third reading
(documents.house.mo.gov/billtracking/bills261/rollcalls/049.010.pdf, saved for OPEN-696),
run through the scraper's own House walk with no network. It prints "MR SPEAKER" among 112
yeas. Who that is comes from the manifest's votes.house_speaker_by_session, as Idaho
(OPEN-680) and Mississippi (OPEN-731) do.
"""
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils import convert_pdf, get_pseudo_id  # noqa: E402

from mo import Missouri  # noqa: E402
from mo.votes import MOVoteScraper, parse_house_rollcall  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mo_open696")
ROLL_CALL = "house_rollcall_049.010.pdf"
CODES = {"2026": "261", "2025S1": "253"}


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


def house_roll_call(tmp_path, session="2026"):
    """{printed name: (option, voter id spec)} for the fixture, as the House walk makes it."""
    url = (
        f"https://documents.house.mo.gov/billtracking/bills{CODES[session]}"
        "/rollcalls/001.001.pdf"
    )
    downloads = tmp_path / "downloads"
    downloads.mkdir(exist_ok=True)
    scraper = MOVoteScraper(Missouri(), str(tmp_path))

    def urlretrieve(requested, *args, **kwargs):
        copy = str(downloads / f"dl{len(os.listdir(downloads))}")
        name = ROLL_CALL if requested == url else "house_rollcall_missing.html"
        shutil.copy(os.path.join(FIXTURES, name), copy)
        return copy, None

    scraper.urlretrieve = urlretrieve
    (vote,) = scraper._scrape_lower_chamber(session)
    return {
        v["voter_name"]: (v["option"], get_pseudo_id(v["voter_id"])) for v in vote.votes
    }


def test_speaker_comes_from_the_manifest(tmp_path, manifest):
    manifest(
        "mo:\n  votes:\n    house_speaker_by_session:\n      2026: Jonathan Patterson\n"
    )
    voters = house_roll_call(tmp_path)
    assert voters["MR SPEAKER"] == ("yes", {"name": "Jonathan Patterson"})


def test_speaker_left_as_printed_when_the_manifest_has_no_session(tmp_path, manifest):
    manifest(
        "mo:\n  votes:\n    house_speaker_by_session:\n      '2025': Jonathan Patterson\n"
    )
    assert house_roll_call(tmp_path)["MR SPEAKER"] == ("yes", {"name": "MR SPEAKER"})
    manifest("mo:\n  votes:\n    house_speaker_by_session: null\n")
    assert house_roll_call(tmp_path)["MR SPEAKER"] == ("yes", {"name": "MR SPEAKER"})


def test_speaker_is_read_for_the_roll_calls_session(tmp_path, manifest):
    manifest(
        "mo:\n  votes:\n    house_speaker_by_session:\n"
        "      '2026': Jonathan Patterson\n      2025S1: Someone Else\n"
    )
    voters = house_roll_call(tmp_path, session="2025S1")
    assert voters["MR SPEAKER"] == ("yes", {"name": "Someone Else"})


def test_another_states_speaker_is_not_used(tmp_path, manifest):
    manifest(
        "ms:\n  votes:\n    house_speaker_by_session:\n      '2026': Jason White\n"
    )
    assert house_roll_call(tmp_path)["MR SPEAKER"][1] == {"name": "MR SPEAKER"}


def test_speaker_is_a_house_name_only(tmp_path, manifest):
    manifest(
        "mo:\n  votes:\n    house_speaker_by_session:\n      '2026': Jonathan Patterson\n"
    )
    text = convert_pdf(os.path.join(FIXTURES, ROLL_CALL), type="text")
    rc = parse_house_rollcall(text.decode("utf-8"))
    vote = MOVoteScraper(Missouri(), str(tmp_path))._make_vote(
        "2026", "upper", rc, "k", [], ["passage"]
    )
    speaker = next(v for v in vote.votes if v["voter_name"] == "MR SPEAKER")
    assert get_pseudo_id(speaker["voter_id"]) == {"name": "MR SPEAKER"}


def test_every_other_name_is_unchanged(tmp_path, manifest):
    manifest(
        "mo:\n  votes:\n    house_speaker_by_session:\n      '2026': Jonathan Patterson\n"
    )
    voters = house_roll_call(tmp_path)
    # the PDF's own totals: Yes 112, No 27, Present 0, Absent 19
    assert len(voters) == 158
    assert sum(option == "yes" for option, _ in voters.values()) == 112
    assert voters["SMITH (46)"] == ("yes", {"name": "SMITH (46)"})
    assert voters["DURNELL"] == ("no", {"name": "DURNELL"})
    for name, (_, spec) in voters.items():
        if name != "MR SPEAKER":
            assert spec == {"name": name}
