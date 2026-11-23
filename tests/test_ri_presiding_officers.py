"""OPEN-785: "Mr. Speaker" and "Madam President" on a Rhode Island roll call are the officers in
office on the roll call's day, read from the manifest (utils/presiding_officers.py, shared with
Louisiana's OPEN-764).

The fixtures (ri_open785/) are real 2026 vote reports as webserver.rilegislature.gov serves them
(SVotes|HVotes/votereport.asp?id=<n>, read 2026-11-23), unchanged:
- H_22540: House, 2026-H 7865 passage, 5/5/2026 (YEAS 62, NAYS 11, NOT VOTING 2), "Mr. Speaker"
  voting yes and Rep. Blazejewski voting by name: Speaker Shekarchi presided.
- H_22554: House, 2026-H 7608 passage, 5/12/2026 (YEAS 72, NAYS 0, NOT VOTING 3), "Mr. Speaker"
  voting yes and Rep. Shekarchi by name: the House elected Blazejewski Speaker on 5/7/2026.
- S_17352: Senate consent calendar, 3/3/2026 (YEAS 37, NAYS 0, NOT VOTING 1), "Madam President"
  (Senate President Val Lawson) and "Appollonio, Jr." voting yes.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils import get_pseudo_id  # noqa: E402
from ri.bills import RIBillScraper  # noqa: E402
from utils import presiding_officers  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ri_open785")
HOUSE_BEFORE, HOUSE_AFTER, SENATE = "H_22540.html", "H_22554.html", "S_17352.html"
CHAMBER = {HOUSE_BEFORE: "lower", HOUSE_AFTER: "lower", SENATE: "upper"}
TITLE = {
    HOUSE_BEFORE: "Mr. Speaker",
    HOUSE_AFTER: "Mr. Speaker",
    SENATE: "Madam President",
}
# each report's own totals: YEAS, NAYS, NOT VOTING
TOTALS = {HOUSE_BEFORE: (62, 11, 2), HOUSE_AFTER: (72, 0, 3), SENATE: (37, 0, 1)}
RI = (
    "ri:\n  votes:\n"
    "    house_speaker_by_session:\n      '2026':\n"
    "        '2026-01-06': Joe Shekarchi\n        '2026-05-07': Chris Blazejewski\n"
    "    senate_president_by_session:\n      '2026': Val Lawson\n"
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


def _scraper():
    scraper = object.__new__(RIBillScraper)
    scraper.warning = mock.Mock()
    scraper._tz = mock.Mock(localize=lambda d: d)
    return scraper


def roll_call(page, chamber=None, session="2026", scraper=None):
    """{printed name: (option, voter id spec)} for one real report, through the scraper's own
    get_votes and vote_event (every RI vote event, consent calendars included, is made there)."""
    scraper = scraper or _scraper()
    html = open(os.path.join(FIXTURES, page), encoding="utf-8").read()
    scraper.get = lambda url: mock.Mock(text=html)
    (vote,) = scraper.get_votes(
        "https://webserver.rilegislature.gov/x", session
    ).values()
    v = scraper.vote_event(
        chamber or CHAMBER[page], session, vote, "PASSAGE", "HB 1", "lower", "k"
    )
    return {
        x["voter_name"]: (x["option"], get_pseudo_id(x["voter_id"])) for x in v.votes
    }


@pytest.mark.parametrize(
    "page,officer",
    [
        (HOUSE_BEFORE, "Joe Shekarchi"),
        (HOUSE_AFTER, "Chris Blazejewski"),
        (SENATE, "Val Lawson"),
    ],
)
def test_title_is_the_officer_in_office_on_the_roll_calls_day(manifest, page, officer):
    manifest(RI)
    assert roll_call(page)[TITLE[page]] == ("yes", {"name": officer})


@pytest.mark.parametrize("page", sorted(TOTALS))
def test_votes_counts_and_every_other_name_are_unchanged(manifest, page):
    manifest(RI)
    voters = roll_call(page)
    options = [option for option, _ in voters.values()]
    assert (
        options.count("yes"),
        options.count("no"),
        options.count("other"),
    ) == TOTALS[page]
    assert len(voters) == sum(TOTALS[page])
    for name, (_, spec) in voters.items():
        if name != TITLE[page]:
            assert spec == {"name": name}
    if page == SENATE:  # OPEN-786 is a people-data alias, not a scraper rename
        assert voters["Appollonio, Jr."] == ("yes", {"name": "Appollonio, Jr."})


@pytest.mark.parametrize(
    "text",
    [
        "ri:\n  votes:\n    house_speaker_by_session:\n      '2025': Joe Shekarchi\n"
        "    senate_president_by_session:\n      '2025': Val Lawson\n",
        "ri:\n  votes:\n    house_speaker_by_session: null\n    senate_president_by_session: null\n",
        "ri:\n  name: Rhode Island\n",
        "la:\n  votes:\n    house_speaker_by_session:\n      '2026': Phillip DeVillier\n"
        "    senate_president_by_session:\n      '2026': Cameron Henry\n",
        # dated, but the first day listed is after these roll calls
        "ri:\n  votes:\n    house_speaker_by_session:\n      '2026':\n        '2026-06-01': Someone\n"
        "    senate_president_by_session:\n      '2026':\n        '2026-06-01': Someone\n",
    ],
    ids=[
        "session-not-listed",
        "null",
        "no-votes-block",
        "another-state",
        "before-first-day",
    ],
)
def test_title_kept_with_one_warning_when_the_manifest_has_no_name(manifest, text):
    manifest(text)
    scraper = _scraper()
    for page in (HOUSE_BEFORE, HOUSE_AFTER, SENATE):
        assert roll_call(page, scraper=scraper)[TITLE[page]] == (
            "yes",
            {"name": TITLE[page]},
        )
    warned = [c.args for c in scraper.warning.call_args_list if "OPEN-785" in c.args[0]]
    # one warning per field and session, though two House roll calls left the title
    assert [a[1:3] for a in warned] == [
        ("house_speaker_by_session", "2026"),
        ("senate_president_by_session", "2026"),
    ]


def test_no_warning_when_the_manifest_names_the_officer(manifest):
    manifest(RI)
    scraper = _scraper()
    for page in (HOUSE_BEFORE, HOUSE_AFTER, SENATE):
        roll_call(page, scraper=scraper)
    assert not [c for c in scraper.warning.call_args_list if "OPEN-785" in c.args[0]]


def test_a_title_is_only_its_own_chambers_officer(manifest):
    """A Senate report's "Madam President" is never read as a House title, and the other way."""
    manifest(RI)
    assert roll_call(SENATE, chamber="lower")["Madam President"][1] == {
        "name": "Madam President"
    }
    assert roll_call(HOUSE_AFTER, chamber="upper")["Mr. Speaker"][1] == {
        "name": "Mr. Speaker"
    }


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2026-01-05", None),
        ("2026-01-06", "Joe Shekarchi"),
        ("2026-05-06", "Joe Shekarchi"),
        ("2026-05-07", "Chris Blazejewski"),
        ("2026-06-11", "Chris Blazejewski"),
        (None, None),
    ],
)
def test_a_dated_session_gives_the_officer_from_their_first_day(
    manifest, day, expected
):
    manifest(RI)
    assert (
        presiding_officers.officer("ri", "house_speaker_by_session", "2026", day)
        == expected
    )


def test_an_undated_session_ignores_the_day_and_an_unquoted_session_still_matches(
    manifest,
):
    manifest(
        "ri:\n  votes:\n    senate_president_by_session:\n      2026: Val Lawson\n"
    )
    for day in (None, "2026-01-01", "2026-12-31"):
        assert (
            presiding_officers.officer("ri", "senate_president_by_session", "2026", day)
            == "Val Lawson"
        )
