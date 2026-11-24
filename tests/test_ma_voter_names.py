"""Tests for OPEN-474: Massachusetts roll-call voter names in a form the importer matches.

The fixtures are real 194th roll calls run through `pdftotext -layout`, as the scraper
does: House No. 25 of the 2025 RollCalls PDF (`ma_house_rollcall_194_jones_x.txt`,
"--Jones--", "Mr. Speaker" and "X Garcia" printed with one space), House No. 1
(`..._star.txt`, "Moran M." with no comma) and Senate Roll Call #31
(`ma_senate_rollcall_194_31.txt`, "Surname, Given names" and "Driscoll, Jr., William J.").

The NAYS and not-voting names below were read off the sheet by eye, not by the code
under test.

OPEN-810: "Mr. Speaker" is named only by the manifest's votes.house_speaker_by_session (read by
utils/presiding_officers.py). These tests point the manifest at a made-up Speaker, SPEAKER, a
name in no scraper code, fixture or people file, so a name that comes out can only have come
from the manifest.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma.bills import MABillScraper  # noqa: E402
from ma.voter_names import house_voter_name, senate_voter_name  # noqa: E402
from ma.votes import HouseVoteRecordParser  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SPEAKER = "Oswin Thackerberry"
MA = "ma:\n  votes:\n    house_speaker_by_session:\n      194th: {}\n".format(SPEAKER)


def _write_manifest(tmp_path, monkeypatch, text, name="jurisdictions.yaml"):
    # a new file each time: the reader caches a file by its modification time
    path = tmp_path / name
    path.write_text(text)
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(path))


@pytest.fixture(autouse=True)
def manifest(tmp_path, monkeypatch):
    _write_manifest(tmp_path, monkeypatch, MA)


NO_25_NAYS = {
    "Garry",
    "Robertson",
    "Jones",
    "Ferguson",
    "Frost",
    "Muradian",
    "Berthiaume",
    "Chaisson",
    "DeCoste",
    "Gaskey",
    "Howitt",
    "Kane",
    "Marsi",
    "McKenna",
    "Orrall",
    "Pease",
    "Smola",
    "Soter",
    "Sweezey",
    "Thurber",
    "Vaughn",
    "Wong",
    "Xiarhos",
}
NO_25_NOT_VOTING = {
    "Garcia",
    "Murphy",
    "Nguyen",
    "Kearney",
    "Vieira",
    "Boldyga",
    "Lombardo",
    "Sullivan-Almeida",
}


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class _FakeVote:
    legislative_session = "194th"

    def __init__(self):
        self.voters = []

    def yes(self, name):
        self.voters.append(("yes", name))

    def no(self, name):
        self.voters.append(("no", name))

    def vote(self, how, name):
        self.voters.append((how, name))

    def set_count(self, option, value):
        # OPEN-442: the House reader also sets the tally from the sheet's header
        pass


def _house_scraper(fixture, warnings):
    scraper = MABillScraper.__new__(MABillScraper)
    scraper.get_house_pdf = lambda vurl: _fixture(fixture)
    scraper.info = lambda *a, **kw: None
    scraper.warning = lambda msg, *a: warnings.append(msg % a)
    return scraper


def _house_vote(fixture, number, session="194th", warnings=None, scraper=None):
    if scraper is None:
        scraper = _house_scraper(fixture, [] if warnings is None else warnings)
    vote = _FakeVote()
    vote.legislative_session = session
    assert scraper.scrape_house_vote(vote, "http://example/RollCalls", number) is True
    return vote.voters


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("--Jones--", "Jones"),
        ("--Whipps--", "Whipps"),
        ("Tyler *", "Tyler"),
        ("Mr. Speaker", SPEAKER),
        ("Moran M.", "Moran, M."),
        ("Moran, M.", "Moran, M."),
        ("Ramos, A.", "Ramos, A."),
        ("Lipper-Garabedian", "Lipper-Garabedian"),
        ("Gómez", "Gómez"),
    ],
)
def test_house_names(printed, expected):
    assert house_voter_name(printed, "194th") == expected


def test_speaker_of_an_unlisted_session_is_left_as_printed():
    """Better unmatched than given to the wrong person."""
    assert house_voter_name("Mr. Speaker", "191st") == "Mr. Speaker"


@pytest.mark.parametrize(
    "text",
    [
        None,  # no manifest file
        "ma:\n  name: Massachusetts\n",  # no votes block
        "ma:\n  votes:\n    house_speaker_by_session: null\n",
        "zz:\n  votes:\n    house_speaker_by_session:\n      194th: Someone\n",
    ],
)
def test_without_a_manifest_name_the_title_stays_as_printed(
    tmp_path, monkeypatch, text
):
    """OPEN-810: there is no name in code to fall back on."""
    if text is None:
        monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(tmp_path / "absent.yaml"))
    else:
        _write_manifest(tmp_path, monkeypatch, text, "other.yaml")
    assert house_voter_name("Mr. Speaker", "194th") == "Mr. Speaker"


def test_the_speaker_is_whoever_the_manifest_names(tmp_path, monkeypatch):
    _write_manifest(
        tmp_path,
        monkeypatch,
        "ma:\n  votes:\n    house_speaker_by_session:\n      195th: Pell Verricombe\n",
        "next.yaml",
    )
    assert house_voter_name("Mr. Speaker", "195th") == "Pell Verricombe"
    assert house_voter_name("Mr. Speaker", "194th") == "Mr. Speaker"


def test_a_session_the_manifest_does_not_list_is_warned_once(tmp_path, monkeypatch):
    """The scrape says so (once a session) instead of guessing a name."""
    fixture, warnings = "ma_house_rollcall_194_jones_x.txt", []
    scraper = _house_scraper(fixture, warnings)
    voters = _house_vote(fixture, 25, session="195th", scraper=scraper)
    _house_vote(fixture, 25, session="195th", scraper=scraper)
    assert ("yes", "Mr. Speaker") in voters
    speaker_warnings = [w for w in warnings if "house_speaker_by_session" in w]
    assert len(speaker_warnings) == 1 and "195th" in speaker_warnings[0]

    warnings.clear()
    _house_vote(fixture, 25, scraper=scraper)  # 194th is listed
    assert not [w for w in warnings if "house_speaker_by_session" in w]


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Keenan, John F.", "John F. Keenan"),
        ("Creem, Cynthia Stone", "Cynthia Stone Creem"),
        ("Driscoll, Jr., William J.", "William J. Driscoll, Jr."),
        ("O'Connor, Patrick M.", "Patrick M. O'Connor"),
        ("Collins, Nick", "Nick Collins"),
        ("Smith", "Smith"),
    ],
)
def test_senate_names(printed, expected):
    assert senate_voter_name(printed) == expected


def test_house_reader_pairs_each_letter_with_its_own_name():
    """The old reader split rows on three spaces and zipped the letters with the
    names, so "X Garcia" (one space) became a name with no letter and every later
    voter took the next voter's letter."""
    voters = _house_vote("ma_house_rollcall_194_jones_x.txt", 25)
    assert len(voters) == 127 + 23 + 8
    assert {n for how, n in voters if how == "no"} == NO_25_NAYS
    assert {n for how, n in voters if how == "other"} == NO_25_NOT_VOTING
    assert sum(how == "yes" for how, _ in voters) == 127


def test_house_reader_writes_names_the_people_data_holds():
    names = {n for _, n in _house_vote("ma_house_rollcall_194_jones_x.txt", 25)}
    assert {SPEAKER, "Jones", "Whipps", "Garcia"} <= names
    assert not any(n.startswith(("X ", "Y ", "N ", "P ")) for n in names)
    assert not any("--" in n or "*" in n or n == "Mr. Speaker" for n in names)

    names = {n for _, n in _house_vote("ma_house_rollcall_194_star.txt", 1)}
    assert {"Moran, F.", "Moran, J.", "Moran, M.", "Tyler"} <= names


def test_votes_scraper_house_reader_uses_the_same_names():
    text = _fixture("ma_house_rollcall_194_jones_x.txt")
    parser = HouseVoteRecordParser(
        text.split("MASSACHUSETTS HOUSE OF REPRESENTATIVES", 1)[1], session="194th"
    )
    assert SPEAKER in parser.names and "Mr. Speaker" not in parser.names


def test_senate_reader_writes_given_names_first(monkeypatch):
    import ma.bills as ma_bills

    scraper = MABillScraper.__new__(MABillScraper)
    scraper.warning = scraper.info = lambda *a, **kw: None
    scraper.urlretrieve = lambda url: ("/dev/null", None)
    pdf = _fixture("ma_senate_rollcall_194_31.txt").encode("utf-8")
    monkeypatch.setattr(ma_bills, "convert_pdf", lambda path, fmt: pdf)
    monkeypatch.setattr(ma_bills.os, "remove", lambda path: None)

    vote = _FakeVote()
    assert scraper.scrape_senate_vote(vote, "http://example/SenateRollCall31.pdf")
    names = [n for how, n in vote.voters if how == "yes"]
    assert len(names) == 39
    assert {
        "John F. Keenan",
        "Cynthia Stone Creem",
        "William J. Driscoll, Jr.",
        "Adam Gómez",
        "John C. Velis",  # printed "Velis, John C. − 39.", the count removed
    } <= set(names)
    assert not any("," in n and not n.endswith(", Jr.") for n in names)
