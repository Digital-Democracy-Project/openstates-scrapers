"""Tests for OPEN-825: the Hawaii Senate prints its floor tally as an aye count with only the
exceptions named ("Ayes, 25; Aye(s) with reservations: none .  Noes, 0 (none). Excused, 0
(none)."), so its plain ayes are the senators seated that day (people fork role dates) minus
those the text names, kept only when they and the ayes with reservations come to the printed aye
count.

Nothing here touches the network. The people data is OPEN-709's saved copy of the people fork
(tests/fixtures/hi_open709/people). The status pages are saved from data.capitol.hawaii.gov
(session/measure_indiv.aspx, year=2026): OPEN-709's (read 2026-11-20) and hi_open825's (read
2026-11-23). The expected counts below are typed from each page's printed text, not produced by
this code.
"""
import json
import logging
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi import members as hi_members  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "fixtures")
PEOPLE = os.path.join(HERE, "hi_open709", "people")


@pytest.fixture(scope="module")
def members():
    os.environ[hi_members.PEOPLE_DIR_ENV] = PEOPLE
    try:
        return hi_members.load_members(None)
    finally:
        del os.environ[hi_members.PEOPLE_DIR_ENV]


def _votes(path, members):
    bill_id = os.path.basename(path).replace(".html", "").split("-")[0]
    chamber = "lower" if bill_id.startswith("HB") else "upper"
    page = lxml.html.fromstring(open(os.path.join(HERE, path), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = members
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber=chamber)
    out = []
    for v in scraper.parse_bill_actions_table(
        bill, table, bill_id, "2026 Regular Session", "https://example/" + path, chamber
    ):
        named = {}
        for x in v.votes:
            named.setdefault(x["option"], []).append(x["voter_name"])
        out.append(
            dict(
                date=v.start_date,
                chamber=json.loads(v.organization[1:])["classification"],
                motion=v.motion_text,
                result=v.result,
                classification=v.motion_classification,
                counts={c["option"]: c["value"] for c in v.counts},
                named=named,
                key=v.dedupe_key,
            )
        )
    return out


def _senate_floor(path, members, date):
    found = [
        v
        for v in _votes(path, members)
        if v["date"] == date
        and v["chamber"] == "upper"
        and "committee" not in v["motion"]
    ]
    assert len(found) == 1, found
    return found[0]


# (page, date, printed ayes, noes, excused)
PRINTED = [
    # unanimous Third Reading ("Ayes, 25; ... Noes, 0 (none). Excused, 0 (none).")
    ("hi_open709/SB2387.html", "2026-03-10", 25, 0, 0),
    ("hi_open709/HB1642.html", "2026-04-14", 25, 0, 0),
    # Final Reading after conference, both forms ("0 No(es): none." and "Noes, 0 (none).")
    ("hi_open709/HB1642.html", "2026-05-06", 25, 0, 0),
    ("hi_open709/SB2135.html", "2026-04-30", 25, 0, 0),
    # ... with one excused (Fukunaga)
    ("hi_open709/SB2153.html", "2026-05-01", 24, 0, 1),
    # noes
    ("hi_open709/HB1768.html", "2026-04-14", 22, 3, 0),
    # noes and an excused "Lee, C."
    ("hi_open825/SB2418.html", "2026-03-10", 21, 3, 1),
    # reservations, noes and excused, in 2025 (before the seat change of 2025-11-30/12-03)
    ("hi_open825/SB1588.html", "2025-02-19", 20, 2, 3),
    # four with reservations among 25 ayes
    ("hi_open825/SB283.html", "2025-02-27", 25, 0, 0),
    # a failed Final Reading
    ("hi_open825/HB1550.html", "2026-05-06", 9, 16, 0),
    # nominations: "Ayes, 18." with seven excused; reservations with "Lee, C." and noes; failed
    ("hi_open825/GM624.html", "2026-04-20", 18, 0, 7),
    ("hi_open825/GM801.html", "2026-04-30", 20, 5, 0),
    ("hi_open825/GM657.html", "2026-04-14", 2, 23, 0),
]


@pytest.mark.parametrize("path,date,ayes,noes,excused", PRINTED)
def test_person_votes_match_the_printed_counts(
    members, path, date, ayes, noes, excused
):
    v = _senate_floor(path, members, date)
    assert v["counts"] == {"yes": ayes, "no": noes, "not voting": excused}
    assert {o: len(n) for o, n in v["named"].items() if n} == {
        o: n for o, n in v["counts"].items() if n
    }
    everyone = sum(v["named"].values(), [])
    assert len(everyone) == len(set(everyone)) == 25


def test_sb283_reservations_are_named_once(members):
    # "Ayes, 25; Aye(s) with reservations: Senator(s) Fukunaga, Inouye, Kidani, San Buenaventura ."
    yes = _senate_floor("hi_open825/SB283.html", members, "2025-02-27")["named"]["yes"]
    for name in ("Fukunaga", "Inouye", "Kidani", "San Buenaventura"):
        assert name in yes
    assert "Michelle Kidani" not in yes and "Brenton Awa" in yes


def test_the_seat_change_follows_the_people_dates(members):
    # Aquino's seat ended 2025-11-30, Lamosao's began 2025-12-03
    v2025 = _senate_floor("hi_open825/SB1588.html", members, "2025-02-19")
    v2026 = _senate_floor("hi_open825/SB2418.html", members, "2026-03-10")
    assert "Henry Aquino" in v2025["named"]["yes"]
    assert "Rachele Lamosao" not in sum(v2025["named"].values(), [])
    assert "Rachele Lamosao" in v2026["named"]["yes"]
    assert "Henry Aquino" not in sum(v2026["named"].values(), [])


def test_whole_lists_are_kept(members):
    # the second pattern used to cut "(Senator(s) Chang, ...)" at "(s)", the fourth kept no noes
    v = _senate_floor("hi_open825/GM624.html", members, "2026-04-20")
    assert v["named"]["not voting"] == [
        "Chang",
        "DeCoite",
        "Inouye",
        "Keohokalole",
        "Kidani",
        "Lee, C",
        "McKelvey",
    ]
    assert "Chris Lee" not in v["named"]["yes"]
    v = _senate_floor("hi_open825/SB1588.html", members, "2025-02-19")
    assert v["named"]["no"] == ["Awa", "Inouye"]
    assert v["named"]["not voting"] == ["Gabbard", "Kouchi", "Richards"]


def test_motion_result_and_classification(members):
    v = _senate_floor("hi_open825/GM801.html", members, "2026-04-30")
    assert v["motion"] == "Confirmed." and v["result"] == "pass"
    v = _senate_floor("hi_open825/HB1550.html", members, "2026-05-06")
    assert v["motion"] == "Failed to pass Final Reading." and v["result"] == "fail"


def test_no_people_data_keeps_the_counts_and_printed_names():
    # unlike OPEN-709's forms (no count printed), the roll call stays, as it did before
    v = _senate_floor("hi_open825/SB1588.html", None, "2025-02-19")
    assert v["counts"] == {"yes": 20, "no": 2, "not voting": 3}
    assert len(v["named"]["yes"]) == 5  # the five with reservations
    assert len(v["named"]["no"]) == 2


def test_no_clear_roster_keeps_the_counts(members):
    # 2021: the older people records carry no start dates, so nobody can say who sat
    v = _senate_floor("hi_open709/HB862-2021.html", members, "2021-04-13")
    assert v["counts"] == {"yes": 24, "no": 1, "not voting": 0}
    assert v["named"] == {"yes": ["Acasio", "Ihara"], "no": ["Fevella"]}


class _ShortRoster:
    """The real roster minus one senator: seated and not named then misses the printed count."""

    def __init__(self, members, drop):
        self.members, self.drop = members, drop

    def seated(self, chamber, day):
        return [p for p in self.members.seated(chamber, day) if p["name"] != self.drop]

    def find(self, seated, name):
        return self.members.find(seated, name)


def test_a_count_that_does_not_add_up_keeps_only_the_printed_names(members, caplog):
    short = _ShortRoster(members, "Brenton Awa")
    with caplog.at_level(logging.WARNING):
        v = _senate_floor("hi_open709/SB2387.html", short, "2026-03-10")
    assert v["counts"] == {"yes": 25, "no": 0, "not voting": 0}
    assert v["named"] == {}
    assert "is not the printed 25 ayes" in caplog.text


def test_a_name_that_is_not_one_seated_member_keeps_only_the_printed_names(members):
    # Awa is printed as a no; without him on the roster the name cannot be placed
    short = _ShortRoster(members, "Brenton Awa")
    v = _senate_floor("hi_open709/HB1768.html", short, "2026-04-14")
    assert v["counts"] == {"yes": 22, "no": 3, "not voting": 0}
    assert v["named"] == {"no": ["Awa", "DeCorte", "Fevella"]}


def test_senate_roll_calls_keep_key_motion_result_and_counts(members):
    # with or without the roster, each Senate roll call keeps its dedupe_key, motion, result,
    # classification and counts: only its names change
    for path in ("hi_open709/HB1768.html", "hi_open709/HB1642.html"):
        with_roster = _votes(path, members)
        without = _votes(path, None)
        for a in with_roster:
            if a["chamber"] == "upper":
                b = [x for x in without if x["key"] == a["key"]]
                assert len(b) == 1
                assert {k: x for k, x in a.items() if k != "named"} == {
                    k: x for k, x in b[0].items() if k != "named"
                }


def test_a_house_tally_with_a_count_gets_no_worked_out_ayes(members):
    # the rule is the Senate's: a House text with an aye count and no aye names (the veto
    # override form) keeps only what it prints, even when the roster would add up
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = members
    table = lxml.html.fromstring(
        "<table><tr><th>Date</th></tr><tr><td>03/10/2026</td><td>H</td><td>Veto overridden "
        "by 2/3's vote with 49 Ayes; 1 Noes Representative(s) Garcia; and 0 Excused .</td>"
        "</tr></table>"
    )
    bill = Bill("HB1", "2026 Regular Session", "title", chamber="lower")
    (v,) = scraper.parse_bill_actions_table(
        bill, table, "HB1", "2026 Regular Session", "https://example/", "lower"
    )
    assert {c["option"]: c["value"] for c in v.counts}["yes"] == 49
    assert [x["voter_name"] for x in v.votes] == ["Garcia"]
