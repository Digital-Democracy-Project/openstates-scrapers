"""Tests for OPEN-693: Mississippi's roll calls are classified from the motion instead of all being
"passage", and "Motion to Recommit Lost" is a lost vote.

The ms scraper turns a bill-history action that links a roll call ("(S) Passed As Amended") into a fixed
motion text through _vote_mapping ("Passage as Amended", True), then labels it with vote_classification()
in ms/bills.py (the ms block of config/motion_classification.yaml). The fixtures are the text (pdftotext)
of real roll-call PDFs linked from 2024-2026 bill histories (billstatus.ls.state.ms.us/<year>/pdf/votes/
house|senate/<n>.pdf, read 2026-11-20), run through the scraper's own scrape_votes(); HB1924_2026_history.xml
is the real bill history of 2026 HB 1924, whose override roll call is on a partial veto.
"""

import os
from datetime import datetime
import re
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

import ms.bills  # noqa: E402
from ms.bills import MSBillScraper, vote_classification  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ms_open693")

# Every motion text _vote_mapping can give, with its label (Ramon's rules: OPEN-677 comment 21792, OPEN-617,
# OPEN-583). Seen = roll calls linked from bill histories of 2024-2026 (5,404).
EXPECTED = {
    # "Passed", "Failed", "Adopted" (a resolution): 2,861 roll calls seen
    "Passage": ["passage"],
    # "Passed As Amended", "Adopted As Amended": 1,229 seen
    "Passage as Amended": ["passage"],
    # 834 seen, 3 lost (2024 HB 1988 Senate, three-fifths needed)
    "Adopt Conference Report": ["passage"],
    "Concurrence in Amendment From House": ["passage"],  # 77 seen
    "Concurrence in Amendment From Senate": ["passage"],  # 102 seen
    # a whole-bill veto; a partial one is "veto-override" (below)
    "Override Veto": ["passage"],
    "Failed To Concur": ["passage"],  # never seen: a lost concurrence vote (FOR RAMON)
    "Motion to Concur": ["passage"],  # never seen: as above (FOR RAMON)
    "Appointment Confirmation": [],  # Senate confirmations (SN measures): 297 seen
    "Adopt Committee Substitute": ["amendment"],  # never seen with a roll call
    "Conference Report Filed": [],  # filing, not a vote on the report
    "Motion to Table": [],  # 2026 SB 2828
    "Table Motion to Reconsider": [],
    "Decline to Concur": [],  # declines and invites a conference: the bill goes on
    "Motion to Suspend Rules": [],
    "Motion to Recommit": [],  # 2025 SB 2515
    "Reconsideration": [],
    "Recommit to Committee": [],
}


def test_every_mapped_motion_has_a_decided_label():
    motions = {motion for motion, _ in MSBillScraper._vote_mapping.values()}
    assert motions == set(EXPECTED)


@pytest.mark.parametrize("motion,expected", sorted(EXPECTED.items()))
def test_mapped_motion_labels(motion, expected):
    assert vote_classification(motion) == expected


def test_partial_veto_override_is_not_passage():
    assert vote_classification("Override Veto", line_item_veto=True) == [
        "veto-override"
    ]
    # the flag only matters for an override
    assert vote_classification("Passage", line_item_veto=True) == ["passage"]


def test_recommit_lost_is_a_lost_vote():
    assert MSBillScraper._vote_mapping["Motion to Recommit Lost"] == (
        "Motion to Recommit",
        False,
    )


# (fixture, bill, chamber, history action) for real roll calls: every action seen with a roll call in
# 2026 (up to three of each, both chambers) plus the rare ones of 2024-2025.
REAL_ROLL_CALLS = [
    ("2026_house_0030003.txt", "2026 HB0001", "lower", "Passed As Amended"),
    ("2026_house_0100010.txt", "2026 HB0002", "lower", "Passed As Amended"),
    ("2026_house_0160005.txt", "2026 HB0003", "lower", "Passed As Amended"),
    ("2026_senate_0590041.txt", "2026 HB0001", "upper", "Passed"),
    ("2026_senate_0230002.txt", "2026 HB0003", "upper", "Passed"),
    ("2026_senate_0590019.txt", "2026 HB0223", "upper", "Passed"),
    ("2026_house_0370037.txt", "2026 HB0017", "lower", "Passed"),
    ("2026_house_0360050.txt", "2026 HB0028", "lower", "Passed"),
    ("2026_house_0300003.txt", "2026 HB0223", "lower", "Passed"),
    ("2026_senate_0590026.txt", "2026 HB0314", "upper", "Passed As Amended"),
    ("2026_senate_0640039.txt", "2026 HB0314", "upper", "Passed As Amended"),
    ("2026_senate_0650028.txt", "2026 HB0338", "upper", "Passed As Amended"),
    (
        "2026_house_0710003.txt",
        "2026 HB0314",
        "lower",
        "Concurred in Amend From Senate",
    ),
    (
        "2026_house_0350009.txt",
        "2026 HB0431",
        "lower",
        "Concurred in Amend From Senate",
    ),
    (
        "2026_house_0650002.txt",
        "2026 HB0479",
        "lower",
        "Concurred in Amend From Senate",
    ),
    ("2026_house_0810002.txt", "2026 HB0342", "lower", "Conference Report Adopted"),
    ("2026_house_0830058.txt", "2026 HB0343", "lower", "Conference Report Adopted"),
    ("2026_house_0850003.txt", "2026 HB0377", "lower", "Conference Report Adopted"),
    ("2026_senate_0840015.txt", "2026 HB0342", "upper", "Conference Report Adopted"),
    ("2026_senate_0830085.txt", "2026 HB0343", "upper", "Conference Report Adopted"),
    ("2026_senate_0850013.txt", "2026 HB0377", "upper", "Conference Report Adopted"),
    ("2026_house_0370008.txt", "2026 HB0362", "lower", "Failed"),
    ("2026_house_0640013.txt", "2026 SB2436", "lower", "Failed"),
    ("2026_house_1000005.txt", "2026 HB1924", "lower", "Veto Overridden"),
    ("2026_senate_0710019.txt", "2026 HB4033", "upper", "Failed"),
    ("2026_senate_0810013.txt", "2026 HB4135", "upper", "Failed"),
    ("2026_senate_1000003.txt", "2026 HC0065", "upper", "Failed"),
    ("2026_house_0030002.txt", "2026 HC0002", "lower", "Adopted"),
    ("2026_house_0710014.txt", "2026 HC0058", "lower", "Adopted"),
    ("2026_house_0840047.txt", "2026 HC0064", "lower", "Adopted"),
    ("2026_senate_0150003.txt", "2026 HC0002", "upper", "Adopted"),
    ("2026_senate_0300013.txt", "2026 HC0008", "upper", "Adopted"),
    ("2026_senate_0300013.txt", "2026 HC0009", "upper", "Adopted"),
    ("2026_senate_0240004.txt", "2026 HC0021", "upper", "Adopted As Amended"),
    (
        "2026_senate_0650012.txt",
        "2026 SB2096",
        "upper",
        "Concurred in Amend From House",
    ),
    (
        "2026_senate_0670004.txt",
        "2026 SB2126",
        "upper",
        "Concurred in Amend From House",
    ),
    (
        "2026_senate_0670005.txt",
        "2026 SB2360",
        "upper",
        "Concurred in Amend From House",
    ),
    ("2026_senate_0860011.txt", "2026 SB2828", "upper", "Tabled Failed"),
    ("2026_senate_0810011.txt", "2026 SN0001", "upper", "Appointment Confirmed"),
    ("2026_senate_0790006.txt", "2026 SN0002", "upper", "Appointment Confirmed"),
    ("2026_senate_0590014.txt", "2026 SN0003", "upper", "Appointment Confirmed"),
    ("2025_senate_0310061.txt", "2025 SB2515", "upper", "Motion to Recommit Lost"),
    ("2025_senate_0860023.txt", "2025 SN0032", "upper", "Appointment Not Confirmed"),
    ("2024_senate_1230024.txt", "2024 HB1988", "upper", "Conference Report Failed"),
]


def run_scrape_votes(
    monkeypatch, tmp_path, fixture, action, chamber, line_item_veto=False
):
    text = open(os.path.join(FIXTURES, fixture), "rb").read()
    scraper = MSBillScraper.__new__(MSBillScraper)

    def urlretrieve(url, verify=False):
        path = tmp_path / "vote.pdf"
        path.write_bytes(b"")
        return str(path), None

    monkeypatch.setattr(scraper, "urlretrieve", urlretrieve, raising=False)
    monkeypatch.setattr(ms.bills, "convert_pdf", lambda path, kind: text)
    bill = Bill("HB 1", legislative_session="2026", chamber=chamber, title="t")

    votes = list(
        scraper.scrape_votes(
            "http://billstatus.ls.state.ms.us/x.pdf",
            action,
            datetime(2026, 1, 1),
            chamber,
            bill,
            line_item_veto,
        )
    )
    assert len(votes) == 1
    return votes[0], text.decode()


@pytest.mark.parametrize("fixture,bill,chamber,action", REAL_ROLL_CALLS)
def test_real_roll_calls(monkeypatch, tmp_path, fixture, bill, chamber, action):
    vote, text = run_scrape_votes(monkeypatch, tmp_path, fixture, action, chamber)
    motion = MSBillScraper._vote_mapping[action][0]
    assert vote.motion_classification == EXPECTED[motion]
    # the result agrees with the roll call's own words ("... failed to pass", "the motion to
    # recommit ... failed"), independent of the mapping
    head = " ".join(text.split("Yeas--")[0].split())
    assert vote.result == ("fail" if re.search(r"\bfail", head) else "pass"), head


def test_real_roll_calls_cover_both_chambers_and_30_plus():
    assert len(REAL_ROLL_CALLS) >= 30
    assert {chamber for _, _, chamber, _ in REAL_ROLL_CALLS} == {"upper", "lower"}


class FakeResponse:
    def __init__(self, content):
        self.content = content


def scrape_hb1924(monkeypatch, tmp_path, history):
    """Run the real scrape_bills() over 2026 HB 1924's real history (offline)."""
    scraper = MSBillScraper.__new__(MSBillScraper)
    allmsrs = open(os.path.join(FIXTURES, "allmsrs_HB1924_2026.xml"), "rb").read()

    def get(url, verify=False):
        return FakeResponse(allmsrs if "all_measures" in url else history)

    def urlretrieve(url, verify=False):
        m = re.search(r"/votes/(house|senate)/(\d+)\.pdf$", url)
        path = tmp_path / ("2026_%s_%s.txt" % m.groups())
        shutil.copy(os.path.join(FIXTURES, path.name), path)
        return str(path), None

    monkeypatch.setattr(scraper, "get", get, raising=False)
    monkeypatch.setattr(scraper, "urlretrieve", urlretrieve, raising=False)
    monkeypatch.setattr(
        ms.bills, "convert_pdf", lambda path, kind: open(path, "rb").read()
    )
    votes = [
        o for o in scraper.scrape_bills("lower", "2026") if not isinstance(o, Bill)
    ]
    return {v.motion_text: v for v in votes}


def test_hb1924_partial_veto_override_end_to_end(monkeypatch, tmp_path):
    history = open(os.path.join(FIXTURES, "HB1924_2026_history.xml"), "rb").read()
    votes = scrape_hb1924(monkeypatch, tmp_path, history)
    assert set(votes) == {
        "Passage",
        "Passage as Amended",
        "Adopt Conference Report",
        "Override Veto",
    }
    assert votes["Override Veto"].motion_classification == ["veto-override"]
    assert votes["Override Veto"].result == "pass"
    for motion in ("Passage", "Passage as Amended", "Adopt Conference Report"):
        assert votes[motion].motion_classification == ["passage"]


def test_whole_bill_veto_override_end_to_end(monkeypatch, tmp_path):
    # the same history with a whole-bill veto in place of the partial one
    history = open(os.path.join(FIXTURES, "HB1924_2026_history.xml"), "rb").read()
    assert b"Partially Vetoed By Governor" in history
    history = history.replace(b"Partially Vetoed By Governor", b"Vetoed")
    votes = scrape_hb1924(monkeypatch, tmp_path, history)
    assert votes["Override Veto"].motion_classification == ["passage"]
