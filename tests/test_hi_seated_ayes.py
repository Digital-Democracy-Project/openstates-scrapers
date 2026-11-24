"""Tests for OPEN-709: Hawaii House floor tallies and the Senate resolution adoption print no aye
count, so their ayes are the members seated that day (people fork role dates) minus those the
text names. Nothing here touches the network: the people data is a saved copy of the people fork's
data/hi/legislature and data/hi/retired at 51ca6f83 (people #36, OPEN-716), and the status pages
are saved from data.capitol.hawaii.gov (read 2026-11-20).

The expected aye counts come from the House journal (data.capitol.hawaii.gov/sessions/journal/
House/2026/, "passed Third Reading by a vote of N ayes ..."), not from this code, and the Senate's
from its journal of 2026-04-28 (all 25 present; SR 20 adopted with DeCorte and Fevella voting no).
"""
import json
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi import members as hi_members  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open709")
PEOPLE = os.path.join(FIXTURES, "people")


@pytest.fixture(scope="module")
def members():
    os.environ[hi_members.PEOPLE_DIR_ENV] = PEOPLE
    try:
        return hi_members.load_members(None)
    finally:
        del os.environ[hi_members.PEOPLE_DIR_ENV]


def _votes(name, members):
    bill_id = name[:-5]
    chamber = "upper" if bill_id.startswith("S") else "lower"
    page = lxml.html.fromstring(open(os.path.join(FIXTURES, name), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = members
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber=chamber)
    out = []
    for v in scraper.parse_bill_actions_table(
        bill, table, bill_id, "2026 Regular Session", "https://example/" + name, chamber
    ):
        named = {}
        for x in v.votes:
            named.setdefault(x["option"], []).append(x["voter_name"])
        out.append(
            dict(
                date=v.start_date,
                chamber=json.loads(v.organization[1:])["classification"],
                motion=v.motion_text,
                classification=v.motion_classification,
                counts={c["option"]: c["value"] for c in v.counts},
                named=named,
            )
        )
    return out


def _floor(name, members, date, chamber="lower"):
    found = [
        v
        for v in _votes(name, members)
        if v["date"] == date
        and v["chamber"] == chamber
        and v["classification"] != ["committee-passage"]
    ]
    assert len(found) == 1, found
    return found[0]


def test_seated_house_follows_the_people_dates(members):
    names = lambda day: {p["name"] for p in members.seated("lower", day)}  # noqa: E731
    assert len(names("2026-02-13")) == 51 and "Daniel Holt" in names("2026-02-13")
    assert len(names("2026-02-14")) == 50 and "Daniel Holt" not in names("2026-02-14")
    assert len(names("2026-04-13")) == 50 and "Cov Ratcliffe" not in names("2026-04-13")
    assert len(names("2026-04-14")) == 51 and "Cov Ratcliffe" in names("2026-04-14")
    assert len(members.seated("upper", "2026-04-28")) == 25


def test_a_role_with_no_start_date_makes_the_day_unknown(members):
    # 2021: older people records carry end dates only, so nobody can say who sat
    assert members.seated("lower", "2021-03-09") is None


# (page, date, aye count in the House journal)
JOURNAL = [
    ("HB1768.html", "2026-03-10", 42),  # "42 ayes to 8 noes"
    (
        "SB2153.html",
        "2026-04-09",
        49,
    ),  # "49 ayes, with Representative Cochran being excused"
    ("SB2387.html", "2026-04-14", 44),  # "44 ayes to 7 noes" (Ratcliffe's first day)
    ("SB2135.html", "2026-04-14", 50),
    ("HB1642.html", "2026-05-06", 44),  # "44 ayes to 7 noes"
    ("HB1705.html", "2026-03-06", 47),  # 3 excused, inside the 50-seat window
    ("HB1705.html", "2026-04-23", 50),
]


@pytest.mark.parametrize("name,date,journal_ayes", JOURNAL)
def test_house_ayes_match_the_journal(members, name, date, journal_ayes):
    v = _floor(name, members, date)
    assert v["counts"]["yes"] == journal_ayes
    # names and counts add up, and nobody is listed twice
    for option, count in v["counts"].items():
        assert len(v["named"].get(option, [])) == count
    everyone = sum(v["named"].values(), [])
    assert len(everyone) == len(set(everyone))


def test_hb1768_named_voters(members):
    v = _floor("HB1768.html", members, "2026-03-10")
    assert v["named"]["no"] == [
        "Alcos",
        "Garcia",
        "Gedeon",
        "Kong",
        "Matsumoto",
        "Muraoka",
        "Pierick",
        "Shimizu",
    ]
    yes = v["named"]["yes"]
    assert "Kila" in yes  # aye with reservations, as the page names him
    assert "Darius Kila" not in yes  # ... and not counted again from the seats
    assert "Sam Kong" not in yes and "Diamond Garcia" not in yes
    assert "Daniel Holt" not in yes and "Cov Ratcliffe" not in yes  # the vacant seat
    assert "Nadine Nakamura" in yes


def test_ratcliffe_votes_from_his_first_day(members):
    assert (
        "Cov Ratcliffe" in _floor("SB2387.html", members, "2026-04-14")["named"]["yes"]
    )
    assert (
        "Cov Ratcliffe"
        not in _floor("SB2153.html", members, "2026-04-09")["named"]["yes"]
    )


def test_holt_listed_excused_on_his_last_days(members):
    v = _floor("HB1621.html", members, "2026-02-11")
    assert v["counts"] == {"yes": 49, "no": 1, "not voting": 1}
    assert v["named"]["not voting"] == ["Holt"]


def test_family_name_and_initial(members):
    # "Representative(s) Cochran, Lee, M., Poepoe excused (3)"
    v = _floor("HB1705.html", members, "2026-02-17")
    assert v["named"]["not voting"] == ["Cochran", "Lee, M", "Poepoe"]
    assert v["counts"]["yes"] == 47
    assert "Mike Lee" not in v["named"]["yes"]


def test_senate_resolution_adoption(members):
    v = _floor("SR20.html", members, "2026-04-28", chamber="upper")
    assert v["motion"] == "Report and Resolution Adopted as amended (SD 1)."
    assert v["classification"] == ["passage"]
    assert v["counts"] == {"yes": 23, "no": 2, "not voting": 0}
    assert v["named"]["no"] == ["DeCorte", "Fevella"]
    assert len(v["named"]["yes"]) == 23


def test_kept_roll_calls_are_unchanged_by_the_new_ones(members):
    # without people data the scraper yields exactly what it kept before (main); with it, those
    # same roll calls are unchanged; the House floor tally it adds after HB 1705's reconsideration
    # (04-22-26) carries the "Reconsider: " prefix (OPEN-856, test_hi_reconsider_prefix)
    for name in (
        "HB1705.html",
        "HB1768.html",
        "SB2387.html",
        "SR20.html",
        "HB1642.html",
        "HB1621.html",
    ):
        before = _votes(name, None)
        after = _votes(name, members)
        assert [v for v in after if v in before] == before
    assert [
        v["date"]
        for v in _votes("HB1705.html", members)
        if v["motion"].startswith("Reconsider: ")
    ] == ["2026-04-23"]


def test_no_people_data_keeps_no_derived_roll_call():
    votes = _votes("HB1768.html", None)
    assert not [
        v for v in votes if v["chamber"] == "lower" and "Reading" in v["motion"]
    ]


def test_a_name_that_is_not_one_seated_member_skips_the_tally(members):
    scraper = object.__new__(HIBillScraper)
    scraper.members = members
    v = {
        "yes_resv": "none",
        "no": "Representative(s) Nobody",
        "n_no": "1",
        "excused": "none",
        "n_excused": "0",
    }
    assert scraper.seated_ayes(v, "lower", "2026-03-10", "HB1") is None
    # Holt, after his seat ended
    v["no"] = "Representative(s) Holt"
    assert scraper.seated_ayes(v, "lower", "2026-03-10", "HB1") is None
    v["no"] = "Representative(s) Holt"
    assert len(scraper.seated_ayes(v, "lower", "2026-02-11", "HB1")) == 50


def test_a_list_that_does_not_match_its_count_skips_the_tally(members):
    scraper = object.__new__(HIBillScraper)
    scraper.members = members
    v = {
        "yes_resv": "none",
        "no": "Representative(s) Garcia, Pierick",
        "n_no": "3",
        "excused": "none",
        "n_excused": "0",
    }
    assert scraper.seated_ayes(v, "lower", "2026-03-10", "HB1") is None


class _Response:
    def __init__(self, text):
        self.text = text

    def json(self):
        return json.loads(self.text)


class _FakeGitHub:
    """Serves the people fork's two listings and raw files from the saved copy."""

    def __init__(self, fail=False):
        self.fail = fail
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if self.fail:
            raise ConnectionError("down")
        for folder in hi_members.FOLDERS:
            if url == hi_members.LIST_URL.format(folder=folder):
                files = sorted(os.listdir(os.path.join(PEOPLE, "hi", folder)))
                return _Response(
                    json.dumps(
                        [
                            {
                                "type": "file",
                                "name": f,
                                "download_url": f"raw/{folder}/{f}",
                            }
                            for f in files
                        ]
                    )
                )
        _, folder, f = url.split("/")
        return _Response(open(os.path.join(PEOPLE, "hi", folder, f)).read())


def test_fetch_reads_both_folders_from_the_fork(members):
    os.environ.pop(hi_members.PEOPLE_DIR_ENV, None)
    gh = _FakeGitHub()
    fetched = hi_members.load_members(gh)
    assert gh.urls[0] == (
        "https://api.github.com/repos/Digital-Democracy-Project/people/contents/"
        "data/hi/legislature?ref=main"
    )
    assert sum(u.startswith("https://api.github.com") for u in gh.urls) == 2
    assert len(fetched.roles) == len(members.roles)
    assert len(fetched.seated("lower", "2026-03-10")) == 50


def test_fetch_failure_means_no_roster():
    os.environ.pop(hi_members.PEOPLE_DIR_ENV, None)
    assert hi_members.load_members(_FakeGitHub(fail=True)) is None


def test_a_shared_family_name_needs_its_initial():
    def person(name, given, family):
        return {
            "id": "ocd-person/" + name,
            "name": name,
            "given_name": given,
            "family_name": family,
            "roles": [{"type": "lower", "start_date": "2025-01-01"}],
        }

    roster = hi_members.Members(
        [
            person("Bert Kobayashi", "Bert", "Kobayashi"),
            person("Dale Kobayashi", "Dale", "Kobayashi"),
        ]
    )
    seated = roster.seated("lower", "2026-03-10")
    assert roster.find(seated, "Kobayashi") is None  # two members: never pick one
    assert roster.find(seated, "Kobayashi, D")["name"] == "Dale Kobayashi"
    assert roster.find(seated, "Kobayashi, B.")["name"] == "Bert Kobayashi"


def test_a_derived_tally_takes_no_reconsider_prefix(members):
    # HB 1705: "Reconsideration of action taken on 04-16-26" sits between its Final Reading
    # and its Third Reading; the floor tallies keep their own motion text
    v = _floor("HB1705.html", members, "2026-03-06")
    assert (
        v["motion"]
        == "Passed Third Reading with Representative(s) Garcia voting aye with reservations; none voting no (0) and Representative(s) Perruso, Quinlan, Sayama excused (3)."
    )


def test_scrape_start_loads_the_members(monkeypatch):
    import hi.bills

    loaded = object()
    monkeypatch.setattr(hi.bills, "get_short_codes", lambda scraper: None)
    monkeypatch.setattr(hi.bills, "load_members", lambda scraper: loaded)
    scraper = object.__new__(HIBillScraper)
    scraper.jurisdiction = hi.Hawaii()  # OPEN-748: scrape() looks the session up
    monkeypatch.setattr(scraper, "scrape_type", lambda *a: iter(()), raising=False)
    list(scraper.scrape(chamber="lower", session="2026 Regular Session"))
    assert scraper.members is loaded


def test_the_same_member_listed_twice_skips_the_tally(members):
    scraper = object.__new__(HIBillScraper)
    scraper.members = members
    base = {"yes_resv": "none", "excused": "none", "n_excused": "0"}
    # twice in one list
    v = dict(base, no="Representative(s) Garcia, Garcia", n_no="2")
    assert scraper.seated_ayes(v, "lower", "2026-03-10", "HB1") is None
    # in two lists (aye with reservations and no)
    v = dict(
        base,
        yes_resv="Representative(s) Garcia",
        no="Representative(s) Garcia",
        n_no="1",
    )
    assert scraper.seated_ayes(v, "lower", "2026-03-10", "HB1") is None


def test_one_person_with_two_roles_that_day_makes_the_day_unknown():
    person = {
        "id": "ocd-person/1",
        "name": "Ann Two",
        "given_name": "Ann",
        "family_name": "Two",
        "roles": [
            {"type": "lower", "start_date": "2025-01-01", "district": "1"},
            {"type": "lower", "start_date": "2026-01-01", "district": "2"},
        ],
    }
    roster = hi_members.Members([person])
    assert roster.seated("lower", "2025-06-01") == [person]
    assert roster.seated("lower", "2026-03-10") is None
