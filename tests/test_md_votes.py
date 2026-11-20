"""Tests for OPEN-700: Maryland roll calls are classified from their motion, not all passage.

The fixtures are real roll-call PDFs of 2026RS, 2025S1 and 2026S1
(mgaleg.maryland.gov/<session>/votes/house|senate/<seq>.pdf, read 2026-11-20) as pdftotext -layout
gives them, which is what convert_pdf(type="text") returns. They are run through the votes scraper's
own scrape_vote() and the bills scraper's own parse_vote_pdf(). The expected labels, bills and tallies
below were read off the PDFs by hand.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
import md.bills  # noqa: E402
import md.votes  # noqa: E402
from md.bills import MDBillScraper  # noqa: E402
from md.votes import MDVoteScraper, vote_classification  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "md_open700")


def _fixture_text(url):
    # ".../2026RS/votes/senate/0740.pdf" -> "2026rs_senate_0740.txt"
    session, _, chamber, seq = url.lower().rsplit("/", 4)[-4:]
    name = f"{session}_{chamber}_{seq.replace('.pdf', '.txt')}"
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


@pytest.fixture(autouse=True)
def offline_pdfs(monkeypatch):
    def convert_pdf(filename, type="xml"):
        assert type == "text"
        return _fixture_text(filename)

    monkeypatch.setattr(md.votes, "convert_pdf", convert_pdf)
    monkeypatch.setattr(md.bills, "convert_pdf", convert_pdf)


class _Votes(MDVoteScraper):
    def __init__(self):
        self.warnings = []

    def urlretrieve(self, url):
        return url, None

    def warning(self, msg, *args):
        self.warnings.append(msg)


class _Bills(MDBillScraper):
    def __init__(self):
        pass

    def urlretrieve(self, url):
        return url, None

    def warning(self, msg, *args):
        pass


def scrape_vote(session, chamber, seq):
    url = f"https://mgaleg.maryland.gov/{session}/votes/{chamber}/{seq}.pdf"
    v = _Votes().scrape_vote(url, "2026")
    if v is None:
        return None
    d = v.as_dict()
    d["bill"] = v.bill_identifier
    return d


def parse_vote_pdf(session, chamber, seq):
    url = f"https://mgaleg.maryland.gov/{session}/votes/{chamber.title()}/{seq}.pdf"
    bill = Bill("HB 1", "2026", "x", chamber="lower")
    return _Bills().parse_vote_pdf(url, bill).as_dict()


def _counts(v):
    return {c["option"]: c["value"] for c in v["counts"]}


# (session, chamber, seq, bill, label, yes, no) through the votes scraper, the registered one.
VOTES_SCRAPER = [
    # third reading, every tag: passage (lost ones too)
    ("2026RS", "house", "0076", "HB 3", ["passage"], 135, 0),
    (
        "2026RS",
        "house",
        "0950",
        "SB 283",
        ["passage"],
        123,
        13,
    ),  # "On Third Reading (Amend)"
    (
        "2026RS",
        "house",
        "0953",
        "SB 283",
        ["passage"],
        120,
        10,
    ),  # "(Reconsidered) (Amend)"
    ("2026RS", "house", "0890", "HB 336", ["passage"], 125, 10),  # "(Rules Suspended)"
    ("2026RS", "senate", "0058", "SB 1", ["passage"], 31, 13),
    ("2026RS", "senate", "0415", "SB 282", ["passage"], 40, 6),
    # the House's one roll call after concurring / receding: passage
    ("2026RS", "house", "1473", "HB 3", ["passage"], 136, 0),  # "(Hse concurred)"
    ("2026RS", "house", "1234", "SB 334", ["passage"], 91, 40),  # "(Hse Receded)"
    # Senate: CCR adoption then its own final passage roll call -> only the final one counts
    ("2026RS", "senate", "0740", "SB 282", [], 38, 6),
    ("2026RS", "senate", "0741", "SB 282", ["passage"], 38, 6),
    # Senate third-reading consent calendar: the motion line is the list of bills
    ("2026RS", "senate", "0251", "SB 72", ["passage"], 42, 0),
    # amendment votes
    (
        "2026RS",
        "house",
        "0025",
        "HB 488",
        ["amendment"],
        39,
        98,
    ),  # "FLA Del. Buckel /613520/1"
    (
        "2026RS",
        "house",
        "0938",
        "SB 283",
        ["amendment"],
        97,
        35,
    ),  # "Committee Amendment #69"
    (
        "2026RS",
        "senate",
        "0399",
        "SB 282",
        ["amendment"],
        13,
        31,
    ),  # "Floor Amendment Corderman ..."
    (
        "2026RS",
        "senate",
        "1265",
        "HB 1222",
        ["amendment"],
        22,
        22,
    ),  # "Favorable with 3 amendments /513122/1"
    ("2026S1", "house", "1748", "HB 2100", ["amendment"], 33, 96),
    # procedure and second reading: unlabelled
    ("2026RS", "house", "0058", "HB 1", [], 37, 100),  # "Motion to Recommit"
    (
        "2026RS",
        "house",
        "0889",
        "HB 336",
        [],
        129,
        2,
    ),  # rules suspension, 2 readings in 1 day
    ("2026RS", "house", "1717", "SB 255", [], 90, 37),  # "Previous Question"
    ("2026RS", "house", "1052", "SB 323", [], 88, 37),  # "FLA ... Motion to Lay Over"
    (
        "2026S1",
        "house",
        "1742",
        "HB 2100",
        [],
        96,
        36,
    ),  # "FLA ... Ruled out of order Decision of the Chair"
    (
        "2026RS",
        "senate",
        "1083",
        "SB 791",
        [],
        28,
        15,
    ),  # adoption of the favorable report (2nd reading)
    ("2026RS", "senate", "0546", "SB 626", [], 20, 21),  # "Motion to postpone"
]


@pytest.mark.parametrize("session,chamber,seq,bill,label,yes,no", VOTES_SCRAPER)
def test_votes_scraper_labels_real_roll_calls(
    session, chamber, seq, bill, label, yes, no
):
    v = scrape_vote(session, chamber, seq)
    assert v["motion_classification"] == label, v["motion_text"]
    assert v["bill"] == bill
    assert (_counts(v)["yes"], _counts(v)["no"]) == (yes, no)
    assert v["result"] == ("pass" if yes > no else "fail")


def test_votes_scraper_skips_a_quorum_call():
    assert scrape_vote("2026RS", "house", "0003") is None


# The same rules through the bills scraper's PDF parser (parse_vote_pdf, not called by the bills
# scraper today). It reads the motion from a different line, so it is tested on roll calls where it
# reads the right one.
BILLS_PARSER = [
    ("2026RS", "house", "0076", "On Third Reading", ["passage"]),
    (
        "2026RS",
        "house",
        "1473",
        "On Third Reading and Final Passage (Hse concurred)",
        ["passage"],
    ),
    ("2026RS", "senate", "0740", "Conference Committee Report - Adoption", []),
    (
        "2026RS",
        "senate",
        "0741",
        "Bill is on Third Reading for Final Passage.",
        ["passage"],
    ),
    ("2026RS", "senate", "0399", "Floor Amendment Corderman /133129/1", ["amendment"]),
    ("2026RS", "house", "0938", "Committee Amendment #69", ["amendment"]),
    ("2026RS", "senate", "0546", "Motion to postpone", []),
    (
        "2025S1",
        "senate",
        "0005",
        "Shall the Bill pass notwithstanding the objections of the",
        ["passage"],
    ),
]


@pytest.mark.parametrize("session,chamber,seq,motion,label", BILLS_PARSER)
def test_bills_pdf_parser_uses_the_same_rules(session, chamber, seq, motion, label):
    v = parse_vote_pdf(session, chamber, seq)
    assert v["motion_text"] == motion
    assert v["motion_classification"] == label


def test_bills_html_parser_uses_the_same_rules(monkeypatch):
    # parse_vote_page reads the old HTML vote pages; a minimal page in its shape, with real motions
    page = (
        "<html><body><table><tr><td>Legislative Date: Mar 23, 2009</td></tr>"
        '<tr><td colspan="23">{motion}</td></tr>'
        '<tr><td class="t">Totals</td><td class="t">Yeas 100</td><td class="t">Nays 30</td>'
        '<td class="t">Not Voting 1</td><td class="t">Excused 0</td><td class="t">Absent 0</td></tr>'
        "</table></body></html>"
    )

    class Resp:
        def __init__(self, text):
            self.text = text

    # parse_vote_page records "Not Voting" and "Excused" with vote.other, which VoteEvent no
    # longer has (a finding of OPEN-700: the old HTML parser cannot run as it stands)
    monkeypatch.setattr(
        VoteEvent, "other", lambda self, name: self.vote("other", name), raising=False
    )

    for motion, label in [
        ("On Third Reading", ["passage"]),
        ("FLA Del. Buckel /613520/1", ["amendment"]),
        ("Motion to Recommit", []),
    ]:
        scraper = _Bills()
        monkeypatch.setattr(
            scraper,
            "get",
            lambda url, m=motion: Resp(page.format(motion=m)),
            raising=False,
        )
        bill = Bill("HB 1", "2009", "x", chamber="lower")
        v = scraper.parse_vote_page("house/0001.htm", bill).as_dict()
        assert v["motion_classification"] == label, motion


# Every distinct motion text of 2026RS, 2025S1 and 2026S1 that the parsers emit, numbers kept
# as seen, and its label.
@pytest.mark.parametrize(
    "motion,label",
    [
        ("On Third Reading", ["passage"]),
        ("On Third Reading                                     (Amend)", ["passage"]),
        ("On Third Reading                                     (Emerg)", ["passage"]),
        ("On Third Reading                                     (Const)", ["passage"]),
        (
            "On Third Reading                                     (Emerg/Amend)",
            ["passage"],
        ),
        (
            "On Third Reading                                     (Const/Amend)",
            ["passage"],
        ),
        ("ON THIRD READING (Rules Suspended)", ["passage"]),
        ("On Third Reading and Final Passage (Hse concurred)", ["passage"]),
        ("On Third Reading and Final Passage (CCR Adp)", ["passage"]),
        ("On Third Reading and Final Passage (Hse Receded)", ["passage"]),
        ("Bill is on Third Reading for Final Passage.", ["passage"]),
        ("Bill is on Third Reading for Final Passage. (Emerg/Amend)", ["passage"]),
        ("The bill is on third reading for final passage.", ["passage"]),
        ("Bill on third reading for final passage.", ["passage"]),
        ("HB 1006    HB 1013    HB 1076", ["passage"]),
        (
            "SB 72     SB 398    SB 399    SB 400    SB 414   SB 442      SB 684",
            ["passage"],
        ),
        (
            "Shall the Bill pass notwithstanding the objections of the Chief Executive?",
            ["passage"],
        ),
        ("Conference Committee Report - Adoption", []),
        # 2025RS Senate SB 338, followed by its own final passage roll call like 2026's
        ("Question is on the adoption of the Conference Committee Report.", []),
        ("Favorable with amendments adp - ON 2ND RDG", []),
        ("Favorable adp - ON 2ND RDG", []),
        ("Question is on the adoption of the favorable report, as amended.", []),
        ("Motion to Special Order", []),
        ("Motion To Special Order by Senator Ready", []),
        ("Motion to Recommit", []),
        ("Previous Question", []),
        ("Motion to limit debate", []),
        ("Motion to postpone", []),
        ("Motion to suspend rules and allow 2 Rdgs on 1 Day", []),
        ("Motion to Suspend Rules from 1st to 2nd Rdg  (Const)", []),
        ("Suspended Rule 39 to allow two readings of a bill in the same day", []),
        ("Shall the Bill be Introduced?", []),
        ("FLA Del. Buckel /613520/1", ["amendment"]),
        ("FLA Del. Morgan, M. /283424/1", ["amendment"]),
        ("Floor Amendment Ready /393120/1", ["amendment"]),
        ("Committee Amendments", ["amendment"]),
        ("committee amendment #3", ["amendment"]),
        ("Favorable with 3 amendments /513122/1", ["amendment"]),
        (
            "FLA Del. Buckel /133323/1           Ruled out of order    Decision of the Chair",
            [],
        ),
        ("FLA Del. Buckel /393423/1    Motion to Lay Over    Motion to Not Allow", []),
        ("No motion given", []),
    ],
)
def test_md_vote_classification(motion, label):
    assert vote_classification(motion) == label


def test_md_yaml_block_decides_passage_only():
    # amendment labels are the scraper's; the yaml block never returns them
    assert classify_motion("md", "FLA Del. Buckel /613520/1") == []
    assert classify_motion("md", "On Third Reading") == ["passage"]
    # a resolution's or a joint resolution's number list is a consent calendar too
    assert classify_motion("md", "HJ 1  SJ 2") == ["passage"]
    # no line-item override was seen; one names an item, not the bill, and stays unlabelled
    assert (
        classify_motion(
            "md",
            "Shall the Item pass notwithstanding the objections of the Chief Executive?",
        )
        == []
    )
    # a bill number inside a longer line is not a consent calendar
    assert classify_motion("md", "HB 139 CCR") == []
