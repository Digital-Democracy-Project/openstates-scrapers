"""OPEN-885: two Oklahoma roll calls whose text does not say they are the chamber's passage vote.

Fixtures are the real _VOTES.HTM pages (oklegislature.gov, read 2026-11-24) of the seven bill-chambers
the scorecard measurement found uncounted: four House "Advance From General Order" roll calls (the
legislature's history records each day as "Third Reading, Measure ... passed", the House's only vote on
the bill) and three Senate resolution "Adopt" roll calls. The history lines are the bill page's own.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))
sys.path.insert(0, os.path.dirname(__file__))

from openstates.scrape import Bill  # noqa: E402

from ok.bills import (  # noqa: E402
    OKBillScraper,
    advance_is_passage,
    third_reading_passed,
    vote_classification,
)
from test_ok_votes import FIXTURES as OPEN687_FIXTURES, _Resp  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ok_open885")

# (fname, bill type, session, the House history entries of the roll call's day)
HOUSE_ADVANCE = [
    (
        "House_HB1491_VOTES.HTM",
        "2025-03-26",
        "Third Reading, Measure and Emergency passed:  Ayes: 80 Nays: 16",
    ),
    (
        "House_SB135_VOTES.HTM",
        "2025-05-01",
        "Third Reading, Measure and Emergency passed:  Ayes: 68 Nays: 14",
    ),
    (
        "House_HB3749_VOTES.HTM",
        "2026-03-25",
        "Third Reading, Measure passed:  Ayes: 80 Nays: 15",
    ),
    (
        "House_SB1806_VOTES.HTM",
        "2026-05-06",
        "Third Reading, Measure and Emergency passed:  Ayes: 91 Nays: 0",
    ),
]
SENATE_ADOPT = [
    ("Senate_SCR12_VOTES.HTM", "concurrent resolution", "2025-05-29"),
    ("Senate_SR13_VOTES.HTM", "resolution", "2025-04-07"),
    ("Senate_HCR1027_VOTES.HTM", "concurrent resolution", "2026-05-05"),
]


def scrape(folder, fname, bill_type, history=()):
    raw = open(os.path.join(folder, fname), "rb").read()
    text = raw.decode("cp1252")
    scraper = OKBillScraper.__new__(OKBillScraper)
    scraper.warning = lambda *a, **k: None
    scraper.get = lambda url, verify=False: _Resp(text)
    chamber, bill_file = fname.split("_", 1)
    bill = Bill(
        bill_file.split("_")[0],
        legislative_session="2025",
        chamber="lower" if chamber == "House" else "upper",
        title="t",
        classification=[bill_type],
    )
    for day, who, description in history:
        bill.add_action(description=description, date=day, chamber=who)
    url = "https://www.oklegislature.gov/cf/votes/%s/%s" % (chamber, bill_file)
    return list(scraper.scrape_votes(bill, url))


@pytest.mark.parametrize("fname,day,action", HOUSE_ADVANCE)
def test_house_advance_that_is_the_third_reading_is_passage(fname, day, action):
    votes = scrape(FIXTURES, fname, "bill", [(day, "lower", action)])
    advance = [v for v in votes if v.motion_text == "Advance From General Order"]
    assert len(advance) == 1 and advance[0].start_date == day
    assert advance[0].motion_classification == ["passage"]
    # the committee roll calls on the same page keep their label
    others = [v for v in votes if v is not advance[0]]
    assert others and all(
        v.motion_classification == ["committee-passage"] for v in others
    )


@pytest.mark.parametrize("fname,day,action", HOUSE_ADVANCE)
def test_house_advance_without_the_history_saying_so_stays_unlabelled(
    fname, day, action
):
    for history in (
        [],
        [(day, "lower", "General Order")],
        # the Senate's passage on the same day is not the House's
        [(day, "upper", action)],
        # another day
        [("2024-01-01", "lower", action)],
    ):
        votes = scrape(FIXTURES, fname, "bill", history)
        advance = [v for v in votes if v.motion_text == "Advance From General Order"]
        assert advance[0].motion_classification == []


def test_house_advance_with_a_third_reading_roll_call_that_day_stays_unlabelled():
    # the History says the House passed the bill; the third reading roll call is the passage
    assert not advance_is_passage(
        "Advance From General Order",
        "lower",
        "2025-03-26",
        [("2025-03-26", "lower", "Third Reading, Measure passed:  Ayes: 80 Nays: 15")],
        {"2025-03-26"},
    )
    assert advance_is_passage(
        "Advance From General Order",
        "lower",
        "2025-03-26",
        [("2025-03-26", "lower", "Third Reading, Measure passed:  Ayes: 80 Nays: 15")],
        set(),
    )


def test_the_senates_advance_is_never_passage():
    # Senate SB 6 of 2025: "Advance" then "Third Reading" the same day; the Senate's history reads
    # "Measure passed", and even a House-style line would not count for the Senate
    votes = scrape(
        OPEN687_FIXTURES,
        "Senate_SB6_VOTES.HTM",
        "bill",
        [("2025-03-12", "upper", "Third Reading, Measure passed:  Ayes: 40 Nays: 5")],
    )
    by_motion = {v.motion_text: v.motion_classification for v in votes}
    assert by_motion["Advance"] == []
    assert by_motion["Third Reading"] == ["passage"]
    assert not advance_is_passage(
        "Advance From General Order",
        "upper",
        "2025-03-12",
        [("2025-03-12", "upper", "Third Reading, Measure passed")],
        set(),
    )
    assert not advance_is_passage(
        "Advance",
        "upper",
        "2025-03-12",
        [("2025-03-12", "upper", "Third Reading, Measure passed")],
        set(),
    )


def test_third_reading_passed_reads_only_a_third_reading_pass_by_that_chamber_that_day():
    history = [
        (
            "2025-03-26",
            "lower",
            "Third Reading, Measure and Emergency passed:  Ayes: 80 Nays: 16",
        ),
        ("2025-03-26", "lower", "Emergency added"),
        ("2025-03-27", "upper", "Second Reading referred to Education"),
    ]
    assert third_reading_passed(history, "lower", "2025-03-26")
    assert not third_reading_passed(history, "upper", "2025-03-26")
    assert not third_reading_passed(history, "lower", "2025-03-27")
    assert not third_reading_passed(
        [("2025-03-26", "lower", "Third Reading, Measure failed:  Ayes: 40 Nays: 56")],
        "lower",
        "2025-03-26",
    )


@pytest.mark.parametrize("fname,bill_type,day", SENATE_ADOPT)
def test_senate_resolution_adoption_is_passage(fname, bill_type, day):
    votes = scrape(FIXTURES, fname, bill_type)
    assert [(v.start_date, v.motion_text) for v in votes] == [(day, "Adopt")]
    assert votes[0].motion_classification == ["passage"]


@pytest.mark.parametrize("fname,bill_type,day", SENATE_ADOPT)
def test_adopt_on_a_bill_stays_unlabelled(fname, bill_type, day):
    votes = scrape(FIXTURES, fname, "bill")
    assert votes[0].motion_classification == []


def test_other_adopt_and_emergency_texts_are_unchanged():
    for motion in ("Adopt Amendment", "Table Amendment"):
        assert vote_classification(motion, False, resolution=True) == ["amendment"]
    for motion in ("Emergency", "Special Election", "Adopt Motion", "Advance"):
        assert vote_classification(motion, False, resolution=True) == []
    assert vote_classification("Adopt", True, resolution=True) == ["committee-passage"]
    assert vote_classification("Adopt Resolution", False) == ["passage"]
