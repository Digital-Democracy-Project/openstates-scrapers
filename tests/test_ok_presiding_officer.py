"""OPEN-790: "Mr. Speaker" on an Oklahoma House roll call is the session's Speaker, read from the
manifest's votes.house_speaker_by_session through utils/presiding_officers.py (the reader Louisiana,
OPEN-764, and Rhode Island, OPEN-785, use). With no manifest value the title stays as printed.

The fixtures are the real House and Senate vote pages already used by OPEN-687 and OPEN-704
(oklegislature.gov/cf/2025-26 SUPPORT DOCUMENTS/votes/House|Senate/<bill>_VOTES.HTM), run through
the scraper's own scrape_votes(). A House floor roll call lists "Mr. Speaker"; a committee roll call
never does (2026 HB 3005: two floor roll calls and a committee one). The pages and roll calls used
here list the Speaker whether or not OPEN-789 (Crosswhite Hader read as one name) is in: without it,
some other roll calls lose the Speaker's line to the extra "Hader".
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

from ok.bills import OKBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
OK = "ok:\n  votes:\n    house_speaker_by_session:\n      '2025': Kyle Hilbert\n"


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    """Point the manifest reader at a file holding `text` (a new file each time: the reader
    caches a file by its modification time)."""
    written = []

    def write(text):
        written.append(text)
        path = tmp_path / "jurisdictions{}.yaml".format(len(written))
        path.write_text(text)
        monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(path))

    return write


class _Resp:
    def __init__(self, text):
        self.text = text


def roll_calls(path, session="2025", scraper=None):
    """[(chamber, motion, {printed name: (option, voter id spec)})] for one real page."""
    raw = open(os.path.join(FIXTURES, path), "rb").read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    if scraper is None:
        scraper = OKBillScraper.__new__(OKBillScraper)
        scraper.warning = mock.Mock()
    scraper.get = lambda url, verify=False: _Resp(text)
    chamber = "House" if "House" in path else "Senate"
    bill = Bill("HB 1", legislative_session=session, chamber="lower", title="t")
    url = "https://www.oklegislature.gov/cf/votes/%s/x_VOTES.HTM" % chamber
    return [
        (
            get_pseudo_id(v.organization)["classification"],
            v.motion_text,
            {
                x["voter_name"]: (x["option"], get_pseudo_id(x["voter_id"]))
                for x in v.votes
            },
        )
        for v in scraper.scrape_votes(bill, url)
    ]


def test_house_mr_speaker_is_the_sessions_speaker(manifest):
    manifest(OK)
    votes = roll_calls("ok_open704/House_HB3005_VOTES.HTM")
    votes += roll_calls("ok_open687/House_SCR1_VOTES.HTM")
    with_title = [names for _, _, names in votes if "Mr. Speaker" in names]
    # HB 3005's two floor roll calls and SCR 1's adoption; HB 3005's committee vote has none
    assert len(votes) == 4 and len(with_title) == 3
    for names in with_title:
        option, spec = names["Mr. Speaker"]
        assert spec == {"name": "Kyle Hilbert"}
        # everyone else keeps their printed name
        assert all(
            s == {"name": n} for n, (_, s) in names.items() if n != "Mr. Speaker"
        )


def test_the_speakers_option_is_kept(manifest):
    manifest(OK)
    # 2025 HB 1003: the Speaker voted no on "Adopt Amendment" (47-39), yes on "Table Amendment"
    votes = roll_calls("ok_open687/House_HB1003_VOTES.HTM")
    options = {m: n["Mr. Speaker"] for _, m, n in votes if "Mr. Speaker" in n}
    assert options["Adopt Amendment"] == ("no", {"name": "Kyle Hilbert"})
    assert options["Table Amendment"] == ("yes", {"name": "Kyle Hilbert"})


def test_no_manifest_value_leaves_the_title_and_warns_once(manifest):
    manifest(OK)
    scraper = OKBillScraper.__new__(OKBillScraper)
    scraper.warning = mock.Mock()
    votes = roll_calls("ok_open687/House_HB1003_VOTES.HTM", "2027", scraper)
    specs = [n["Mr. Speaker"][1] for _, _, n in votes if "Mr. Speaker" in n]
    assert specs and all(s == {"name": "Mr. Speaker"} for s in specs)
    assert scraper.warning.call_count == 1
    assert "house_speaker_by_session" in scraper.warning.call_args[0]


def test_no_ok_entry_at_all_leaves_the_title(manifest):
    manifest("la:\n  votes:\n    house_speaker_by_session:\n      '2025': Someone\n")
    votes = roll_calls("ok_open687/House_HB1003_VOTES.HTM")
    specs = [n["Mr. Speaker"][1] for _, _, n in votes if "Mr. Speaker" in n]
    assert specs and all(s == {"name": "Mr. Speaker"} for s in specs)


def test_senate_pages_are_unchanged(manifest):
    # the Senate prints no title; a "Mr. Speaker" there would not be the House Speaker
    manifest(OK)
    for path in (
        "ok_open687/Senate_SB1050_VOTES.HTM",
        "ok_open687/Senate_SB6_VOTES.HTM",
    ):
        votes = roll_calls(path)
        assert votes
        for chamber, _, names in votes:
            assert chamber == "upper"
            assert all(s == {"name": n} for n, (_, s) in names.items())
