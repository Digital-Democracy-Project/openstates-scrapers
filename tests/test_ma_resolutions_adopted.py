"""OPEN-923: the House's "Resolutions adopted" vote is the resolution's passage.

BROKER-617 (comment 23853): H 4692's House vote, "Resolutions adopted - 155 YEAS to 3 NAYS (See YEA and NAY No.
111 )" (2025-11-19), was unlabelled, so the House's vote on that resolution was missed. The Senate writes the same
step "Adopted -see Roll Call #106 (Yeas 34 to Nays 4)", which the "^adopted" rule already labels.

Every Massachusetts vote action stored for the 194th (512 lines, Mac replica, 2026-11-26) was read for the wording:
"Resolutions adopted" occurs once (H 4692). "Order adopted" (H 2026, a House order, twice) is not a resolution and
stays unlabelled. The action lines are the stored ones.
"""
import os
import sys
from unittest import mock

import lxml.html
import pytest
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402


def _votes(identifier, date, chamber, action_line):
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    bill = Bill(identifier, legislative_session="194th", title="t", classification="bill")
    page = lxml.html.fromstring(
        "<table><tbody><tr><td>{}</td><td>{}</td><td>{}</td></tr></tbody></table>".format(
            date, chamber, action_line
        )
    )
    with mock.patch.object(scraper, "scrape_house_vote", return_value=True), mock.patch.object(
        scraper, "scrape_house_voters", return_value="pdf"
    ), mock.patch.object(scraper, "scrape_senate_vote", return_value=True):
        return [v for v in scraper.scrape_action_page(bill, page) if type(v).__name__ == "VoteEvent"]


def test_h4692_house_vote_is_passage():
    (vote,) = _votes(
        "H4692", "11/19/2025", "House", "Resolutions adopted - 155 YEAS to 3 NAYS (See YEA and NAY No. 111 )"
    )
    assert vote.motion_text == "Resolutions adopted"
    assert vote.motion_classification == ["passage"]
    assert vote.result == "pass"


def test_h4692_senate_vote_is_still_passage():
    (vote,) = _votes("H4692", "11/19/2025", "Senate", "Adopted -see   Roll Call #106 (Yeas 34 to Nays 4)")
    assert vote.motion_classification == ["passage"]


@pytest.mark.parametrize("text", ["Resolutions adopted", "Resolution adopted"])
def test_the_adoption_wording_is_passage(text):
    assert classify_motion("ma", text) == ["passage"]


@pytest.mark.parametrize(
    "text",
    [
        "Order adopted",  # a House order (H 2026), not a resolution
        "Resolutions reported favorably by committee",  # a committee step, never a roll call
        "Amendment #1 (Tarr) rejected",
        "Emergency preamble adopted",
    ],
)
def test_nearby_wording_is_not_passage(text):
    assert classify_motion("ma", text) == []
