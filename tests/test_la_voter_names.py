"""OPEN-764: "Mr. Speaker" and "Mr. President" on a Louisiana roll call are the session's
presiding officers, read from the manifest.

The fixtures (la_open764/) are real 2026 Regular Session roll-call PDFs as legis.la.gov serves
them (ViewDocument.aspx?d=<file name>), saved for the PA/NE/LA go-live spot check (OPEN-447),
unchanged, run through the scraper's own scrape_vote with no network:
- 1471686: House, SB 185 final passage, "Mr. Speaker" among 98 yeas (YEAS 98, NAYS 0, ABSENT 7).
- 1474935: House, HB 956 concurrence, "Mr. Speaker" among 10 absent (YEAS 95, NAYS 0, ABSENT 10).
- 1457825: Senate, SB 359 final passage, "Mr. President" among 36 yeas (YEAS 36, NAYS 0, ABSENT 3).
- 1450816: Senate, SB 101 final passage, "Mr. President" the one absent (YEAS 37, NAYS 0, ABSENT 1).
Who the officers are comes from the manifest's votes.house_speaker_by_session and
votes.senate_president_by_session, as Idaho (OPEN-680), Mississippi (OPEN-731) and Missouri
(OPEN-738) read the Speaker.
"""
import os
import shutil
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from la.bills import LABillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "la_open764")
HOUSE_YEA, HOUSE_ABSENT = "1471686.pdf", "1474935.pdf"
SENATE_YEA, SENATE_ABSENT = "1457825.pdf", "1450816.pdf"
CHAMBER = {
    HOUSE_YEA: "House",
    HOUSE_ABSENT: "House",
    SENATE_YEA: "Senate",
    SENATE_ABSENT: "Senate",
}
# each PDF's own "Total --" lines: YEAS, NAYS, ABSENT
TOTALS = {
    HOUSE_YEA: (98, 0, 7),
    HOUSE_ABSENT: (95, 0, 10),
    SENATE_YEA: (36, 0, 3),
    SENATE_ABSENT: (37, 0, 1),
}
BOTH = (
    "la:\n  votes:\n"
    "    house_speaker_by_session:\n      '2026': Phillip DeVillier\n"
    "    senate_president_by_session:\n      '2026': Cameron Henry\n"
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


def roll_call(pdf, session="2026", chamber=None, scraper=None):
    """{printed name: (option, voter id spec)} for one fixture, as scrape_vote makes it."""
    scraper = scraper or LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.urlretrieve = lambda url, path: shutil.copy(
        os.path.join(FIXTURES, pdf), path
    )
    bill = Bill("SB 1", session, "x", chamber="upper")
    link = "{} Vote on SB 1, FINAL PASSAGE (#1)".format(chamber or CHAMBER[pdf])
    (vote,) = scraper.scrape_vote(bill, link, "https://www.legis.la.gov/x")
    return {
        v["voter_name"]: (v["option"], get_pseudo_id(v["voter_id"])) for v in vote.votes
    }


@pytest.mark.parametrize(
    "pdf,title,expected",
    [
        (HOUSE_YEA, "Mr. Speaker", ("yes", {"name": "Phillip DeVillier"})),
        (HOUSE_ABSENT, "Mr. Speaker", ("other", {"name": "Phillip DeVillier"})),
        (SENATE_YEA, "Mr. President", ("yes", {"name": "Cameron Henry"})),
        (SENATE_ABSENT, "Mr. President", ("other", {"name": "Cameron Henry"})),
    ],
)
def test_presiding_officer_comes_from_the_manifest(manifest, pdf, title, expected):
    manifest(BOTH)
    assert roll_call(pdf)[title] == expected


def test_each_chamber_reads_its_own_field(manifest):
    manifest(
        "la:\n  votes:\n    house_speaker_by_session:\n      '2026': Phillip DeVillier\n"
    )
    assert roll_call(HOUSE_YEA)["Mr. Speaker"][1] == {"name": "Phillip DeVillier"}
    assert roll_call(SENATE_YEA)["Mr. President"][1] == {"name": "Mr. President"}
    manifest(
        "la:\n  votes:\n    senate_president_by_session:\n      '2026': Cameron Henry\n"
    )
    assert roll_call(SENATE_YEA)["Mr. President"][1] == {"name": "Cameron Henry"}
    assert roll_call(HOUSE_YEA)["Mr. Speaker"][1] == {"name": "Mr. Speaker"}


def test_officer_is_read_for_the_roll_calls_session(manifest):
    manifest(
        "la:\n  votes:\n"
        "    house_speaker_by_session:\n      '2026': Phillip DeVillier\n      2024s1: Someone Else\n"
        "    senate_president_by_session:\n      2026: Cameron Henry\n      2024s1: Another One\n"
    )
    assert roll_call(HOUSE_YEA, session="2024s1")["Mr. Speaker"][1] == {
        "name": "Someone Else"
    }
    assert roll_call(SENATE_YEA, session="2024s1")["Mr. President"][1] == {
        "name": "Another One"
    }
    # an unquoted 2026 in the manifest is a number; it still names the "2026" session
    assert roll_call(SENATE_YEA)["Mr. President"][1] == {"name": "Cameron Henry"}


@pytest.mark.parametrize(
    "text",
    [
        "la:\n  votes:\n    house_speaker_by_session:\n      '2025': Phillip DeVillier\n"
        "    senate_president_by_session:\n      '2025': Cameron Henry\n",
        "la:\n  votes:\n    house_speaker_by_session: null\n    senate_president_by_session: null\n",
        "la:\n  name: Louisiana\n",
        "ms:\n  votes:\n    house_speaker_by_session:\n      '2026': Jason White\n",
    ],
    ids=["session-not-listed", "null", "no-votes-block", "another-state"],
)
def test_title_kept_with_one_warning_when_the_manifest_has_no_name(manifest, text):
    manifest(text)
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.warning = mock.Mock()
    assert roll_call(HOUSE_YEA, scraper=scraper)["Mr. Speaker"] == (
        "yes",
        {"name": "Mr. Speaker"},
    )
    roll_call(
        HOUSE_ABSENT, scraper=scraper
    )  # same session and title: no second warning
    assert roll_call(SENATE_YEA, scraper=scraper)["Mr. President"] == (
        "yes",
        {"name": "Mr. President"},
    )
    warned = [c.args for c in scraper.warning.call_args_list if "OPEN-764" in c.args[0]]
    assert [a[1:3] for a in warned] == [
        ("house_speaker_by_session", "2026"),
        ("senate_president_by_session", "2026"),
    ]


def test_no_warning_when_the_manifest_names_the_officer(manifest):
    manifest(BOTH)
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.warning = mock.Mock()
    roll_call(HOUSE_YEA, scraper=scraper)
    roll_call(SENATE_ABSENT, scraper=scraper)
    assert not [c for c in scraper.warning.call_args_list if "OPEN-764" in c.args[0]]


def test_a_title_is_only_its_own_chambers_officer(manifest):
    """A House roll call's "Mr. Speaker" is never read as a Senate title, and the other way."""
    manifest(BOTH)
    assert roll_call(HOUSE_YEA, chamber="Senate")["Mr. Speaker"][1] == {
        "name": "Mr. Speaker"
    }
    assert roll_call(SENATE_YEA, chamber="House")["Mr. President"][1] == {
        "name": "Mr. President"
    }


@pytest.mark.parametrize("pdf", sorted(TOTALS))
def test_votes_counts_and_every_other_name_are_unchanged(manifest, pdf):
    manifest(BOTH)
    voters = roll_call(pdf)
    yeas, nays, absent = TOTALS[pdf]
    options = [option for option, _ in voters.values()]
    assert (
        options.count("yes"),
        options.count("no"),
        options.count("other"),
    ) == TOTALS[pdf]
    assert len(voters) == yeas + nays + absent
    for name, (_, spec) in voters.items():
        if name not in ("Mr. Speaker", "Mr. President"):
            assert spec == {"name": name}
