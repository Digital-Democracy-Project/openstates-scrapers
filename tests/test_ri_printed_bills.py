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

from ri.bills import RIBillScraper, printed_bill, vote_motion  # noqa: E402

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


def _scrape_votes(name, chamber, session):
    """scrape_chamber_votes over a date list naming this one real report."""
    scraper = object.__new__(RIBillScraper)
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
        # Senate 6/11/2026: "SENATE BILL - S 2045 sub a ... Reconsider": a reconsideration, not passage
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
            [],
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
