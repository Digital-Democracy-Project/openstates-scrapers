"""Tests for OPEN-807: Mississippi's "Current version" no longer hides the stage-named text it duplicates.

A bill's history XML (billstatus.ls.state.ms.us/<session>/pdf/history/<HB|SB>/<bill>.xml) names its texts
under INTRO_OTHER, CMTESUB_OTHER, PASSED_OTHER and ASG_OTHER, and CURRENT_OTHER repeats the newest one's file
(HB 1001: IN, HB 2: PS, HB 1: SG). The fixtures are those real files, read 2026-11-23, run through the
scraper's own scrape_bills() offline.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from ms.bills import MSBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

ALLMSRS = b"""<?xml version="1.0" encoding="ISO-8859-1"?>
<LASTACTION><MSRGROUP><MEASURE>%s</MEASURE><MEASURELINK>x</MEASURELINK>
<ACTIONLINK>../history/x.xml</ACTIONLINK></MSRGROUP></LASTACTION>"""


class FakeResponse:
    def __init__(self, content):
        self.content = content


def scrape_bill(monkeypatch, history_path, measure, chamber):
    """The Bill scrape_bills() makes from one real history XML (its roll calls are not read)."""
    scraper = MSBillScraper.__new__(MSBillScraper)
    history = open(history_path, "rb").read()

    def get(url, verify=False):
        return FakeResponse(ALLMSRS % measure if "all_measures" in url else history)

    monkeypatch.setattr(scraper, "get", get, raising=False)
    monkeypatch.setattr(
        scraper, "scrape_votes", lambda *a, **k: iter(()), raising=False
    )
    (bill,) = [o for o in scraper.scrape_bills(chamber, "2026") if isinstance(o, Bill)]
    return bill


def versions(bill):
    return {
        v["note"]: sorted(link["url"].rsplit("/", 1)[1] for link in v["links"])
        for v in bill.versions
    }


@pytest.mark.parametrize(
    "fixture,measure,chamber,expected",
    [
        # died in committee: its only text is the introduced one
        (
            "ms_open807/HB1001_2026_history.xml",
            b"HB1001",
            "lower",
            {"As Introduced": ["HB1001IN.htm", "HB1001IN.pdf"]},
        ),
        # committee substitute, passed the House, died in the Senate: Current = PS
        (
            "ms_open807/HB0002_2026_history.xml",
            b"HB2",
            "lower",
            {
                "As Introduced": ["HB0002IN.htm", "HB0002IN.pdf"],
                "Committee Substitute": ["HB0002CS.htm", "HB0002CS.pdf"],
                "As Passed the lower": ["HB0002PS.htm", "HB0002PS.pdf"],
                "Amendment No 1 (Cmte Sub) (Adopted) (Voice Vote)": [
                    "HB0002_H_(Cmte_Sub)_Amend_01.htm",
                    "HB0002_H_(Cmte_Sub)_Amend_01.pdf",
                ],
            },
        ),
        # signed by the Governor: Current = SG
        (
            "ms_open807/HB0001_2026_history.xml",
            b"HB1",
            "lower",
            {
                "As Introduced": ["HB0001IN.htm", "HB0001IN.pdf"],
                "As Passed the lower": ["HB0001PS.htm", "HB0001PS.pdf"],
                "Approved by the Governor": ["HB0001SG.htm", "HB0001SG.pdf"],
                "Amendment No 1 (Adopted) (Voice Vote)": [
                    "HB0001_H_Amend_01.htm",
                    "HB0001_H_Amend_01.pdf",
                ],
            },
        ),
        (
            "ms_open807/SB2001_2026_history.xml",
            b"SB2001",
            "upper",
            {
                "As Introduced": ["SB2001IN.htm", "SB2001IN.pdf"],
                "As Passed the upper": ["SB2001PS.htm", "SB2001PS.pdf"],
            },
        ),
    ],
)
def test_current_version_keeps_the_stage_name(
    monkeypatch, fixture, measure, chamber, expected
):
    bill = scrape_bill(monkeypatch, os.path.join(FIXTURES, fixture), measure, chamber)
    got = versions(bill)
    # HB 2 has more adopted amendments than the one checked here; the texts are what matter
    texts = {note: urls for note, urls in got.items() if "Amendment" not in note}
    assert texts == {n: u for n, u in expected.items() if "Amendment" not in n}
    for note, urls in expected.items():
        assert got[note] == urls
    assert "Current version" not in got


def test_current_version_that_names_no_listed_text_is_kept(monkeypatch, tmp_path):
    # Not seen in 2026 or 20261E; if the site ever lists a current text under no stage field, it stays
    # (visible, with no stage) rather than being dropped.
    history = open(
        os.path.join(FIXTURES, "ms_open807/HB1001_2026_history.xml"), "rb"
    ).read()
    history = history.replace(
        b"<CURRENT_OTHER>../../../../documents/2026/html/HB/1000-1099/HB1001IN.htm",
        b"<CURRENT_OTHER>../../../../documents/2026/html/HB/1000-1099/HB1001XX.htm",
    )
    path = tmp_path / "history.xml"
    path.write_bytes(history)
    got = versions(scrape_bill(monkeypatch, str(path), b"HB1001", "lower"))
    assert got == {
        "As Introduced": ["HB1001IN.htm", "HB1001IN.pdf"],
        "Current version": ["HB1001XX.htm", "HB1001XX.pdf"],
    }
