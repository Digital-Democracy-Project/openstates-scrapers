from pathlib import Path

import lxml.html
from openstates.scrape import Bill
from spatula import URL

from nv.bills import VoteList

# OPEN-595: AB 4 of the 2025 special session (2025Special36), its "Final Passage" vote list
# (GetBillVotes?billKey=12994&voteTypeId=3, fetched 2026-11-16).
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "nv_open595"
    / "ab4_2025special36_final_passage.html"
)


def _votes(html):
    bill = Bill("AB 4", "2025Special36", "t", chamber="lower", classification="bill")
    page = VoteList(
        {"bill": bill, "url": "https://example.invalid/votes"},
        source=URL("https://example.invalid/GetBillVotes"),
    )
    page.root = lxml.html.fromstring(html)
    return [member_page.input for member_page in page.process_page()]


def test_final_passage_votes_are_classified_by_the_nv_rules():
    votes = _votes(FIXTURE.read_text(encoding="utf-8"))
    assert [(v.motion_text, v.result, v.motion_classification) for v in votes] == [
        ("Assembly (1st Reprint)", "pass", ["passage"]),
        ("Senate (4th Reprint)", "pass", ["passage"]),
        # 11-18; the Senate rescinded this passage on 11-19 and passed the bill again
        ("Senate (3rd Reprint)", "pass", ["passage"]),
    ]


def test_an_unseen_label_is_left_unclassified():
    # Not seen in Nevada's data: the label is edited so the scraper must ask the nv rules, not
    # stamp "passage" on every roll call as it did before OPEN-595.
    html = FIXTURE.read_text(encoding="utf-8").replace(
        "Assembly (1st Reprint)", "Assembly (Veto)"
    )
    assert [v.motion_classification for v in _votes(html)] == [
        [],
        ["passage"],
        ["passage"],
    ]
