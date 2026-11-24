from pathlib import Path

import lxml.html
from openstates.scrape import Bill
from spatula import URL

from nv.bills import VoteList, vote_result

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
        # 11-18; NELIS says "Rescinded" (OPEN-865): voided, so not a passage vote
        ("Senate (3rd Reprint)", "fail", []),
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
        [],  # the rescinded 3rd Reprint vote (OPEN-865)
    ]


# OPEN-865: NELIS's own outcome decides the result, not yeas > nays. Real pages, fetched 2026-11-24.
FIXTURES = Path(__file__).parent / "fixtures" / "nv_open865"


def _fixture_votes(name):
    return _votes((FIXTURES / name).read_text(encoding="utf-8"))


def test_a_vote_nelis_says_passed_no_fails_though_yeas_outnumber_nays():
    # AB 5, Senate 11-19: 10-8 of 21, "Passed No (Constitutional Majority)" (11 are needed)
    votes = _fixture_votes("ab5_2025special36_final_passage.html")
    assert [(v.motion_text, v.result) for v in votes] == [
        ("Assembly (1st Reprint)", "pass"),
        ("Senate (2nd Reprint)", "fail"),
    ]
    senate = votes[1]
    assert {c["option"]: c["value"] for c in senate.counts}["yes"] == 10
    assert {c["option"]: c["value"] for c in senate.counts}["no"] == 8


def test_a_two_thirds_vote_short_of_two_thirds_fails():
    # SB 10, Assembly 11-19: 27-10 of 42, "Passed No (2/3 of Elected Members)" (28 are needed);
    # the Senate's 18-0 "Passed Yes (2/3 ...)" stays a pass
    votes = _fixture_votes("sb10_2025special36_final_passage.html")
    assert {(v.motion_text.split()[0], v.result) for v in votes} == {
        ("Assembly", "fail"),
        ("Senate", "pass"),
    }


def test_a_rescinded_vote_is_marked_and_is_not_a_passage_vote():
    votes = _votes(FIXTURE.read_text(encoding="utf-8"))
    rescinded = [v for v in votes if v.extras.get("nelis_outcome") == "Rescinded"]
    assert [v.motion_text for v in rescinded] == ["Senate (3rd Reprint)"]
    assert rescinded[0].motion_classification == []
    # the 16-2 tally is kept as NELIS shows it
    assert {c["option"]: c["value"] for c in rescinded[0].counts}["yes"] == 16
    assert all("nelis_outcome" not in v.extras for v in votes if v not in rescinded)


def test_a_vote_nelis_says_passed_yes_passes():
    # 2023 regular session: both votes "Passed Yes (Constitutional Majority)", unchanged
    votes = _fixture_votes("82nd2023_9545_final_passage.html")
    assert [v.result for v in votes] == ["pass", "pass"]


def test_vote_result_reads_nelis_text_first_and_the_count_only_when_it_is_silent():
    assert vote_result("Passed Yes (Constitutional Majority)", 1, 20) == "pass"
    assert vote_result("Passed  No  (2/3 of Elected Members)", 27, 10) == "fail"
    assert vote_result("Rescinded", 16, 2) == "fail"
    assert vote_result("", 10, 8) == "pass"
    assert vote_result("", 8, 10) == "fail"
    assert vote_result(None, 5, 5) == "fail"
