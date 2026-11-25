"""Tests for OPEN-873: Rhode Island roll calls whose bill number is printed in an unusual form,
and calendar items read and passed with no motion line.

Every fixture in tests/fixtures/ri_open873/ is a real vote report
(webserver.rilegislature.gov/SVotes|HVotes/votereport.asp?id=..., read 2026-11-24).

* The Senate's budget roll calls print "House Bill No. 7127  SUB A aa" and "BUDGET H-7127 SUB A AA";
  others print "REP NAME      H 7165", "SENATE BILL - S 2045 sub a", "HOUSE BILL 2026 H-8611",
  "SEN NAME    No. 2067", "REP NAME   HOUSE No. 5146" or "2025   H-5477". None matched, so those
  roll calls were dropped.
* A calendar item read and passed ("CALENDAR" or "IMMEDIATE CONSIDERATION", then "ITEM n  bill",
  then the title) has no motion line, so its motion was a fragment of the title and it was not
  labelled passage.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ri.bills import (  # noqa: E402
    RIBillScraper,
    passed_actions,
    printed_bill,
    title_only_header,
    vote_motion,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ri_open873")

# bills a real scrape would have found
BILLS = {
    ("lower", "7127"): "H 7127",
    ("lower", "7165"): "H 7165",
    ("lower", "8611"): "H 8611",
    ("lower", "5146"): "H 5146",
    ("lower", "6137"): "H 6137",
    ("lower", "5477"): "H 5477",
    ("upper", "2045"): "S 2045",
    ("upper", "2067"): "S 2067",
    ("upper", "8"): "S 8",
    ("upper", "2018"): "S 2018",
    ("upper", "2340"): "S 2340",
    ("lower", "7408"): "H 7408",
    ("upper", "3315"): "S 3315",
    ("upper", "3326"): "S 3326",
    ("lower", "8627"): "H 8627",
}


def _page(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


def _scrape_votes(name, chamber, session, history=None):
    """scrape_chamber_votes over a date list naming this one real report. `history` is
    {(bill chamber, number): [action lines]} the bill scrape would have read."""
    scraper = object.__new__(RIBillScraper)
    scraper._chamber_passed = {k: passed_actions(v) for k, v in (history or {}).items()}
    # the OPEN-785 presiding-officer warning (no manifest here) is tested in test_ri_presiding_officers.py
    scraper.warning = lambda *a, **k: None
    scraper._bill_id_by_type = dict(BILLS)
    scraper._tz = types.SimpleNamespace(localize=lambda d: d)
    listing = (
        '<html><body><center><div class="vote"><a href="votereport.asp?id=%s">'
        "Details</a></div></center></body></html>" % name.split("_")[1].split(".")[0]
    )
    scraper.get_vote_dates = lambda url, session: ["6/20/%s" % session]
    scraper.post_to = lambda url, date: listing
    scraper.get = lambda url: types.SimpleNamespace(text=_page(name))
    return list(scraper.scrape_chamber_votes(chamber, session))


@pytest.mark.parametrize(
    "name,session,chamber,bill,motion,classification",
    [
        # Senate 6/9/2026, the budget: "BUDGET H-7127 SUB A AA" (the vote to consider it)
        ("S_17769.html", "2026", "upper", "H 7127", "BUDGET H-7127 SUB A AA", []),
        # "House Bill No. 7127  SUB A aa", an amendment, then passage
        ("S_17782.html", "2026", "upper", "H 7127", "Passage", ["passage"]),
        # Senate 6/11/2026: "SENATE BILL - S 2045 sub a ... Reconsider": the amendment vote redone, then passage (OPEN-883)
        (
            "S_18010.html",
            "2026",
            "upper",
            "S 2045",
            "Reconsider / Approval of Amendment",
            ["amendment"],
        ),
        (
            "S_18011.html",
            "2026",
            "upper",
            "S 2045",
            "Reconsider / Passage as Amended",
            ["passage"],  # OPEN-883: the re-vote after reconsidering (31-6) replaces the 32-6
        ),
        # "HOUSE BILL 2026 H-8611" (the year and the chamber letter)
        ("S_18037.html", "2026", "upper", "H 8611", "In Concurrence", ["passage"]),
        # "SEN ACOSTA   No. 2067": a Senate resolution, no motion line and no calendar marker
        ("S_17324.html", "2026", "upper", "S 2067", "FAILURES IN LATIN AMERICA", []),
        # "REP CHIPPENDALE   H 7165" voted in the Senate
        (
            "S_17332.html",
            "2026",
            "upper",
            "H 7165",
            "Cameron David Charon in Marriage",
            [],
        ),
        # 2025: "REP SLATER   HOUSE No. 5146", "SEN MCKENNEY   No. 8", "H 6137", "2025   H-5477"
        (
            "S_16595.html",
            "2025",
            "upper",
            "H 5146",
            "within the City of Providence RI",
            [],
        ),
        ("S_16588.html", "2025", "upper", "S 8", "committee on A.I/Emerging Tech.", []),
        ("S_17303.html", "2025", "upper", "H 6137", "Passage", ["passage"]),
        (
            "S_17304.html",
            "2025",
            "upper",
            "H 5477",
            "In Concurrence / Passage",
            ["passage"],
        ),
        # a calendar item read and passed has no motion line: its motion is the marker
        ("S_17356.html", "2026", "upper", "S 2018", "CALENDAR", ["passage"]),
        ("S_17747.html", "2026", "upper", "S 3315", "CALENDAR", ["passage"]),
        (
            "S_17344.html",
            "2026",
            "upper",
            "S 2340",
            "IMMEDIATE CONSIDERATION",
            ["passage"],
        ),
        (
            "H_22382.html",
            "2026",
            "lower",
            "H 7165",
            "IMMEDIATE CONSIDERATION",
            ["passage"],
        ),
        (
            "H_22944.html",
            "2026",
            "lower",
            "H 8627",
            "IMMEDIATE CONSIDERATION",
            ["passage"],
        ),
    ],
)
def test_roll_call_is_tied_to_its_bill_and_labelled(
    name, session, chamber, bill, motion, classification
):
    (vote,) = _scrape_votes(name, chamber, session)
    assert vote.bill_identifier == bill
    assert vote.organization == '~{"classification": "%s"}' % chamber
    assert vote.motion_text == motion
    assert vote.motion_classification == classification
    # the report's counts and its names are kept as printed
    assert len(vote.votes) > 30
    assert sum(c["value"] for c in vote.counts) == len(vote.votes)


@pytest.mark.parametrize(
    "lines,expected",
    [
        (["House Bill No. 7127  SUB A aa", "REP ABNEY", "Passage"], ("H", "7127")),
        (["HOUSE BILL CONSIDERATION", "BUDGET H-7127 SUB A AA"], ("H", "7127")),
        (["SENATE BILL - S 2045 sub a", "SENATOR KALLMAN"], ("S", "2045")),
        (["HOUSE BILL 2026 H-8611", "RELATING TO TAXATION"], ("H", "8611")),
        (["SEN ACOSTA              No. 2067", "SENATE RESOLUTION"], ("S", "2067")),
        (["REP SLATER        HOUSE No. 5146", "AN ACT"], ("H", "5146")),
        # two different bills printed by the same form: never a guess
        (["SENATE BILL - S 2045 sub a", "RELATING TO S 3315"], None),
        # a chamber word and a number with neither "Bill" nor "No." is title text, not a bill
        (["ACT RELATING TO THE STATE HOUSE 2026 ROOF"], None),
        # no bill number at all: a bare roll call, a nomination, an election
        (["ROLL CALL"], None),
        (
            ["CALENDAR", "ITEM 3          0", "Appointment of a Member to the Board"],
            None,
        ),
        (["Election of the", "Senate Reading Clerk"], None),
    ],
)
def test_printed_bill(lines, expected):
    found = printed_bill(lines)
    assert (found and (found["chamber"], found["bill"])) == (expected or None)


def test_a_printed_year_of_another_session_is_skipped():
    # the report is 2025's ("2025   H-5477"), scraped as session 2026
    assert _scrape_votes("S_17304.html", "upper", "2026") == []


def test_calendar_item_with_a_motion_line_keeps_it_and_a_point_of_order_stays_unlabelled():
    assert (
        vote_motion(
            [
                "CALENDAR",
                "ITEM 6  2026-H 7551",
                "TITLE",
                "PASSAGE",
                "RULING OF THE CHAIR",
            ]
        )
        == "PASSAGE / RULING OF THE CHAIR"
    )
    # not a calendar item: a point of order's header ends in the title, as before
    assert (
        vote_motion(["POINT of ORDER", "ITEM 1  2025-S 359 SUB A", "CRIMINAL OFFENSES"])
        == "CRIMINAL OFFENSES"
    )


# OPEN-873 follow-up: a roll call whose header is a member line and a title, with no marker
# and no motion, is the chamber's passage vote when the bill's own history says that chamber
# passed it that day (Ramon, 2026-11-24).
SENATE_2067 = {("upper", "2067"): ["01/13/2026 Senate read and passed"]}
SENATE_7165 = {("lower", "7165"): ["01/22/2026 Senate passed in concurrence"]}


@pytest.mark.parametrize(
    "name,history,bill,motion",
    [
        # both roll calls on the Senate resolution, same day as "Senate read and passed"
        ("S_17324.html", SENATE_2067, "S 2067", "Passage"),
        ("S_17325.html", SENATE_2067, "S 2067", "Passage"),
        ("S_17332.html", SENATE_7165, "H 7165", "In Concurrence"),
    ],
)
def test_title_only_roll_call_is_passage_when_the_bill_history_says_it_passed(
    name, history, bill, motion
):
    (vote,) = _scrape_votes(name, "upper", "2026", history)
    assert vote.bill_identifier == bill
    assert vote.motion_text == motion
    assert vote.motion_classification == ["passage"]
    # the report's counts and names are kept as printed
    assert len(vote.votes) > 30
    assert sum(c["value"] for c in vote.counts) == len(vote.votes)


@pytest.mark.parametrize(
    "history",
    [
        # no history read for the bill
        {},
        # passed, but on another day
        {("upper", "2067"): ["01/14/2026 Senate read and passed"]},
        # the other chamber passed it that day
        {("upper", "2067"): ["01/13/2026 House read and passed"]},
        # a committee recommending passage, and a passage that failed, are not a chamber passing it
        {("upper", "2067"): ["01/13/2026 Committee recommends passage"]},
        {("upper", "2067"): ["01/13/2026 Senate failed to pass"]},
    ],
)
def test_title_only_roll_call_stays_unlabelled_without_a_matching_passage(history):
    (vote,) = _scrape_votes("S_17324.html", "upper", "2026", history)
    assert vote.motion_text == "FAILURES IN LATIN AMERICA"
    assert vote.motion_classification == []


@pytest.mark.parametrize(
    "name,session,chamber,bill_key,motion,classification",
    [
        # a motion line: kept, whatever the history says (a reconsideration, an amendment)
        (
            "S_18011.html",
            "2026",
            "upper",
            ("upper", "2045"),
            "Reconsider / Passage as Amended",
            ["passage"],  # OPEN-883: the re-vote after reconsidering (31-6) replaces the 32-6
        ),
        ("S_17782.html", "2026", "upper", ("lower", "7127"), "Passage", ["passage"]),
        (
            "S_17769.html",
            "2026",
            "upper",
            ("lower", "7127"),
            "BUDGET H-7127 SUB A AA",
            [],
        ),
        # a calendar marker: its own rule
        ("S_17356.html", "2026", "upper", ("upper", "2018"), "CALENDAR", ["passage"]),
        (
            "H_22382.html",
            "2026",
            "lower",
            ("lower", "7165"),
            "IMMEDIATE CONSIDERATION",
            ["passage"],
        ),
    ],
)
def test_other_header_shapes_ignore_the_history(
    name, session, chamber, bill_key, motion, classification
):
    # a history that would confirm a passage on every date of every chamber
    every = [
        "%s %s passed in concurrence" % (d, c)
        for d in (
            "01/13/2026",
            "01/22/2026",
            "06/09/2026",
            "06/10/2026",
            "06/11/2026",
            "01/20/2026",
            "06/16/2026",
            "06/20/2026",
        )
        for c in ("Senate", "House")
    ]
    (vote,) = _scrape_votes(name, chamber, session, {bill_key: every})
    assert vote.motion_text == motion
    assert vote.motion_classification == classification


@pytest.mark.parametrize(
    "lines,expected",
    [
        (["SEN ACOSTA              No. 2067", "SENATE RESOLUTION", "TITLE"], True),
        (["REP CHIPPENDALE           H 7165", "AN ACT RELATING TO", "MARRIAGES"], True),
        # a motion line ends the header
        (["REP ABNEY", "MAKING APPROPRIATION", "Approval of Amendment"], False),
        (["SEN ACOSTA   No. 2067", "TITLE", "PASSAGE"], False),
        # a calendar item, a point of order, a bare roll call, a nomination, an election
        (["CALENDAR", "ITEM 59  2026-S 3315", "TITLE"], False),
        (["POINT of ORDER", "ITEM 1  2025-S 359 SUB A", "CRIMINAL OFFENSES"], False),
        (["ROLL CALL"], False),
        (
            ["CALENDAR", "ITEM 3          0", "Appointment of a Member to the Board"],
            False,
        ),
        (["Election of the", "Senate Reading Clerk"], False),
        # "SENATOR" is not a member line, and a member line alone has no title after it
        (["SENATOR KALLMAN", "TITLE"], False),
        (["SEN ACOSTA   No. 2067"], False),
    ],
)
def test_title_only_header(lines, expected):
    assert title_only_header(lines) is expected


def test_passed_actions():
    assert passed_actions(
        [
            "01/13/2026 Recommended for Immediate Consideration",
            "01/13/2026 Senate read and passed",
            "01/20/2026 House passed Sub A as amended in concurrence",
            "01/21/2026 Committee recommends passage",
            "01/22/2026 Senate passed in concurrence",
            "01/22/2026 Transmitted to Governor",
            "01/23/2026 House failed to pass",
            "01/24/2026 Scheduled for House passage (01/24/2026)",
        ]
    ) == {
        ("upper", "2026-01-13"): "Passage",
        ("lower", "2026-01-20"): "In Concurrence",
        ("upper", "2026-01-22"): "In Concurrence",
    }
