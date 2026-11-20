"""Tests for OPEN-687: Oklahoma's roll calls are classified from the motion, and committee votes are
never passage.

The fixtures are real _VOTES.HTM pages of 2025-2026 bills (oklegislature.gov/cf/2025-26 SUPPORT
DOCUMENTS/votes/House|Senate/<bill>_VOTES.HTM, read 2026-11-20), run through the scraper's own
scrape_votes(). A floor roll call's motion is its link text, title-cased ("THIRD_READING (RCS# 0695)" ->
"Third Reading"); a committee roll call's motion is built from its header (House "Energy Committee: Do
Pass", Senate often only the committee's name, "Judiciary").
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from classify_motion import classify_motion  # noqa: E402
from ok.bills import OKBillScraper, vote_classification  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ok_open687")

# Floor motions seen on 121 vote pages (72 bills, 287 roll calls) of 2025-2026 bills, with how they are labelled.
REAL_FLOOR_MOTIONS = [
    (
        "Third Reading",
        ["passage"],
    ),  # 99 roll calls, both chambers, lost ones too (2025 SB 2 House)
    (
        "Fourth Reading",
        ["passage"],
    ),  # final passage after a CCR or concurrence (2025 SB 1000 House)
    (
        "Veto Override No Emergency",
        ["passage"],
    ),  # Senate, 2025 SB 1050 (whole-bill veto)
    (
        "Veto Override With Emergency",
        ["passage"],
    ),  # Senate, 2025 HB 2785 (whole-bill veto)
    ("Veto Override Without Emer.", ["passage"]),  # House, 2025 SB 1050
    ("Veto Override With Emer.", ["passage"]),  # House, 2025 HB 2785
    ("Adopt Resolution", ["passage"]),  # House, 2025 SCR 1
    ("Adopt Amendment", ["amendment"]),  # House, 2025 HB 1003
    ("Table Amendment", ["amendment"]),  # House, 2025 HB 1003
    (
        "Emergency",
        [],
    ),  # emergency-clause roll call (2025 HB 1003 House: measure passed, emergency failed)
    ("Advance", []),  # Senate, "Advanced to Third Reading" (2025 SB 6, 2026 SB 1400)
    ("Reconsider Measure", []),  # House, 2025 SB 2
    ("Appeal Of The Decision Of The Chair", []),  # House, 2025 SB 2
]


@pytest.mark.parametrize("motion,expected", REAL_FLOOR_MOTIONS)
def test_real_floor_motions(motion, expected):
    assert vote_classification(motion, committee=False) == expected


# Committee motions as the scraper builds them; their text says nothing reliable (Senate).
REAL_COMMITTEE_MOTIONS = [
    "Energy Committee: Do Pass",
    "Appropriations And Budget Finance Subcommittee: Do Pass",
    "Judiciary",
    "Joint Committee On Appropriations And Budget",
    "Do Pass Amended Cs",
    "Commissioner To Promulgate Rules. Effective Date.",
    # a committee vote whose text happens to look like a floor motion is still committee
    "Third Reading",
]


@pytest.mark.parametrize("motion", REAL_COMMITTEE_MOTIONS)
def test_committee_roll_calls_are_never_passage(motion):
    assert vote_classification(motion, committee=True) == ["committee-passage"]


@pytest.mark.parametrize(
    "motion",
    [
        "Veto Override Line Item",  # not seen: a line-item override is not passage
        "Third Reading Reconsidered",
        "Judiciary",  # a committee name reaching the floor path stays unlabelled
        "",
    ],
)
def test_unseen_floor_text_stays_unlabelled(motion):
    assert vote_classification(motion, committee=False) == []


def test_shared_rules_never_give_passage_for_amendment_or_emergency():
    for motion in ("Adopt Amendment", "Table Amendment", "Emergency", "Advance"):
        assert classify_motion("ok", motion) == []


class _Resp:
    def __init__(self, text):
        self.text = text


def _scrape_page(fname, edit=None):
    raw = open(os.path.join(FIXTURES, fname), "rb").read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    if edit:
        text = edit(text)
    scraper = OKBillScraper.__new__(OKBillScraper)
    scraper.warning = lambda *a, **k: None
    scraper.get = lambda url, verify=False: _Resp(text)
    chamber, bill_file = fname.split("_", 1)
    bill_id = bill_file.replace("_VOTES.HTM", "")
    bill = Bill(
        bill_id,
        legislative_session="2025",
        chamber="lower" if bill_id.startswith("H") else "upper",
        title="t",
    )
    url = "https://www.oklegislature.gov/cf/votes/%s/%s" % (chamber, bill_file)
    return [
        (v.start_date, v.motion_text, v.motion_classification, v.result)
        for v in scraper.scrape_votes(bill, url)
    ]


REAL_PAGES = {
    # House: two committee votes, a lost third reading, a reconsideration and an appeal, the third
    # reading again, and a lost fourth reading after the second CCR (2026)
    "House_SB2_VOTES.HTM": [
        ("2026-05-14", "Fourth Reading", ["passage"], "fail"),
        ("2025-05-07", "Third Reading", ["passage"], "pass"),
        ("2025-05-07", "Appeal Of The Decision Of The Chair", [], "pass"),
        ("2025-05-07", "Reconsider Measure", [], "pass"),
        ("2025-05-06", "Third Reading", ["passage"], "fail"),
        (
            "2025-04-23",
            "Energy And Natural Resources Oversight Committee: Do Pass As Amended, Strike The Title",
            ["committee-passage"],
            "pass",
        ),
        ("2025-04-09", "Energy Committee: Do Pass", ["committee-passage"], "pass"),
    ],
    "House_HB1003_VOTES.HTM": [
        ("2025-05-15", "Emergency", [], "pass"),
        ("2025-05-15", "Fourth Reading", ["passage"], "pass"),
        ("2025-03-26", "Third Reading", ["passage"], "pass"),
        ("2025-03-26", "Third Reading", ["passage"], "pass"),
        ("2025-03-26", "Adopt Amendment", ["amendment"], "pass"),
        ("2025-03-26", "Table Amendment", ["amendment"], "fail"),
        (
            "2025-02-27",
            "Judiciary And Public Safety Oversight Committee: Do Pass",
            ["committee-passage"],
            "pass",
        ),
        (
            "2025-02-19",
            "Criminal Judiciary Committee: Do Pass",
            ["committee-passage"],
            "pass",
        ),
    ],
    "House_SCR1_VOTES.HTM": [
        ("2025-02-03", "Adopt Resolution", ["passage"], "pass"),
    ],
    "Senate_SB1050_VOTES.HTM": [
        ("2025-05-29", "Veto Override No Emergency", ["passage"], "pass"),
        ("2025-03-27", "Third Reading", ["passage"], "pass"),
        ("2025-02-27", "Do Pass", ["committee-passage"], "pass"),
    ],
    "Senate_SB6_VOTES.HTM": [
        ("2025-03-12", "Third Reading", ["passage"], "pass"),
        ("2025-03-12", "Advance", [], "pass"),
        ("2025-02-11", "Education", ["committee-passage"], "pass"),
    ],
    "Senate_HB2785_VOTES.HTM": [
        ("2025-05-29", "Veto Override With Emergency", ["passage"], "pass"),
        ("2025-05-22", "Third Reading", ["passage"], "pass"),
        (
            "2025-05-19",
            "Joint Committee On Appropriations And Budget",
            ["committee-passage"],
            "pass",
        ),
    ],
}


@pytest.mark.parametrize("fname", sorted(REAL_PAGES))
def test_real_vote_pages(fname):
    assert _scrape_page(fname) == REAL_PAGES[fname]


def test_roll_call_missing_from_the_link_list_is_not_labelled_committee():
    # House SB 2's Energy Committee vote (RCS 23) with its link taken out of the page's link list:
    # nothing marks it as a committee vote any more, so it is left unlabelled (and never passage)
    def drop_link(text):
        assert text.count('href="#RCS0023"') == 1
        return text.replace('href="#RCS0023"', 'href="#gone"')

    votes = _scrape_page("House_SB2_VOTES.HTM", edit=drop_link)
    assert ("2025-04-09", "Energy Committee: Do Pass", [], "pass") in votes
    assert len(votes) == len(REAL_PAGES["House_SB2_VOTES.HTM"])


def test_house_veto_override_page():
    votes = _scrape_page("House_HB2785_VOTES.HTM")
    assert ("2025-05-29", "Veto Override With Emer.", ["passage"], "pass") in votes
    assert all(
        v[2] == ["committee-passage"] for v in votes if "Committee" in v[1]
    ), votes


def test_scraper_no_longer_hard_codes_passage():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "scrapers", "ok", "bills.py")
    ).read()
    assert 'classification="passage"' not in src
    assert "classification=vote_classification(motion, committee)" in src
