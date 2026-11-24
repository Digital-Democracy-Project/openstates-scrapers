"""OPEN-815: "Speaker" and "Mr. President" on a Maryland roll call are the session's presiding
officers, read from the manifest (utils/presiding_officers.py, shared with Louisiana OPEN-764,
Rhode Island OPEN-785 and Massachusetts OPEN-810).

The fixtures (md_open815/) are real roll-call PDFs as mgaleg.maryland.gov serves them
(<session>/votes/<chamber>/<seq>.pdf, read 2026-11-23), unchanged, run through the scraper's own
scrape_vote and its convert_pdf with no network. Read off the PDFs by hand:
- 2026RS house 0889: SB 283 third reading, Mar 11 2026, "Presiding: Speaker", "Speaker" voting
  yea (129 Yeas, 2 Nays, 8 Not Voting, 0 Excused, 2 Absent).
- 2026RS house 1483: HB 769 final passage, Mar 30 2026, "Presiding: Clippinger", "Speaker" voting
  yea, Clippinger printed nowhere else and Pena-Melnyk printed by name as absent: the delegate in
  the chair cast the title's vote (112, 22, 4, 0, 3).
- 2026RS senate 0058: SB 1 third reading, Feb 3 2026, "Mr. President" voting yea (31, 13, 0, 0, 3).
- 2026S1 house 1742: HB 2100 amendment ruling, Aug 3 2026, "Presiding: Clippinger" but Clippinger
  also voting yea by name, so "Speaker" (not voting) is the Speaker (96, 36, 6, 0, 3).
- 2026S1 senate 1404: HB 2100 motion to limit debate, Aug 4 2026, "Mr. President" voting yea
  (31, 13, 2, 0, 1).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from md.votes import MDVoteScraper, add_voter  # noqa: E402
from openstates.scrape import VoteEvent  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402
from utils import presiding_officers  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "md_open815")
HOUSE, HOUSE_STAND_IN, SENATE = (
    "2026rs_house_0889",
    "2026rs_house_1483",
    "2026rs_senate_0058",
)
HOUSE_SPECIAL, SENATE_SPECIAL = "2026s1_house_1742", "2026s1_senate_1404"
SESSION = {
    HOUSE: "2026",
    HOUSE_STAND_IN: "2026",
    SENATE: "2026",
    HOUSE_SPECIAL: "2026s1",
    SENATE_SPECIAL: "2026s1",
}
TITLE = {
    HOUSE: "Speaker",
    HOUSE_STAND_IN: "Speaker",
    SENATE: "Mr. President",
    HOUSE_SPECIAL: "Speaker",
    SENATE_SPECIAL: "Mr. President",
}
# the title's printed option on each roll call
OPTION = {
    HOUSE: "yes",
    HOUSE_STAND_IN: "yes",
    SENATE: "yes",
    HOUSE_SPECIAL: "not voting",
    SENATE_SPECIAL: "yes",
}
# each PDF's own counts line: Yeas, Nays, Not Voting, Excused, Absent
TOTALS = {
    HOUSE: (129, 2, 8, 0, 2),
    HOUSE_STAND_IN: (112, 22, 4, 0, 3),
    SENATE: (31, 13, 0, 0, 3),
    HOUSE_SPECIAL: (96, 36, 6, 0, 3),
    SENATE_SPECIAL: (31, 13, 2, 0, 1),
}
OPTIONS = ("yes", "no", "not voting", "excused", "absent")
MD = (
    "md:\n  votes:\n"
    "    house_speaker_by_session:\n      '2026': Joseline Peña-Melnyk\n"
    "      2026s1: Joseline Peña-Melnyk\n"
    "    senate_president_by_session:\n      '2026': Bill Ferguson\n"
    "      2026s1: Bill Ferguson\n"
)
OFFICER = {"house": "Joseline Peña-Melnyk", "senate": "Bill Ferguson"}


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


class _Votes(MDVoteScraper):
    """The real scraper reading a saved PDF in place of the site."""

    def __init__(self):
        self.warnings = []

    def urlretrieve(self, url):
        session, _, chamber, seq = url.lower().rsplit("/", 4)[-4:]
        name = "{}_{}_{}".format(session, chamber, seq)
        return os.path.join(FIXTURES, name), None

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)


def roll_call(name, scraper=None):
    """The one VoteEvent of a saved PDF, through scrape_vote (convert_pdf included)."""
    session, chamber, seq = name.split("_")
    url = "https://mgaleg.maryland.gov/{}/votes/{}/{}.pdf".format(
        session.upper(), chamber, seq
    )
    (vote,) = (scraper or _Votes()).scrape_vote(url, SESSION[name])
    return vote


def voters(vote):
    """{printed name: (option, voter id spec)}"""
    return {
        v["voter_name"]: (v["option"], get_pseudo_id(v["voter_id"])) for v in vote.votes
    }


@pytest.mark.parametrize("name", [HOUSE, SENATE, HOUSE_SPECIAL, SENATE_SPECIAL])
def test_title_is_the_sessions_officer(manifest, name):
    manifest(MD)
    assert voters(roll_call(name))[TITLE[name]] == (
        OPTION[name],
        {"name": OFFICER[name.split("_")[1]]},
    )


def test_a_member_in_the_chair_printed_nowhere_else_cast_the_title(manifest):
    """1483: "Presiding: Clippinger"; the Speaker is printed by name as absent, so "Speaker" is
    Clippinger's vote, not a second vote by the Speaker."""
    manifest(MD)
    names = voters(roll_call(HOUSE_STAND_IN))
    assert names["Speaker"] == ("yes", {"name": "Clippinger"})
    assert names["Peña-Melnyk"] == ("absent", {"name": "Peña-Melnyk"})
    assert "Clippinger" not in names


def test_a_member_in_the_chair_printed_by_name_leaves_the_title_to_the_officer(
    manifest,
):
    """1742: "Presiding: Clippinger" but Clippinger votes yea by name."""
    manifest(MD)
    names = voters(roll_call(HOUSE_SPECIAL))
    assert names["Clippinger"] == ("yes", {"name": "Clippinger"})
    assert names["Speaker"] == ("not voting", {"name": "Joseline Peña-Melnyk"})


@pytest.mark.parametrize("name", sorted(TOTALS))
def test_counts_and_every_other_name_are_unchanged(manifest, name):
    manifest(MD)
    vote = roll_call(name)
    names = voters(vote)
    options = [option for option, _ in names.values()]
    assert tuple(options.count(o) for o in OPTIONS) == TOTALS[name]
    assert len(names) == sum(TOTALS[name])
    for printed, (_, spec) in names.items():
        if printed != TITLE[name]:
            assert spec == {"name": printed}


@pytest.mark.parametrize(
    "text",
    [
        "md:\n  votes:\n    house_speaker_by_session:\n      '2025': Joseline Peña-Melnyk\n"
        "    senate_president_by_session:\n      '2025': Bill Ferguson\n",
        "md:\n  votes:\n    house_speaker_by_session: null\n"
        "    senate_president_by_session: null\n",
        "md:\n  name: Maryland\n",
        "la:\n  votes:\n    house_speaker_by_session:\n      '2026': Phillip DeVillier\n"
        "    senate_president_by_session:\n      '2026': Cameron Henry\n",
    ],
    ids=["session-not-listed", "null", "no-votes-block", "another-state"],
)
def test_title_kept_with_one_warning_when_the_manifest_has_no_name(manifest, text):
    manifest(text)
    scraper = _Votes()
    for name in (HOUSE, SENATE, HOUSE_SPECIAL, SENATE_SPECIAL, HOUSE):
        assert voters(roll_call(name, scraper))[TITLE[name]] == (
            OPTION[name],
            {"name": TITLE[name]},
        )
    warned = [w for w in scraper.warnings if "OPEN-815" in w]
    # one warning per field and session, though the 2026 House roll call was read twice
    assert [w.split(" on ")[0] for w in warned] == [
        "OPEN-815: manifest md.votes.house_speaker_by_session has no 2026",
        "OPEN-815: manifest md.votes.senate_president_by_session has no 2026",
        "OPEN-815: manifest md.votes.house_speaker_by_session has no 2026s1",
        "OPEN-815: manifest md.votes.senate_president_by_session has no 2026s1",
    ]


def test_no_warning_when_the_manifest_names_the_officers(manifest):
    manifest(MD)
    scraper = _Votes()
    for name in sorted(TOTALS):
        roll_call(name, scraper)
    assert not [w for w in scraper.warnings if "OPEN-815" in w]


def test_a_dated_session_gives_the_officer_in_office_on_the_roll_calls_day(manifest):
    """A mid-session change (the per-day form) is read by the roll call's legislative date."""
    manifest(
        "md:\n  votes:\n    house_speaker_by_session:\n      '2026':\n"
        "        '2026-01-14': First Officer\n        '2026-03-01': Second Officer\n"
    )
    assert voters(roll_call(HOUSE))["Speaker"][1] == {"name": "Second Officer"}
    assert (
        presiding_officers.officer(
            "md", "house_speaker_by_session", "2026", "2026-02-28"
        )
        == "First Officer"
    )


@pytest.mark.parametrize("stand_in", [None, "Clippinger"])
def test_a_title_is_only_its_own_chambers_officer(manifest, stand_in):
    """A "Speaker" on a Senate roll call (or "Mr. President" on a House one) is never given the
    officer or the member in the chair."""
    manifest(MD)
    for chamber, title in (("upper", "Speaker"), ("lower", "Mr. President")):
        vote = VoteEvent(
            chamber=chamber,
            start_date="2026-03-30",
            result="pass",
            classification=[],
            motion_text="m",
            legislative_session="2026",
            bill="HB 1",
        )
        assert (
            add_voter(vote, "yes", title, chamber, "2026", "2026-03-30", stand_in)
            is None
        )
        assert get_pseudo_id(vote.votes[-1]["voter_id"]) == {"name": title}
