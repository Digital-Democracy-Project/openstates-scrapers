"""Tests for OPEN-691: Hawaii's roll calls are classified from their motion text.

Every text below is real: the first sentence of a bill-status action that holds a tally, cut the way
parse_vote() in hi/bills.py cuts it, from the 2026 status pages on data.capitol.hawaii.gov
(session/measure_indiv.aspx, read 2026-11-20; the veto override is HB 862 of 2021). The two
"Reconsider: " texts put the scraper's own prefix on a real text. The House floor texts are tallies the scraper's vote
patterns do not read yet; they are ruled on now so they are right once it does.
"""
import json
import os
import re
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import _config, classify_motion  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open691")

HI_CASES = [
    # committee votes, House and Senate (both chambers write them differently)
    (
        "The committee on CAA recommend that the measure be PASSED, UNAMENDED.",
        ["committee-passage"],
    ),  # probe
    (
        "The committee on PBS recommend that the measure be PASSED, WITH AMENDMENTS.",
        ["committee-passage"],
    ),  # probe
    (
        "The committee on FIN recommend that the measure be PASSED, WITH AMENDMENTS.",
        ["committee-passage"],
    ),  # HB1800
    (
        "The committee(s) on  WAM recommend(s) that the measure be PASSED, WITH AMENDMENTS.",  # HB1800
        ["committee-passage"],
    ),
    (
        "The committee(s) on JDC recommend(s) that the measure be PASSED, UNAMENDED.",  # HB1628
        ["committee-passage"],
    ),
    # the House wording on 2021 pages (HB862)
    (
        "The committees on FIN recommend that the measure be PASSED, WITH AMENDMENTS.",
        ["committee-passage"],
    ),
    # a resolution's committee vote, SR10
    (
        "The committee(s) on EIG recommend(s) that the measure be PASSED, UNAMENDED.",
        ["committee-passage"],
    ),
    # the conference committee's own vote (the floor then votes the draft on Final Reading), HB1800
    (
        "The Conference committee recommends that the measure be PASSED, WITH AMENDMENTS.",
        ["committee-passage"],
    ),
    (
        "The Conference Committee recommends that the measure be Passed, with Amendments.",
        ["committee-passage"],
    ),
    # Senate floor: third and final reading
    ("Passed Third Reading, as amended (SD 1).", ["passage"]),  # HB1800
    ("Report adopted; Passed Third Reading.", ["passage"]),  # HB1628
    ("Report Adopted; Passed Third Reading.", ["passage"]),  # HB1663
    (
        "Report adopted; Passed Third Reading, as amended (SD  1).",
        ["passage"],
    ),  # HB1656
    ("Report Adopted; Passed Third Reading, as amended (SD 2).", ["passage"]),  # HB1740
    (
        "Passed Final Reading, as amended (CD 1).",
        ["passage"],
    ),  # HB1800, the conference draft
    # Senate resolution adopted on the floor, SR20
    ("Report and Resolution Adopted as amended (SD 1).", ["passage"]),
    # House floor (not read by the scraper's vote patterns yet)
    (
        "Passed Third Reading with Representative(s) Iwamoto voting aye with reservations; none voting no (0) "
        "and Representative(s) Perruso excused (1).",  # HB1614
        ["passage"],
    ),
    (
        "Passed Third Reading as amended in HD 3 with none voting aye with reservations; none voting no (0) "
        "and Representative(s) Pierick excused (1).",  # HB1782
        ["passage"],
    ),
    (
        "Passed Final Reading as amended in CD 1 with none voting aye with reservations; none voting no (0) "
        "and none excused (0).",  # HB1642, the conference draft
        ["passage"],
    ),
    # HB1705: the House agrees to the Senate's draft by voting it on Final Reading (concurrence)
    (
        "Passed Final Reading as amended in SD 2 with Representative(s) Garcia voting aye with reservations; "
        "none voting no (0) and Representative(s) Evslin excused (1).",
        ["passage"],
    ),
    (
        "Adopted with none voting aye with reservations; none voting no (0) and  Representative(s) Cochran "
        "excused (1).",  # HCR10
        ["passage"],
    ),
    (
        "Adopted as amended in HD 1 with Representative(s) Garcia, Gedeon, Shimizu voting aye with "
        "reservations; Representative(s) Pierick voting no (1) and  Representative(s) Cochran excused (1).",  # HR50
        ["passage"],
    ),
    # House floor votes that move the bill on: not passage
    (
        "Passed Second Reading as amended in HD 1 and referred to the committee(s) on FIN with none voting aye "
        "with reservations; none voting no (0) and none excused (0).",  # HB1607
        [],
    ),
    (
        "Passed Second Reading as amended in HD 1; placed on the calendar for Third Reading with "
        "Representative(s) Kila voting aye with reservations; Representative(s) Alcos voting no (1) and "
        "Representative(s) Perruso excused (1).",  # HB1768 (names shortened)
        [],
    ),
    (
        "Report adopted; referred to the committee(s) on FIN with none voting aye with reservations; none "
        "voting no (0) and none excused (0).",  # HB1740
        [],
    ),
    # whole-bill veto override, HB862 of 2021 (2021 status page; none in 2026)
    (
        "Veto overridden - 2/3's vote: Ayes, 17; Aye(s) with reservations: Senator(s) Moriwaki .",
        ["passage"],
    ),
    (
        "Veto overridden by 2/3's vote with 38 Ayes; 8 Noes Representative(s) Har, Kong, McDermott, Okimoto, "
        "Takumi, Tokioka, Ward, Wildberger; and 4 Excused Representative(s) Ilagan, McKelvey, Nishimoto, Ohno",
        ["passage"],
    ),
    # a roll call taken again after a reconsideration keeps what it decides
    ("Reconsider: Passed Final Reading, as amended (CD 1).", ["passage"]),
    ("Reconsider: Report adopted; Passed Second Reading, as amended (SD 1).", []),
]

# not seen with a tally: anything else stays unlabelled, never passage
HI_UNSEEN = [
    # a committee's deferral has no tally on the status pages (HB1607); if one ever does, it is not a pass
    ("The committee(s) on WAM recommend(s) that the measure be deferred.", []),
    # voice actions today (HB1800, HB1705)
    ("Senate agrees with House amendments.", []),
    ("House disagrees with Senate amendment (s).", []),
    ("Received notice of passage on Final Reading in House (Hse. Com. No. 885).", []),
    ("", []),
]


@pytest.mark.parametrize("text,expected", HI_CASES + HI_UNSEEN)
def test_hi(text, expected):
    assert classify_motion("hi", text) == expected


@pytest.mark.parametrize("text,expected", HI_CASES)
def test_hi_every_real_text_is_decided_by_a_rule(text, expected):
    # the not-passage texts are named on purpose, so a later, wider passage pattern cannot pick them up
    cfg = _config["jurisdictions"]["hi"]
    key = {"passage": "passage", "committee-passage": "committee_passage"}.get(
        (expected or [None])[0], "not_passage"
    )
    assert any(re.search(p, text.lower()) for p in cfg[key])


def _scraper_votes(name, bill_id, chamber):
    page = lxml.html.fromstring(open(os.path.join(FIXTURES, name), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber=chamber)
    return list(
        scraper.parse_bill_actions_table(
            bill,
            table,
            bill_id,
            "2026 Regular Session",
            "https://example/" + name,
            chamber,
        )
    )


@pytest.mark.parametrize(
    "name,bill_id,chamber,expected",
    [
        (
            "HB1800.html",
            "HB1800",
            "lower",
            [
                ("upper", "Passed Final Reading, as amended (CD 1).", ["passage"]),
                (
                    "upper",
                    "The Conference committee recommends that the measure be PASSED, WITH AMENDMENTS.",
                    ["committee-passage"],
                ),
                (
                    "lower",
                    "The Conference Committee recommends that the measure be Passed, with Amendments.",
                    ["committee-passage"],
                ),
                ("upper", "Passed Third Reading, as amended (SD 1).", ["passage"]),
                (
                    "upper",
                    "The committee(s) on  WAM recommend(s) that the measure be PASSED, WITH AMENDMENTS.",
                    ["committee-passage"],
                ),
                (
                    "lower",
                    "The committee on FIN recommend that the measure be PASSED, WITH AMENDMENTS.",
                    ["committee-passage"],
                ),
            ],
        ),
        (
            "HB1628.html",
            "HB1628",
            "lower",
            [
                ("upper", "Report adopted; Passed Third Reading.", ["passage"]),
                (
                    "upper",
                    "The committee(s) on JDC recommend(s) that the measure be PASSED, UNAMENDED.",
                    ["committee-passage"],
                ),
                (
                    "upper",
                    "The committee(s) on WAM recommend(s) that the measure be PASSED, UNAMENDED.",
                    ["committee-passage"],
                ),
                (
                    "upper",
                    "The committee(s) on  PSM recommend(s) that the measure be PASSED, WITH AMENDMENTS.",
                    ["committee-passage"],
                ),
                (
                    "lower",
                    "The committee on JHA recommend that the measure be PASSED, WITH AMENDMENTS.",
                    ["committee-passage"],
                ),
                (
                    "lower",
                    "The committee on PBS recommend that the measure be PASSED, WITH AMENDMENTS.",
                    ["committee-passage"],
                ),
            ],
        ),
        (
            "SR10.html",
            "SR10",
            "upper",
            [
                (
                    "upper",
                    "The committee(s) on HHS recommend(s) that the measure be PASSED, UNAMENDED.",
                    ["committee-passage"],
                ),
                (
                    "upper",
                    "The committee(s) on EIG recommend(s) that the measure be PASSED, UNAMENDED.",
                    ["committee-passage"],
                ),
            ],
        ),
    ],
)
def test_real_status_pages(name, bill_id, chamber, expected):
    votes = _scraper_votes(name, bill_id, chamber)
    got = [
        (
            json.loads(v.organization[1:])["classification"],
            v.motion_text,
            v.motion_classification,
        )
        for v in votes
    ]
    assert got == expected


def test_scraper_no_longer_hard_codes_passage():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "scrapers", "hi", "bills.py")
    ).read()
    assert 'classification="passage"' not in src
    assert 'classification=classify_motion("hi", motion_text)' in src
