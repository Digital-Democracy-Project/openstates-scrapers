"""Tests for OPEN-710: a Hawaii roll call's result is the outcome its text states (passed, adopted,
overridden; failed, sustained), else two-thirds of the members to which the house is entitled for a
veto override (House 51 -> 34, Senate 25 -> 17), else more yeas than nays.

Real texts are from the status pages on data.capitol.hawaii.gov (session/measure_indiv.aspx, read
2026-11-20): HB 862 of 2021 (both veto overrides), HR 50 of 2026 (a House "Report adopted;
referred to ..." and a resolution "Adopted ..."), and SR 20 of 2026 (the Senate resolution
adoption). Before this rule all but the overrides were stored as "fail" (the overrides were not
read at all); the outcomes are the chambers' own (the override notices on HB 862 say each house
"approved and carried" the motion "by a 2/3 vote").
"""
import json
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi import members as hi_members  # noqa: E402
from hi.bills import HIBillScraper, vote_result  # noqa: E402

TESTS = os.path.dirname(__file__)
FIX709 = os.path.join(TESTS, "fixtures", "hi_open709")
FIX710 = os.path.join(TESTS, "fixtures", "hi_open710")

HOUSE_OVERRIDE = (
    "Veto overridden by 2/3's vote with 38 Ayes; 8 Noes Representative(s) Har, Kong, McDermott, "
    "Okimoto, Takumi, Tokioka, Ward, Wildberger; and 4 Excused Representative(s) Ilagan, McKelvey, "
    "Nishimoto, Ohno."
)
SENATE_OVERRIDE = (
    "Veto overridden - 2/3's vote: Ayes, 17; Aye(s) with reservations: Senator(s) Moriwaki . "
    "Noes, 8 (Senator(s) Acasio, Baker, Chang, L. DeCoite, Fevella, Ihara, Inouye, Taniguchi). "
    "Excused, 0 (none). "
)


@pytest.fixture(scope="module")
def members():
    os.environ[hi_members.PEOPLE_DIR_ENV] = os.path.join(FIX709, "people")
    try:
        return hi_members.load_members(None)
    finally:
        del os.environ[hi_members.PEOPLE_DIR_ENV]


def _votes(path, members, session="2026 Regular Session"):
    bill_id = os.path.basename(path)[:-5].split("-")[0]
    chamber = "upper" if bill_id.startswith("S") else "lower"
    page = lxml.html.fromstring(open(path, "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    scraper.members = members
    bill = Bill(bill_id, session, "title", chamber=chamber)
    out = []
    for v in scraper.parse_bill_actions_table(
        bill, table, bill_id, session, "https://example/", chamber
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
                counts={c["option"]: c["value"] for c in v.counts},
                named=named,
            )
        )
    return out


# (chamber, text as on the page, yeas, nays, result): real 2026 / 2021 roll calls (the WAM
# committee text is cut after its outcome)
REAL_RESULTS = [
    ("lower", HOUSE_OVERRIDE, 38, 8, "pass"),
    ("upper", SENATE_OVERRIDE, 17, 8, "pass"),
    (
        "lower",
        "Report adopted; referred to the committee(s) on JHA with none voting aye with "
        "reservations; none voting no (0) and Representative(s) Nakamura, Perruso excused (2).",
        48,
        0,
        "pass",
    ),
    (
        "lower",
        "Adopted as amended in HD 1 with Representative(s) Garcia, Gedeon, Shimizu voting aye with "
        "reservations; Representative(s) Pierick voting no (1) and  Representative(s) Cochran "
        "excused (1).",
        48,
        1,
        "pass",
    ),
    (
        "upper",
        "Report and Resolution Adopted as amended (SD 1).  Aye(s) with reservations: none. Noes, 2 "
        "(Senator(s) DeCorte, Fevella).",
        23,
        2,
        "pass",
    ),
    # kept results: "passed" in the text was "pass" before and still is
    (
        "upper",
        "Passed Final Reading, as amended (CD 1). Ayes, 23; Aye(s) with reservations: Senator(s) "
        "Chang, Ihara, Taniguchi . 2 No(es): Senator(s) Acasio, Fevella.  0 Excused: none.",
        23,
        2,
        "pass",
    ),
    (
        "upper",
        "The committee(s) on  WAM recommend(s) that the measure be PASSED, WITH AMENDMENTS.",
        7,
        1,
        "pass",
    ),
]


@pytest.mark.parametrize("chamber,text,yes,no,expected", REAL_RESULTS)
def test_vote_result_on_real_texts(chamber, text, yes, no, expected):
    assert vote_result(chamber, text, yes, no) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Veto sustained with 30 Ayes; 20 Noes ...",
        "Failed to pass Third Reading. Ayes, 13; Noes, 12.",
        "Motion to override veto failed. Ayes, 16; Noes, 9.",
    ],
)
def test_a_stated_failure_is_fail_even_with_more_yeas(text):
    # constructed texts (no failed floor vote is in the saved sample)
    assert vote_result("upper", text, 16, 9) == "fail"
    assert vote_result("lower", text, 40, 10) == "fail"


@pytest.mark.parametrize(
    "text",
    [
        "Adopted with none voting aye with reservations ...",
        "Report adopted; referred to the committee(s) on FIN ...",
        "Veto overridden ...",
        "Passed Third Reading ...",
    ],
)
def test_a_stated_outcome_wins_over_the_counts(text):
    # constructed counts: the stated outcome is taken as written, whatever the tally says
    assert vote_result("lower", text, 0, 0) == "pass"
    assert vote_result("upper", text, 10, 15) == "pass"


def test_a_stated_failure_wins_over_a_stated_pass():
    # constructed: as in Wyoming's vote_result(), a failure named anywhere in the text is "fail"
    assert (
        vote_result("lower", "Amendment failed; Passed Third Reading.", 40, 10)
        == "fail"
    )


# Constructed counts on an override text that states no outcome, to pin the threshold: two-thirds
# of the members to which each house is entitled, not of those voting.
@pytest.mark.parametrize(
    "chamber,yes,no,expected",
    [
        ("lower", 34, 17, "pass"),
        ("lower", 33, 5, "fail"),  # yeas beat nays, but 33 < 34
        ("upper", 17, 8, "pass"),
        ("upper", 16, 2, "fail"),  # 16 < 17
    ],
)
def test_override_threshold_is_two_thirds_of_the_house(chamber, yes, no, expected):
    assert (
        vote_result(chamber, "Motion to override veto. Ayes ...", yes, no) == expected
    )


@pytest.mark.parametrize(
    "yes,no,expected", [(3, 2, "pass"), (2, 2, "fail"), (1, 2, "fail")]
)
def test_no_stated_outcome_is_more_yeas_than_nays(yes, no, expected):
    assert vote_result("lower", "Some roll call text.", yes, no) == expected


def test_hb862_2021_veto_overrides_become_passing_roll_calls(members):
    votes = _votes(os.path.join(FIX709, "HB862-2021.html"), members, "2021")
    overrides = [v for v in votes if v["motion"].startswith("Veto overridden")]
    assert [(v["date"], v["chamber"], v["result"], v["counts"]) for v in overrides] == [
        ("2021-07-06", "lower", "pass", {"yes": 38, "no": 8, "not voting": 4}),
        ("2021-07-06", "upper", "pass", {"yes": 17, "no": 8, "not voting": 0}),
    ]
    house, senate = overrides
    assert house["named"] == {
        "no": [
            "Har",
            "Kong",
            "McDermott",
            "Okimoto",
            "Takumi",
            "Tokioka",
            "Ward",
            "Wildberger",
        ],
        "not voting": ["Ilagan", "McKelvey", "Nishimoto", "Ohno"],
    }
    assert senate["named"] == {
        "yes": ["Moriwaki"],
        "no": [
            "Acasio",
            "Baker",
            "Chang",
            "L. DeCoite",
            "Fevella",
            "Ihara",
            "Inouye",
            "Taniguchi",
        ],
    }


def test_hr50_report_adopted_and_adopted_are_pass(members):
    votes = _votes(os.path.join(FIX710, "HR50.html"), members)
    floor = [v for v in votes if v["chamber"] == "lower" and v["counts"]["yes"] > 40]
    assert sorted((v["date"], v["motion"][:14], v["result"]) for v in floor) == [
        ("2026-03-31", "Report adopted", "pass"),
        ("2026-04-09", "Adopted as ame", "pass"),
    ]


def test_sr20_senate_resolution_adoption_is_pass(members):
    votes = _votes(os.path.join(FIX709, "SR20.html"), members)
    adoption = [v for v in votes if "Resolution Adopted" in v["motion"]]
    assert [(v["result"], v["counts"]) for v in adoption] == [
        ("pass", {"yes": 23, "no": 2, "not voting": 0})
    ]
