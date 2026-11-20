"""OPEN-688: a Kentucky roll call is stored under the chamber that took it.

scrape_votes stored every roll call in a bill's vote_history.pdf under the bill's own chamber, so a House vote on a
Senate bill was filed as a Senate vote and its House voters matched no one (940 of 1,684 member votes unresolved in the
2026RS probe sample). Each page of the PDF is one roll call headed by the body that took it. The fixtures are
apps.legislature.ky.gov's own vote_history.pdf files: 2026RS SB 1 (Senate bill, two House votes) and 2025RS HB 90
(House bill, two Senate votes; shared with scrapers/ky/tests).
"""
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from ky.bills import KYBillScraper, voting_chamber  # noqa: E402

HERE = os.path.dirname(__file__)
SB1_2026 = os.path.join(HERE, "fixtures", "ky_open688", "26RS_sb1_vote_history.pdf")
HB90_2025 = os.path.join(
    HERE, "..", "scrapers", "ky", "tests", "testdata", "hb90_vote_history.pdf"
)


def scraped_votes(pdf, bill_chamber, tmp_path):
    # scrape_votes deletes the file it reads, so give it a copy
    copy = str(tmp_path / os.path.basename(pdf))
    shutil.copy(pdf, copy)
    scraper = KYBillScraper({"name": "Kentucky"}, str(tmp_path))
    scraper.urlretrieve = lambda url, verify=None: (copy, None)
    bill = Bill("X 1", legislative_session="2026RS", chamber=bill_chamber, title="t")
    # the chamber is stored as a pseudo id: ~{"classification": "upper"}
    return [
        (
            json.loads(ve.organization[1:])["classification"],
            ve.motion_text,
            {v["voter_name"] for v in ve.votes},
        )
        for ve in scraper.scrape_votes("https://example.com/v.pdf", bill, bill_chamber)
    ]


def test_house_votes_on_a_senate_bill_are_stored_under_the_house(tmp_path):
    votes = scraped_votes(SB1_2026, "upper", tmp_path)
    assert [(chamber, motion) for chamber, motion, _ in votes] == [
        ("upper", "PASS SB 1"),
        ("lower", "Pass"),
        ("upper", "FINAL PASSAGE OF SB 1 w/ HFA 2"),
        ("upper", "OVERRIDE VETO FINAL PASSAGE SB 1"),
        ("lower", "Veto Override"),
    ]
    # Fister is a House member (unresolved on the probe's "upper" roll call); Stivers is the Senate President
    house_pass = votes[1][2]
    assert "Fister" in house_pass and "Stivers" not in house_pass
    assert "Stivers" in votes[0][2] and "Fister" not in votes[0][2]


def test_senate_votes_on_a_house_bill_are_stored_under_the_senate(tmp_path):
    votes = scraped_votes(HB90_2025, "lower", tmp_path)
    assert [chamber for chamber, _, _ in votes] == [
        "lower",
        "upper",
        "lower",
        "lower",
        "upper",
    ]
    assert ("upper", "PASS HB 90 W/ scs1 scta1") in [(c, m) for c, m, _ in votes]


@pytest.mark.parametrize(
    "line,expected",
    [
        ("                                 COMMONWEALTH OF KENTUCKY SENATE", "upper"),
        ("                                  House of Representatives", "lower"),
        ("                                  Commonwealth of Kentucky", None),
        # a motion that names the other chamber is not a header
        ("CONCUR IN SENATE AMENDMENTS                     4:45:11 PM", None),
        ("CONCUR IN HOUSE OF REPRESENTATIVES AMENDMENT", None),
    ],
)
def test_voting_chamber_reads_only_the_page_header(line, expected):
    assert voting_chamber(line) == expected


def test_a_page_with_no_header_falls_back_to_the_bill_chamber(tmp_path, monkeypatch):
    # SB 1's text with the header taken off its first House page (page 2): that page alone takes the bill's chamber,
    # not the Senate header of the page before it
    import ky.bills

    real_text = ky.bills.convert_pdf(SB1_2026, "text")
    first_house_header = real_text.index(b"House of Representatives")
    line_end = real_text.index(b"\n", first_house_header)
    headless = real_text[:first_house_header] + real_text[line_end:]
    monkeypatch.setattr(ky.bills, "convert_pdf", lambda filename, type: headless)
    votes = scraped_votes(SB1_2026, "lower", tmp_path)
    assert [chamber for chamber, _, _ in votes] == [
        "upper",
        "lower",  # the bill's chamber: this page names none
        "upper",
        "upper",
        "lower",
    ]
