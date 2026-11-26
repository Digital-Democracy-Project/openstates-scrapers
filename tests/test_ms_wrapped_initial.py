"""OPEN-899: a Mississippi Senate roll call line that breaks right after a member's first
initial keeps the member's name whole.

Two Senators share the surname Simmons, so the Senate roll call prints "Simmons D. T. (12th)"
and "Simmons S. (13th)". PDF text wraps the long name: "... Rhodes, Simmons D." ends one line
and "T. (12th), Simmons S. (13th), ..." starts the next. The line-joiner treated the "." after
"D" as the end of a sentence, so the scraper stored two voters, "Simmons D" (matched to the
Senator by an existing people alias) and "T. (12th)" (matched to nobody), and counted one yes
vote too many.

The fixtures are the text (pdftotext -layout, as the scraper's convert_pdf runs it) of the three
2026 Senate roll calls where "T. (12th)" was left unmatched (billstatus.ls.state.ms.us/2026/pdf/
votes/senate/0300012.pdf SB 2838 passage, 0440002.pdf HB 515 passage, 0860005.pdf HB 1330
conference report, read 2026-11-26). The expected name and totals are read from the printed
text, not from the scraper.
"""
import os
import re
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

import ms.bills  # noqa: E402
from ms.bills import MSBillScraper, _combine_lines  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ms_open899")

ROLL_CALLS = [
    ("2026_senate_0300012.txt", "SB 2838", "Passed"),
    ("2026_senate_0440002.txt", "HB 515", "Passed"),
    ("2026_senate_0860005.txt", "HB 1330", "Conference Report Adopted"),
]


def scrape(monkeypatch, tmp_path, fixture, action):
    text = open(os.path.join(FIXTURES, fixture), "rb").read()
    scraper = MSBillScraper.__new__(MSBillScraper)

    def urlretrieve(url, verify=False):
        path = tmp_path / "vote.pdf"
        path.write_bytes(b"")
        return str(path), None

    monkeypatch.setattr(scraper, "urlretrieve", urlretrieve, raising=False)
    monkeypatch.setattr(ms.bills, "convert_pdf", lambda path, kind: text)
    bill = Bill("SB 1", legislative_session="2026", chamber="upper", title="t")
    votes = list(
        scraper.scrape_votes(
            "http://billstatus.ls.state.ms.us/x.pdf",
            action,
            datetime(2026, 1, 1),
            "upper",
            bill,
            False,
        )
    )
    assert len(votes) == 1
    return votes[0], text.decode()


@pytest.mark.parametrize("fixture,bill,action", ROLL_CALLS)
def test_wrapped_member_name_is_one_voter(monkeypatch, tmp_path, fixture, bill, action):
    vote, text = scrape(monkeypatch, tmp_path, fixture, action)
    names = [v["voter_name"] for v in vote.votes]
    # the member's name as the legislature prints it (the line break is the PDF's)
    assert "Simmons D. T. (12th)" in re.sub(r"\s+", " ", text)
    assert "Simmons D. T. (12th)" in names
    assert "T. (12th)" not in names
    assert "Simmons D" not in names
    # the yes list names every printed Yea once: the count the legislature prints is the
    # number of names, and one wrapped name is one name
    flat = " ".join(text.split())
    yeas = re.search(r"Yeas--(.*?)\.? ?Nays--", flat).group(1).split(",")
    counts = {c["option"]: c["value"] for c in vote.counts}
    assert counts["yes"] == len(yeas)
    assert len([v for v in vote.votes if v["option"] == "yes"]) == len(yeas)
    totals = re.search(r"Yeas--.*?Total-+ ?(\d+)", flat)
    assert counts["yes"] == int(totals.group(1))


def test_a_line_ending_in_an_initial_joins_the_next():
    assert _combine_lines(["Rhodes, Simmons D.", "T. (12th), Sparks,"]) == [
        "Rhodes, Simmons D. T. (12th), Sparks,"
    ]


def test_ordinary_line_ends_still_split():
    # a closing period after a whole name, a total, a colon or a comma ends the line
    for first in ("Younger.", "Total--47.", "by the following vote:", "Rhodes,"):
        assert _combine_lines([first, "Next"]) == [first, "Next"]
