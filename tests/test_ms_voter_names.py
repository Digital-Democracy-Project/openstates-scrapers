"""OPEN-731: "Mr. Speaker" on a Mississippi House roll call is the session's Speaker.

The fixture is the text (pdftotext) of a real House roll-call PDF, 2026 HB 1 "Passed As
Amended" (billstatus.ls.state.ms.us/2026/pdf/votes/house/0030003.pdf, saved for OPEN-693 on
2026-11-20), run through the scraper's own scrape_votes() with no network. It prints
"Mr. Speaker" among 116 yeas. Who that is comes from the manifest's
votes.house_speaker_by_session, as Idaho does (OPEN-680).
"""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

import ms.bills  # noqa: E402
from ms.bills import MSBillScraper  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "ms_open693", "2026_house_0030003.txt"
)


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


def roll_call(monkeypatch, tmp_path, chamber="lower", session="2026"):
    """{printed name: (option, voter id spec)} for the fixture's roll call."""
    text = open(FIXTURE, "rb").read()
    scraper = MSBillScraper.__new__(MSBillScraper)

    def urlretrieve(url, verify=False):
        path = tmp_path / "vote.pdf"
        path.write_bytes(b"")
        return str(path), None

    monkeypatch.setattr(scraper, "urlretrieve", urlretrieve, raising=False)
    monkeypatch.setattr(ms.bills, "convert_pdf", lambda path, kind: text)
    bill = Bill("HB 1", legislative_session=session, chamber="lower", title="t")
    (vote,) = scraper.scrape_votes(
        "http://billstatus.ls.state.ms.us/2026/pdf/votes/house/0030003.pdf",
        "Passed As Amended",
        datetime(2026, 1, 1),
        chamber,
        bill,
    )
    return {
        v["voter_name"]: (v["option"], get_pseudo_id(v["voter_id"])) for v in vote.votes
    }


def test_speaker_comes_from_the_manifest(monkeypatch, tmp_path, manifest):
    manifest("ms:\n  votes:\n    house_speaker_by_session:\n      2026: Jason White\n")
    voters = roll_call(monkeypatch, tmp_path)
    assert voters["Mr. Speaker"] == ("yes", {"name": "Jason White"})


def test_speaker_left_as_printed_when_the_manifest_has_no_session(
    monkeypatch, tmp_path, manifest
):
    manifest(
        "ms:\n  votes:\n    house_speaker_by_session:\n      '2025': Jason White\n"
    )
    assert roll_call(monkeypatch, tmp_path)["Mr. Speaker"] == (
        "yes",
        {"name": "Mr. Speaker"},
    )
    manifest("ms:\n  votes:\n    house_speaker_by_session: null\n")
    assert roll_call(monkeypatch, tmp_path)["Mr. Speaker"] == (
        "yes",
        {"name": "Mr. Speaker"},
    )


def test_speaker_is_read_for_the_bills_session(monkeypatch, tmp_path, manifest):
    manifest(
        "ms:\n  votes:\n    house_speaker_by_session:\n"
        "      '2026': Jason White\n      '20261E': Someone Else\n"
    )
    voters = roll_call(monkeypatch, tmp_path, session="20261E")
    assert voters["Mr. Speaker"] == ("yes", {"name": "Someone Else"})


def test_another_states_speaker_is_not_used(monkeypatch, tmp_path, manifest):
    manifest("id:\n  votes:\n    house_speaker_by_session:\n      '2026': Mike Moyle\n")
    assert roll_call(monkeypatch, tmp_path)["Mr. Speaker"][1] == {"name": "Mr. Speaker"}


def test_speaker_is_a_house_name_only(monkeypatch, tmp_path, manifest):
    manifest(
        "ms:\n  votes:\n    house_speaker_by_session:\n      '2026': Jason White\n"
    )
    voters = roll_call(monkeypatch, tmp_path, chamber="upper")
    assert voters["Mr. Speaker"][1] == {"name": "Mr. Speaker"}


def test_every_other_name_is_unchanged(monkeypatch, tmp_path, manifest):
    manifest(
        "ms:\n  votes:\n    house_speaker_by_session:\n      '2026': Jason White\n"
    )
    voters = roll_call(monkeypatch, tmp_path)
    # 116 yeas + 6 "Absent or those not voting", as the roll call prints them
    # ("Total--116", "Total--6"; the scraper files the six under "not voting")
    assert len(voters) == 122
    assert sum(option == "yes" for option, _ in voters.values()) == 116
    assert voters["Anderson (110th)"] == ("yes", {"name": "Anderson (110th)"})
    assert voters["Lamar"] == ("not voting", {"name": "Lamar"})
    for name, (_, spec) in voters.items():
        if name != "Mr. Speaker":
            assert spec == {"name": name}
