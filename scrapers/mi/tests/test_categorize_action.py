"""MI's categorize_action: upstream stopped labelling "passed by ..." actions as passage (most are
the "PASSED BY HOUSE WITH IMMEDIATE EFFECT" follow-up line). We keep the label for the real
roll-call passage lines, which carry a vote fraction (OPEN-344)."""
import pytest

from mi.bills import categorize_action


@pytest.mark.parametrize(
    "action",
    [
        "PASSED BY 3/4 VOTE ROLL CALL # 49 YEAS 34 NAYS 1 EXCUSED 2 NOT VOTING 0",
        "PASSED BY 2/3 VOTE ROLL CALL # 203 YEAS 30 NAYS 6 EXCUSED 1 NOT VOTING 0",
        "passed by 2/3 vote; given immediate effect Roll Call #163 Yeas 91 Nays 14",
    ],
)
def test_roll_call_passage_with_a_vote_fraction_keeps_its_passage_label(action):
    assert categorize_action(action) == "passage"


@pytest.mark.parametrize(
    "action",
    [
        "PASSED BY HOUSE WITH IMMEDIATE EFFECT",
        "PASSED BY HOUSE WITH SUBSTITUTE (H-1) WITH IMMEDIATE EFFECT",
        "PASSED BY HOUSE WITH AMENDMENT(S) WITH IMMEDIATE EFFECT",
        "PASSED BY HOUSE BY 2/3 VOTE WITHOUT AMENDMENT WITH IMMEDIATE EFFECT",
    ],
)
def test_immediate_effect_follow_up_lines_still_lose_the_label_as_upstream_intends(
    action,
):
    assert categorize_action(action) is None


def test_plain_passed_actions_are_still_passage():
    assert categorize_action("passed") == "passage"
