"""OPEN-760: every Kentucky roll call keeps its own identity at the import (North Dakota's OPEN-757 pattern).

North Dakota's first load stopped on two roll calls with the same motion text, chamber and minute: with no `dedupe_key`
the vote importer (openstates-core `vote_events.py`, `get_object()`) matches on session + bill + motion text + start
date + organization. Each page of a Kentucky vote_history.pdf is one roll call whose roll-call line ends with the
chamber's own number (House "RCS# 423", Senate "RSN# 3792"). House numbers restart every session (RCS# 155 is in both
25RS HB 4 and 26RS HB 500), so the key is the PDF's address (record/<session>/<bill>/vote_history.pdf) plus that number.

No two roll calls in the saved PDFs share a motion text and time (42 roll calls, times to the second), so the colliding
pair below is built from 26RS SB 1's real first page: a copy with its own number (RSN# 3793) and tally. A page printed
twice word for word is one roll call and is kept once.

The fixtures are apps.legislature.ky.gov's own vote_history.pdf files (tests/fixtures/ky_open688, ky_open689).
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from openstates.utils import convert_pdf  # noqa: E402
import ky.bills as ky_bills  # noqa: E402
from ky.bills import KYBillScraper  # noqa: E402

HERE = os.path.dirname(__file__)
SB1_2026 = os.path.join(HERE, "fixtures", "ky_open688", "26RS_sb1_vote_history.pdf")
HB4_2025 = os.path.join(HERE, "fixtures", "ky_open689", "25RS_hb4_vote_history.pdf")
HB500_2026 = os.path.join(HERE, "fixtures", "ky_open689", "26RS_hb500_vote_history.pdf")
RECORD = "https://apps.legislature.ky.gov/record/"


def scraped(pdf_text, url, tmp_path, monkeypatch):
    """scrape_votes() over one PDF's text, as convert_pdf gives it (pages split by form feeds)."""
    monkeypatch.setattr(ky_bills, "convert_pdf", lambda filename, type: pdf_text)
    monkeypatch.setattr(ky_bills.os, "remove", lambda filename: None)
    scraper = KYBillScraper({"name": "Kentucky"}, str(tmp_path))
    scraper.urlretrieve = lambda url, verify=None: ("unused.pdf", None)
    bill = Bill("X 1", legislative_session="2026RS", chamber="upper", title="t")
    return list(scraper.scrape_votes(url, bill, "upper"))


def pages(pdf):
    return convert_pdf(pdf, "text").split(b"\x0c")


def import_match_key(vote):
    """What the importer matches a vote on: its dedupe_key alone when it has one, otherwise session + bill + motion
    text + start date + organization (Kentucky's votes have no identifier)."""
    return getattr(vote, "dedupe_key", None) or (
        vote.legislative_session,
        str(vote.bill),
        vote.motion_text,
        str(vote.start_date),
        str(vote.organization),
    )


def test_each_roll_call_is_keyed_on_its_pdf_and_printed_number(tmp_path, monkeypatch):
    url = RECORD + "26rs/sb1/vote_history.pdf"
    votes = scraped(convert_pdf(SB1_2026, "text"), url, tmp_path, monkeypatch)
    assert [(v.dedupe_key, v.motion_text) for v in votes] == [
        (url + "#RSN3792", "PASS SB 1"),
        (url + "#RCS423", "Pass"),
        (url + "#RSN4120", "FINAL PASSAGE OF SB 1 w/ HFA 2"),
        (url + "#RSN4145", "OVERRIDE VETO FINAL PASSAGE SB 1"),
        (url + "#RCS475", "Veto Override"),
    ]


def test_house_numbers_that_restart_each_session_stay_apart(tmp_path, monkeypatch):
    hb4 = scraped(
        convert_pdf(HB4_2025, "text"),
        RECORD + "25rs/hb4/vote_history.pdf",
        tmp_path,
        monkeypatch,
    )
    hb500 = scraped(
        convert_pdf(HB500_2026, "text"),
        RECORD + "26rs/hb500/vote_history.pdf",
        tmp_path,
        monkeypatch,
    )
    both = [v.dedupe_key for v in hb4 + hb500]
    assert RECORD + "25rs/hb4/vote_history.pdf#RCS155" in both
    assert RECORD + "26rs/hb500/vote_history.pdf#RCS155" in both
    assert len(both) == len(set(both)) == 9 + 13


def test_two_roll_calls_with_the_same_motion_and_time_get_their_own_keys(
    tmp_path, monkeypatch
):
    first = pages(SB1_2026)[0]
    second = first.replace(b"RSN# 3792", b"RSN# 3793").replace(
        b"YEAS:   29", b"YEAS:   28"
    )
    url = RECORD + "26rs/sb1/vote_history.pdf"
    votes = scraped(b"\x0c".join([first, second]), url, tmp_path, monkeypatch)
    assert len(votes) == 2
    a, b = votes
    # without a key the importer would take the second for the first
    assert (a.motion_text, str(a.start_date), str(a.organization)) == (
        b.motion_text,
        str(b.start_date),
        str(b.organization),
    )
    assert [a.dedupe_key, b.dedupe_key] == [url + "#RSN3792", url + "#RSN3793"]
    assert [c["value"] for c in a.counts][0] == 29
    assert [c["value"] for c in b.counts][0] == 28
    keys = collections.Counter(import_match_key(v) for v in votes)
    assert [k for k, n in keys.items() if n > 1] == []


def test_a_page_printed_twice_is_kept_once(tmp_path, monkeypatch):
    sb1 = pages(SB1_2026)
    url = RECORD + "26rs/sb1/vote_history.pdf"
    text = b"\x0c".join([sb1[0], sb1[1], sb1[0]] + sb1[2:])
    votes = scraped(text, url, tmp_path, monkeypatch)
    assert [v.dedupe_key.rsplit("#", 1)[1] for v in votes] == [
        "RSN3792",
        "RCS423",
        "RSN4120",
        "RSN4145",
        "RCS475",
    ]


def test_which_votes_count_as_passage_is_unchanged(tmp_path, monkeypatch):
    """OPEN-689's labels and OPEN-688's chambers stand."""
    votes = scraped(
        convert_pdf(SB1_2026, "text"),
        RECORD + "26rs/sb1/vote_history.pdf",
        tmp_path,
        monkeypatch,
    )
    assert [
        (
            json.loads(v.organization[1:])["classification"],
            v.motion_text,
            v.motion_classification,
            v.result,
        )
        for v in votes
    ] == [
        ("upper", "PASS SB 1", ["passage"], "pass"),
        ("lower", "Pass", ["passage"], "pass"),
        ("upper", "FINAL PASSAGE OF SB 1 w/ HFA 2", ["passage"], "pass"),
        # a whole-bill override (SB 1's history says "Vetoed", not "line items vetoed")
        ("upper", "OVERRIDE VETO FINAL PASSAGE SB 1", ["passage"], "pass"),
        ("lower", "Veto Override", ["passage"], "pass"),
    ]
