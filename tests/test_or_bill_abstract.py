"""OPEN-928: Oregon's stored bill abstract carries no leftover markup and no superseded summary.

Oregon's MeasureSummary prints the current summary in <b>, and text a later version deleted as a bracketed italic span
"[<i>...</i>]". The scraper cut the "digest" part out with a regex that leaves the tail of its closing tags ("</b> </i>] ")
at the start, and kept every tag. 106 of the 304 stored 2026R1 abstracts had markup; SB 1507 also carried its deleted summary.

Fixtures (tests/fixtures/or_open928/stored_abstracts_2026R1.json): the abstracts exactly as stored on the replica on
2026-11-26 (note "summary"). SB 1507 and HB 4070 are the marked-up ones; HB 4074, HB 4119, HB 4157, SB 1566 were already clean;
HB 4040 has an upright bracket "[60] 65" (a deletion not printed in italic). The cleaner is run on them as stored (what the
digest regex leaves is part of the stored text). No test makes a live call.
"""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

# "or" is a Python keyword, so the Oregon package is imported by name
or_bills = importlib.import_module("or.bills")
clean_measure_summary = or_bills.clean_measure_summary

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "or_open928")
with open(
    os.path.join(FIXTURES, "stored_abstracts_2026R1.json"), encoding="utf-8"
) as f:
    STORED = json.load(f)

ALREADY_CLEAN = ["HB 4074", "HB 4119", "HB 4157", "SB 1566"]


def test_tags_are_stripped_and_leading_junk_removed_hb4070():
    stored = STORED["HB 4070"]
    assert stored.startswith("</b> </i>] ")
    out = clean_measure_summary(stored)
    assert out.startswith(
        "Requires the Oregon Health Authority and coordinated care organizations to ensure"
    )
    assert "<" not in out and ">" not in out
    # the bold part (inner <b>) is current text and stays, in order
    assert " terminology. Modifies the types of providers that may be reimbursed" in out
    assert out.endswith("Takes effect on the 91st day following adjournment sine die.")
    # nothing but the tags and the leading "] " is gone: every word is kept
    assert (
        out.split()
        == stored.replace("</b> </i>] ", "", 1)
        .replace("<b>", "")
        .replace("</b>", "")
        .split()
    )


def test_deleted_bracketed_italic_summary_is_dropped_sb1507():
    out = clean_measure_summary(STORED["SB 1507"])
    assert out.startswith(
        "Updates the connection date to the federal Internal Revenue Code"
    )
    # the superseded summary is gone ...
    assert "Reduces taxes" not in out
    assert "statewide retail sales tax" not in out
    assert "revenue lost to tax reductions" not in out
    # ... and the whole current summary stays
    for kept in (
        "Increases the amount of the earned income tax credit",
        "Disconnects from, and requires addback of amounts for, federal provisions",
        "Creates a personal income or corporate excise tax credit",
        "before January 1, 2032. Takes effect on the 91st day following adjournment sine die.",
    ):
        assert kept in out
    assert "<" not in out and "[" not in out and "]" not in out


def test_deleted_span_in_the_middle_of_a_sentence_is_dropped_and_bold_kept():
    out = clean_measure_summary(
        "Directs the [<i>committee</i>] <b>committees</b> to consult with certain "
        "[<i>state agencies and</i>] organizations."
    )
    assert out == "Directs the committees to consult with certain organizations."


def test_deleted_span_across_a_line_break_is_dropped():
    out = clean_measure_summary("Keeps this. [<i>Drops\nthis\ntext.</i>] Keeps that.")
    assert out == "Keeps this. Keeps that."


def test_each_deleted_span_ends_at_its_own_closing_mark():
    # two spans with current text between them: the text between must survive
    out = clean_measure_summary("A [<i>x</i>] KEEP [<i>y</i>] B")
    assert out == "A KEEP B"


def test_upright_bracket_is_not_a_deletion_mark_and_is_kept():
    out = clean_measure_summary(STORED["HB 4040"])
    assert "from 70 years of age to [60] 65 years of age" in out
    assert "<" not in out and "[<" not in out


def test_upright_bracket_at_the_very_start_is_kept():
    # only the stray closing "]" the digest cut leaves is removed, never an opening "["
    assert clean_measure_summary("[60] 65 years of age.") == "[60] 65 years of age."
    assert clean_measure_summary("</b> </i>] [60] 65 years.") == "[60] 65 years."


def test_italic_tags_without_brackets_are_only_stripped():
    assert (
        clean_measure_summary("One <i>two</i> <b>three</b> four")
        == "One two three four"
    )


def test_already_clean_abstracts_are_byte_identical():
    for ident in ALREADY_CLEAN:
        assert clean_measure_summary(STORED[ident]) == STORED[ident], ident


def test_scraper_stores_the_cleaned_abstract_after_the_digest_cut(monkeypatch):
    measure = {
        "MeasurePrefix": "HB",
        "MeasureNumber": 4070,
        "RelatingTo": "Behavioral health",
        "MeasureSummary": "Short digest (Flesch Readability Score: 70.9)."
        + STORED["HB 4070"],
        "MeasureSponsors": [],
        "MeasureDocuments": [],
        "CommitteeAgendaItems": [],
        "MeasureHistoryActions": [],
    }

    class Client:
        def get(self, name, **kwargs):
            return [measure] if name == "measures" else []

    monkeypatch.setattr(or_bills, "index_legislators", lambda s, k: {})
    scraper = or_bills.ORBillScraper(jurisdiction="x", datadir="/tmp")
    scraper.api_client = Client()
    bills = list(scraper.scrape_bills("2026R1"))
    assert len(bills) == 1
    abstracts = bills[0].abstracts
    assert [a["note"] for a in abstracts] == ["summary"]
    assert abstracts[0]["abstract"] == clean_measure_summary(STORED["HB 4070"])
    assert abstracts[0]["abstract"].startswith("Requires the Oregon Health Authority")
