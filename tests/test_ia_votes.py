"""Tests for OPEN-699: Iowa's journal roll calls are classified from their question, not all passage.

The fixtures are cut from real House and Senate journals of 2025-2026
(legis.iowa.gov/docs/publications/HJNL|SJNL/<yyyymmdd>_HJNL|SJNL.pdf, read 2026-11-20) as pdftotext -layout
gives them, which is what convert_pdf(type="text") returns. They are run through the scraper's own
scrape_journal(). The expected labels, tallies and outcomes below were read off the journal text by hand.
"""

import logging
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
import ia.votes  # noqa: E402
from ia.votes import IAVoteScraper, vote_classification  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open699")

# Every distinct question the scraper read from the 290 journals of 2025 and 2026 (1,411 roll calls), with its
# count and label. Amendment numbers vary; one real example of each form is listed.
REAL_MOTIONS = [
    ("Shall the bill pass?", ["passage"]),  # 643 House, 533 Senate
    (
        "Shall the resolution be adopted?",
        ["passage"],
    ),  # 2 House (HR 3, SCR 101), 5 Senate (SJR 9, SR 105)
    (
        "Shall the joint resolution be adopted and agreed to?",
        ["passage"],
    ),  # 2 House (SJR 9, SJR 11)
    ("Shall amendment H-1011 be adopted?", ["amendment"]),  # 73 House, 30 Senate
    ("Shall amendment S-3077 be adopted", ["amendment"]),  # 10 Senate (no closing "?")
    ("Shall amendment H-8096B be adopted?", ["amendment"]),
    ("Shall amendment H-8442, to amendment H-8439, be adopted?", ["amendment"]),  # 25
    ("Shall amendment S-3165 to amendment S-3064 be adopted?", ["amendment"]),  # 6
    ("Shall amendment S-3033 to House amendment S-3030 be adopted?", ["amendment"]),
    (
        "Shall amendment H-8010, to the committee amendment H-8004, be adopted?",
        ["amendment"],
    ),
    ("Shall amendment H-8439, as amended, be adopted?", ["amendment"]),  # 6
    ("Shall the rules be suspended to consider amendment H-8313?", ["amendment"]),  # 49
    (
        "Shall the rules be suspended to consider amendment H-8149, to amendment H-8128?",
        ["amendment"],
    ),  # 12
    (
        "Shall the rules be suspended to consider amendment H-1037, as amended?",
        ["amendment"],
    ),
    (
        "Shall the rules be suspended to consider amendment H-8350, to Senate amendment H-8319?",
        ["amendment"],
    ),
    (
        "Shall the rules be suspended to consider amendment H-8386, to the Senate amendment H-8335?",
        ["amendment"],
    ),
    (
        "Shall the rules be suspended to consider amendment H-8397, to the committee amendment H-8394?",
        ["amendment"],
    ),
    ("Shall the House concur in the Senate amendment H-8459?", ["amendment"]),  # 3
    ("Shall the motion to concur be adopted?", ["amendment"]),  # 2 Senate
    (
        "Shall the motion to concur be adopted",
        ["amendment"],
    ),  # 1 Senate (no closing "?")
    ("Shall the bill be moved to the Unfinished Business Calendar?", []),  # 1 Senate
]


@pytest.mark.parametrize("motion,expected", REAL_MOTIONS)
def test_real_motions(motion, expected):
    assert vote_classification(motion) == expected


@pytest.mark.parametrize(
    "motion",
    [
        "Shall the bill pass? #2",  # the scraper's own numbering of a repeat; classified before it is added
        "Shall House File 2542 be deferred?",  # House 2026-03-04 (no bill number after it: not scraped)
        "Shall the motion to reconsider be adopted?",
    ],
)
def test_unseen_or_procedural_texts_are_not_passage(motion):
    """Only the questions seen in the journals are passage; anything else stays unclassified. No veto
    override roll call is in the 2025-2026 journals, so its wording is not guessed here (listed for Ramon)."""
    assert classify_motion("ia", motion) == []


def scrape(name, chamber, monkeypatch):
    path = os.path.join(FIXTURES, name)
    with open(path, "rb") as f:
        text = f.read()
    monkeypatch.setattr(ia.votes, "convert_pdf", lambda filename, type: text)
    scraper = IAVoteScraper.__new__(IAVoteScraper)
    scraper.urlretrieve = lambda url: (path, None)
    scraper.warning = scraper.error = lambda *a, **k: None
    scraper.logger = logging.getLogger("test_ia_votes")
    out = []
    for vote in scraper.scrape_journal(
        "https://www.legis.iowa.gov/x.pdf", chamber, "2025-2026", datetime(2026, 1, 1)
    ):
        counts = {c["option"]: c["value"] for c in vote.counts}
        out.append(
            (
                vote.bill.split('"identifier": "')[1].split('"')[0],
                vote.motion_text,
                vote.motion_classification,
                vote.result,
                counts["yes"],
                counts["no"],
            )
        )
    return out


JOURNALS = [
    # House 2025-02-13: House Resolution 3, "The motion prevailed and the resolution was adopted."
    (
        "house_20250213_hr3.txt",
        "lower",
        [("HR 3", "Shall the resolution be adopted?", ["passage"], "pass", 76, 10)],
    ),
    # House 2025-04-17: Senate Joint Resolution 9 "declared to have been adopted and agreed to by the House."
    (
        "house_20250417_sjr9.txt",
        "lower",
        [
            (
                "SJR 9",
                "Shall the joint resolution be adopted and agreed to?",
                ["passage"],
                "pass",
                87,
                6,
            )
        ],
    ),
    # House 2026-03-23, SF 572: "The motion to suspend the rules lost."
    (
        "house_20260323_sf572_suspend.txt",
        "lower",
        [
            (
                "SF 572",
                "Shall the rules be suspended to consider amendment H-8251?",
                ["amendment"],
                "fail",
                28,
                62,
            )
        ],
    ),
    # House 2026-04-30, HF 2783: four amendments to amendment H-8439, each "lost."
    (
        "house_20260430_hf2783_amendments.txt",
        "lower",
        [
            (
                "HF 2783",
                f"Shall amendment {n}, to amendment H-8439, be adopted?",
                ["amendment"],
                "fail",
                yes,
                no,
            )
            for n, yes, no in (
                ("H-8442", 26, 59),
                ("H-8443", 26, 59),
                ("H-8444", 25, 60),
                ("H-8446", 30, 55),
            )
        ],
    ),
    # House 2026-05-02, HF 1003: the House concurs in Senate amendment H-8459, then passes the bill as amended.
    (
        "house_20260502_hf1003_concur.txt",
        "lower",
        [
            (
                "HF 1003",
                "Shall the House concur in the Senate amendment H-8459?",
                ["amendment"],
                "pass",
                57,
                28,
            ),
            ("HF 1003", "Shall the bill pass?", ["passage"], "pass", 85, 0),
        ],
    ),
    # Senate 2025-03-19: amendment S-3032 lost, four bills passed, SJR 9 adopted.
    (
        "senate_20250319_sf459_sjr9.txt",
        "upper",
        [
            (
                "SF 459",
                "Shall amendment S-3032 be adopted?",
                ["amendment"],
                "fail",
                13,
                34,
            ),
            ("SF 459", "Shall the bill pass?", ["passage"], "pass", 34, 13),
            ("SF 513", "Shall the bill pass?", ["passage"], "pass", 43, 4),
            ("SF 521", "Shall the bill pass?", ["passage"], "pass", 47, 0),
            ("SF 573", "Shall the bill pass?", ["passage"], "pass", 47, 0),
            ("SJR 9", "Shall the resolution be adopted?", ["passage"], "pass", 47, 0),
        ],
    ),
    # Senate 2025-04-07, HF 954: the question's closing quote is missing in the journal.
    (
        "senate_20250407_hf954.txt",
        "upper",
        [
            (
                "HF 954",
                "Shall amendment S-3077 be adopted",
                ["amendment"],
                "fail",
                13,
                34,
            ),
            ("HF 954", "Shall the bill pass?", ["passage"], "pass", 32, 15),
        ],
    ),
    # Senate 2026-03-24, SF 2464: a calendar move, "The motion passed".
    (
        "senate_20260324_sf2464_unfinished.txt",
        "upper",
        [
            (
                "SF 2464",
                "Shall the bill be moved to the Unfinished Business Calendar?",
                [],
                "pass",
                31,
                15,
            )
        ],
    ),
    # Senate 2026-04-14, HF 2591: the Senate concurs in the House amendment, then passes the bill.
    (
        "senate_20260414_hf2591_concur.txt",
        "upper",
        [
            (
                "HF 2591",
                "Shall the motion to concur be adopted?",
                ["amendment"],
                "pass",
                35,
                12,
            ),
            ("HF 2591", "Shall the bill pass?", ["passage"], "pass", 43, 4),
        ],
    ),
]


@pytest.mark.parametrize("name,chamber,expected", JOURNALS)
def test_real_journals(name, chamber, expected, monkeypatch):
    assert scrape(name, chamber, monkeypatch) == expected
