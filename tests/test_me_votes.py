"""Tests for OPEN-698: Maine's roll calls are classified from the motion, not all labelled passage.

The motion texts are real: the link text of every roll call on the Roll-calls tab of 485 session-132 papers
(legislature.maine.gov/LawMakerWeb/rollcalls.asp?ID=<paper>, 1,057 roll calls, read 2026-11-20). The fixtures
are real rollcall.asp pages of those papers, run through the scraper's own scrape_votes() / scrape_vote().
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from classify_motion import classify_motion  # noqa: E402
from me.bills import MEBillScraper, vote_classification  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "me_open698")

# Passage: a bill's enactment, a resolve's final passage, the chamber's engrossment vote, an order's passage,
# a resolution's adoption and a whole-bill veto override. Counts are roll calls in the sample.
REAL_PASSAGE = [
    "Enactment",  # 24, House (LD 117, RC 114: "PASSED TO BE ENACTED")
    "ENACTMENT",  # 20, Senate ("PASSED TO BE ENACTED, in concurrence")
    "Enactment - Emer",  # 5
    "Enactment - Mandate",
    "Enactment - Bond Issue",
    "ENACTMENT-BOND ISSUE",
    "ENACTMENT-EMERGENCY",
    "ENACT-EMER 2/3 ELECT",
    "Final Passage",  # a resolve's final vote ("FAILED FINAL PASSAGE")
    "final passage",
    "Final Passage - Con Res",  # constitutional resolution
    "Final Passage - Emer",
    "FINAL PASSAGE-EMERGENCY 2/3 ELECTED",
    "PASSAGE TO BE ENGROSSED",  # 7
    "PASSAGE TO BE ENGROSSED AS AMENDED",  # 9
    "Passage to be Engrossed",
    "PASSAGE OF EMERGENCY MEASURE",  # House RC 13: "PASSAGE TO BE ENACTED FAILED"
    "PASSAGE",  # 13, Senate joint orders "READ and PASSED" (SP 97)
    "Passage",  # House order HO 19 "READ and PASSED"
    "ADOPTION",  # SP 10 joint resolution "FAILED ADOPTION"
    "Adoption",  # HR 1 "READ and ADOPTED"
    "Reconsideration - Veto",  # "Shall this Bill become a law notwithstanding the objections of the Governor?"
    "RECONSIDERATION - VETO",
    "reconsideration-veto",
    "VETO OVERRIDE (2/3)",
]

# Amendment roll calls (65 distinct texts in the sample, a selection of each shape).
REAL_AMENDMENT = [
    "ADOPT CAH-1",
    "ADOPT HAH-126 to CAS-44",
    "ADOPT CAH-1 AS AMENDED BY HHH-9",
    "ADOPT C A AS AM BY HRH-33",
    "ADOPT SAS-1",
    "ADOPT SENATE AMENDMENT (S-426) to COMMITTEE AMENDMENT",
    "ADOPT SENATE AMENDMENT (S-392) to LD 297",
    "ADOPT HOUSE AMENDMENT R (H-33) to COMMITEE AMENDMENT",
    "ADOPT COMMITTEE AMENDMENT AS AMENDED BY HOUSE AMENDMENT",
    "INDEF PP HAH-2 TO CAH-1",
    "INDEF PP HAH-34 TO SP 519",
    "INDEF PP HAH-47",
    "IPP HAH-640",
    "INDEFINITELY POSTPONE SENATE AMENDMENT (SAS-1)",
]

# Left unlabelled: committee-report acceptance (Ramon decides; see the PR), indefinite postponement of the
# bill, recede and concur, substitution, and procedure.
REAL_UNLABELLED = [
    "ACC MAJ OTP AS AMENDED REP",  # 139
    "ACCEPT MAJORITY OUGHT TO PASS AS AMENDED REPORT",  # 135
    "ACCEPT MAJORITY OUGHT NOT TO PASS REPORT",  # 130
    "ACC MAJ OUGHT NOT TO PASS REP",  # 127 (LD 115, House RC 250: accepted, "(DEAD)")
    "ACCEPT MINORITY OUGHT TO PASS AS AMENDED REPORT",
    "ACCEPT REPORT 'A' OUGHT TO PASS AS AMENDED",
    "ACCEPT REPORT 'B' OUGHT NOT TO PASS",
    'ACC REPORT "B" ONTP',
    'acc report "a" otp-am by ca "a"',
    "OTP-AM",
    "ACCEPT REPORT",
    "ACCEPTANCE OF REPORT",
    "ACC MAJORITY REPORT",  # a "Refer to Committee" report
    "recon of maj rep otp-am by ca-a",
    "SUBSTITUTE JOINT RES FOR COMMITTEE RPT",
    "INDEFINITELY POSTPONE",  # 13: the bill (12) or, once, an amendment (Senate RC 628)
    "RECEDE AND CONCUR",  # 70: concurs in whatever the other chamber did
    "RECEDE",
    "INSIST",
    "INSIST/ASK FOR COMMITTEE OF CONFERENCE",
    "RECONSIDER",
    "TABLE UNTIL LATER",
    "REFERENCE",
    "REFERENCE TO JUDICIARY",
    "COMMIT",
    "SUSPEND RULES (2/3)",
    "suspend house rule 515",
    "CONFIRMATION BE OVERRIDDEN",  # 32, nominations
    "PLACE ON FILE",
    "FORTHWITH",
    "1ST READING",
    "DISPENSING OF THE READING",
    'DISPENSE THE READING OF H"D"',
    "Move the Previous Question",
    "RULE COMM",
]


@pytest.mark.parametrize("motion", REAL_PASSAGE)
def test_real_passage_motions(motion):
    assert vote_classification(motion) == ["passage"]


@pytest.mark.parametrize("motion", REAL_AMENDMENT)
def test_real_amendment_motions(motion):
    assert vote_classification(motion) == ["amendment"]


@pytest.mark.parametrize("motion", REAL_UNLABELLED)
def test_real_unlabelled_motions(motion):
    assert vote_classification(motion) == []


@pytest.mark.parametrize(
    "motion",
    [
        "Reconsideration - Line Item Veto",  # not seen: a line-item override is not passage
        "PASSAGE TO BE ENGROSSED FAILED RECONSIDER",
        "ADOPTION OF REPORT",
        "",
    ],
)
def test_unseen_text_stays_unlabelled(motion):
    assert vote_classification(motion) == []


def test_shared_rules_never_give_passage_for_amendment_or_report():
    for motion in REAL_AMENDMENT + REAL_UNLABELLED:
        assert classify_motion("me", motion) == []


class _Resp:
    def __init__(self, text):
        self.text = text


def _scraper(pages):
    scraper = MEBillScraper.__new__(MEBillScraper)
    scraper.get = lambda url, **kwargs: _Resp(pages[url])
    return scraper


def _page(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


BASE = "https://legislature.maine.gov/LawMakerWeb/"


def _bill():
    return Bill("SP 10", legislative_session="132", chamber="upper", title="t")


def test_sp10_roll_calls_from_the_real_page():
    # SP 10 (132): the ticket's four roll calls, all stored as passage before OPEN-698
    pages = {BASE + "rollcalls.asp?ID=280095518": _page("rollcalls_280095518.html")}
    for rc in (218, 219, 220, 221):
        url = BASE + f"rollcall.asp?ID=280095518&chamber=Senate&serialnumber={rc}"
        pages[url] = _page(f"rollcall_280095518_Senate_{rc}.html")
    votes = list(
        _scraper(pages).scrape_votes(_bill(), BASE + "rollcalls.asp?ID=280095518")
    )
    assert [
        (v.motion_text, v.motion_classification, v.result, v.identifier) for v in votes
    ] == [
        ("ACCEPT MAJORITY OUGHT NOT TO PASS REPORT", [], "fail", "S-RC 218"),
        ("SUBSTITUTE JOINT RES FOR COMMITTEE RPT", [], "fail", "S-RC 219"),
        ("ACCEPT MINORITY OUGHT TO PASS AS AMENDED REPORT", [], "pass", "S-RC 220"),
        ("ADOPTION", ["passage"], "fail", "S-RC 221"),
    ]
    # nothing is dropped: every member's vote is still recorded
    assert all(len(v.votes) == 35 for v in votes)


REAL_PAGES = [
    # (fixture id, motion, classification, result)
    ("280095523_Senate_270", "PASSAGE TO BE ENGROSSED AS AMENDED", ["passage"], "fail"),
    ("280095523_House_250", "ACC MAJ OUGHT NOT TO PASS REP", [], "pass"),
    ("280095524_House_114", "Enactment", ["passage"], "pass"),
    ("280095733_Senate_651", "ENACTMENT", ["passage"], "pass"),
    ("280095959_House_97", "Final Passage - Con Res", ["passage"], "fail"),
    ("280096902_House_16", "Adoption", ["passage"], "pass"),
    ("280096598_Senate_642", "VETO OVERRIDE (2/3)", ["passage"], "fail"),
    (
        "280097251_House_586",
        "Reconsideration - Veto",
        ["passage"],
        "fail",
    ),  # 77-63, two thirds needed
    ("280095557_House_185", "ADOPT HAH-126 to CAS-44", ["amendment"], "fail"),
    ("280095829_House_4", "INDEF PP HAH-2 TO CAH-1", ["amendment"], "pass"),
    ("280095830_Senate_628", "INDEFINITELY POSTPONE", [], "pass"),
    ("280095566_Senate_963", "RECEDE AND CONCUR", [], "pass"),
]


@pytest.mark.parametrize("fid,motion,classification,result", REAL_PAGES)
def test_real_roll_call_pages(fid, motion, classification, result):
    paper, chamber, rc = fid.split("_")
    url = BASE + f"rollcall.asp?ID={paper}&chamber={chamber}&serialnumber={rc}"
    scraper = _scraper({url: _page(f"rollcall_{fid}.html")})
    (vote,) = list(scraper.scrape_vote(_bill(), motion, url))
    assert vote.motion_classification == classification
    assert vote.result == result
    assert vote.identifier == f"{chamber[0]}-RC {rc}"
    counts = {c["option"]: c["value"] for c in vote.counts}
    assert len(vote.votes) == counts["yes"] + counts["no"] + counts["other"]


# Every distinct motion text of the 1,057 session-132 roll calls (166 texts), with how many roll calls carry
# it and its label (empty = unlabelled), as listed in the OPEN-698 PR for review.
with open(os.path.join(FIXTURES, "motion_texts_132.json"), encoding="utf-8") as _f:
    ALL_TEXTS_132 = json.load(_f)


def test_inventory_is_the_whole_sample():
    assert len(ALL_TEXTS_132) == 166
    assert sum(t["roll_calls"] for t in ALL_TEXTS_132) == 1057


@pytest.mark.parametrize("text", ALL_TEXTS_132, ids=lambda t: t["motion"])
def test_every_session_132_text(text):
    expected = [text["label"]] if text["label"] else []
    assert vote_classification(text["motion"]) == expected
