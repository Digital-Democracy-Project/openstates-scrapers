"""Tests for OPEN-711: a Rhode Island Senate consent-calendar roll call is tied to every bill
on that day's consent calendar, read from the Senate Journal.

Fixtures in tests/fixtures/ri_open711/ are real pages, read 2026-11-21:
* S_<id>.html: Senate vote reports (webserver.rilegislature.gov/SVotes/votereport.asp?id=<id>).
  17837 "CONSENT CALENDAR" and 17838 "#2" (6/10/2026), 17380 "CONSENT CALENDAR" (3/26/2026),
  16605 "CONSENT CALENDAR" (2/11/2025).
* SJ-<date>.txt: the Senate Journal of that date (rilegislature.gov/journals/senatejournals/...,
  a PDF) as the scraper reads it, the text of `pdftotext -layout` (openstates convert_pdf "text").
"""
import datetime as dt
import os
import sys
import types

import pytest
import scrapelib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ri.bills as rb  # noqa: E402
from ri.bills import RIBillScraper, vote_classification  # noqa: E402
from ri.consent import (  # noqa: E402
    consent_calendars,
    journal_urls,
    match_consent_votes,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ri_open711")

# 6/10/2026, from the journal: CONSENT CALENDAR (7 nominations, then 6 bills) and
# CONSENT CALENDAR II (30 House bills), each passed 38-0
JUNE_10_FIRST = ["S 3369", "H 7122", "H 7308", "H 7349", "H 7350", "H 7870"]
JUNE_10_SECOND = [
    "H " + n
    for n in (
        "7416 7763 7774 8588 8589 8590 8591 8592 8593 8594 7656 7342 7649 7568 7613 7674 "
        "7507 7199 8060 7002 8437 8001 7229 7731 7840 7976 8488 8586 8595 8602"
    ).split()
]


def _text(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


def _bills(*ids):
    return {
        ({"H": "lower", "S": "upper"}[b[0]], b.split()[1]): b
        for group in ids
        for b in group
    }


def _scraper(bills, journal=None):
    """A scraper whose journal fetch returns this fixture's text (or nothing)."""
    scraper = object.__new__(RIBillScraper)
    scraper.warnings = []
    scraper.warning = lambda *a, **k: scraper.warnings.append(a)
    scraper._bill_id_by_type = dict(bills)
    scraper._tz = types.SimpleNamespace(localize=lambda d: d)
    scraper.journal_dates = []

    def senate_journal(date):
        scraper.journal_dates.append(date)
        if journal is None:
            return None, []
        day = dt.datetime.strptime(date, "%m/%d/%Y").date()
        return "https://journal/" + journal, consent_calendars(_text(journal), day)

    scraper.senate_journal_consent_calendars = senate_journal
    return scraper


def _scrape(scraper, ids, chamber, date, session=None):
    listing = "<html><body><center>%s</center></body></html>" % "".join(
        '<div class="vote"><a href="votereport.asp?id=%s">Details</a></div>' % i
        for i in ids
    )
    scraper.get_vote_dates = lambda url, session: [date]
    scraper.post_to = lambda url, d: listing
    scraper.get = lambda url: types.SimpleNamespace(
        text=_text("S_%s.html" % url.split("=")[1])
    )
    return list(scraper.scrape_chamber_votes(chamber, session or date[-4:]))


# --- reading the journal -------------------------------------------------------------


def test_journal_gives_each_voted_consent_calendar_and_its_bills():
    cals = consent_calendars(_text("SJ-06-10-2026.txt"), dt.date(2026, 6, 10))
    assert [(c["yeas"], c["nays"]) for c in cals] == [(38, 0), (38, 0)]
    assert [" ".join(b[1:]) for b in cals[0]["bills"]] == JUNE_10_FIRST
    assert [" ".join(b[1:]) for b in cals[1]["bills"]] == JUNE_10_SECOND
    assert {b[0] for c in cals for b in c["bills"]} == {"2026"}
    # the seven nominations at the top of the first calendar are not bills
    assert len(cals[0]["skipped"]) == 7
    assert all(s.startswith("The ") for s in cals[0]["skipped"])
    assert cals[0]["unread"] == cals[1]["unread"] == []


def test_item_neither_bill_nor_nomination_is_reported():
    # a bill printed in a layout the parser does not know must not vanish silently
    text = _text("SJ-02-11-2025.txt").replace(
        "2.     2025-S 218", "2.     S-218 (2025)"
    )
    scraper = _scraper(_bills(["S 164", "S 218", "S 219", "S 223"]))
    scraper.senate_journal_consent_calendars = lambda date: (
        "j",
        consent_calendars(text, dt.date(2025, 2, 11)),
    )
    votes = _scrape(scraper, [16605], "upper", "2/11/2025")
    assert [v.bill_identifier for v in votes] == ["S 164", "S 219", "S 223"]
    assert any("item not read" in w[0] for w in scraper.warnings)


def test_next_days_calendar_printed_in_the_journal_is_not_read():
    # the 3/26/2026 journal also prints the consent calendar "IN ORDER FOR" a later day
    text = _text("SJ-03-26-2026.txt")
    assert text.count("CONSENT CALENDAR") > 1
    assert len(consent_calendars(text, dt.date(2026, 3, 26))) == 1
    assert consent_calendars(text, dt.date(2026, 3, 27)) == []


def test_item_removed_before_the_vote_is_not_on_the_list():
    # 3/26/2026: five nominations, item 2 "Removed from the Consent Calendar and placed on the
    # Calendar on Tuesday, March 31, 2026"; no bill at all
    (cal,) = consent_calendars(_text("SJ-03-26-2026.txt"), dt.date(2026, 3, 26))
    assert cal["bills"] == []
    assert len(cal["skipped"]) == 5


def test_removed_bill_is_left_out():
    # the real removal line, under a bill item (same layout as the 3/26/2026 journal)
    text = (
        "                CONSENT CALENDAR\n\n"
        "IN ORDER FOR THURSDAY, MARCH 26, 2026:\n\n"
        "1.     2026-S 2001\n       BY Lawson\n\n"
        "Removed from the Consent Calendar and placed on the Calendar on Tuesday, March 31, 2026\n"
        "2.     2026-H 7001 SUB A\n       BY Shekarchi\n\n"
        "Today’s Consent Calendar, by unanimous consent, are read and passed, upon a roll call vote:\n\n"
        "YEAS – 36: Senators ...\n\nNAYS – 0:\n"
    )
    (cal,) = consent_calendars(text, dt.date(2026, 3, 26))
    assert cal["bills"] == [("2026", "H", "7001")]


def test_journal_urls_try_both_namings():
    # 2026 "SJ 06-10-2026.pdf", 2025 "06-20-2025.pdf"
    assert journal_urls("6/10/2026") == [
        "https://www.rilegislature.gov/journals/senatejournals/2026%20Senate%20Journals/SJ%2006-10-2026.pdf",
        "https://www.rilegislature.gov/journals/senatejournals/2026%20Senate%20Journals/06-10-2026.pdf",
    ]


# --- matching roll calls to calendars --------------------------------------------------


def test_roll_calls_and_calendars_pair_in_order_when_tallies_agree():
    rcs = [{"yeas": 37, "nays": 0}, {"yeas": 35, "nays": 1}]
    cals = [{"yeas": 37, "nays": 0}, {"yeas": 35, "nays": 1}]
    assert match_consent_votes(rcs, cals) == list(zip(rcs, cals))


def test_several_roll_calls_are_not_paired_when_a_tally_disagrees():
    rcs = [{"yeas": 37, "nays": 0}, {"yeas": 35, "nays": 1}]
    assert match_consent_votes(rcs, list(reversed(rcs))) == []


def test_count_mismatch_pairs_nothing():
    rcs = [{"yeas": 38, "nays": 0}]
    assert match_consent_votes(rcs, [{"yeas": 38, "nays": 0}] * 2) == []
    assert match_consent_votes(rcs, []) == []


# --- the votes pass, end to end on real pages ------------------------------------------


def test_each_bill_on_the_days_two_consent_calendars_gets_its_own_vote():
    scraper = _scraper(_bills(JUNE_10_FIRST, JUNE_10_SECOND), "SJ-06-10-2026.txt")
    votes = _scrape(scraper, [17837, 17838], "upper", "6/10/2026")
    assert [v.bill_identifier for v in votes] == JUNE_10_FIRST + JUNE_10_SECOND
    assert [v.motion_text for v in votes] == ["Consent Calendar"] * 6 + [
        "Consent Calendar #2"
    ] * 30
    # one key per (roll call, bill): the report URL plus the bill (OPEN-252, OPEN-397)
    keys = [v.dedupe_key for v in votes]
    assert len(set(keys)) == 36
    assert keys[0].endswith("votereport.asp?id=17837#S 3369")
    assert keys[-1].endswith("votereport.asp?id=17838#H 8602")
    for v in votes:
        assert v.organization == '~{"classification": "upper"}'
        assert v.motion_classification == ["passage"]
        assert v.result == "pass"
        assert {c["option"]: c["value"] for c in v.counts}["yes"] == 38
        assert len(v.votes) == 38
        assert v.sources[-1]["url"] == "https://journal/SJ-06-10-2026.txt"
    assert '"from_organization__classification": "upper"' in votes[0].bill
    assert '"from_organization__classification": "lower"' in votes[1].bill
    assert scraper.warnings == []


def test_one_roll_call_one_calendar_is_tied_even_if_the_journal_counts_one_fewer():
    # 2/11/2025: the report says 36-0, the journal lists 35 names; it is the day's only one
    bills = ["S 164", "S 218", "S 219", "S 223"]
    scraper = _scraper(_bills(bills), "SJ-02-11-2025.txt")
    votes = _scrape(scraper, [16605], "upper", "2/11/2025")
    assert [v.bill_identifier for v in votes] == bills
    assert {c["option"]: c["value"] for c in votes[0].counts}["yes"] == 36


def test_calendar_of_nominations_only_ties_nothing():
    scraper = _scraper(_bills(["S 2001"]), "SJ-03-26-2026.txt")
    assert _scrape(scraper, [17380], "upper", "3/26/2026") == []


def test_no_journal_leaves_the_roll_call_unlinked():
    scraper = _scraper(_bills(JUNE_10_FIRST, JUNE_10_SECOND), journal=None)
    assert _scrape(scraper, [17837, 17838], "upper", "6/10/2026") == []
    assert scraper.warnings


def test_roll_call_without_its_calendar_is_not_guessed():
    # only one of the day's two consent roll calls: it could be either calendar
    scraper = _scraper(_bills(JUNE_10_FIRST, JUNE_10_SECOND), "SJ-06-10-2026.txt")
    assert _scrape(scraper, [17838], "upper", "6/10/2026") == []


def test_bill_not_found_is_skipped_others_kept():
    scraper = _scraper(_bills(JUNE_10_FIRST[1:], JUNE_10_SECOND), "SJ-06-10-2026.txt")
    votes = _scrape(scraper, [17837, 17838], "upper", "6/10/2026")
    assert len(votes) == 35
    assert "S 3369" not in [v.bill_identifier for v in votes]
    assert scraper.warnings


def test_bill_of_another_session_is_not_used():
    # the journal names "2026-H 7122"; a 2025 bill numbered 7122 is not it
    scraper = _scraper(_bills(JUNE_10_FIRST, JUNE_10_SECOND), "SJ-06-10-2026.txt")
    assert _scrape(scraper, [17837, 17838], "upper", "6/10/2026", "2025") == []


def test_house_consent_opening_vote_reads_no_journal():
    # the House votes each consent item on its own; its opening vote stays untied
    scraper = _scraper(_bills(JUNE_10_FIRST, JUNE_10_SECOND), "SJ-06-10-2026.txt")
    assert _scrape(scraper, [17837], "lower", "6/10/2026") == []
    assert scraper.journal_dates == []


# --- fetching the journal ----------------------------------------------------------------


def _fetching_scraper(tmp_path, answers, monkeypatch):
    """urlretrieve answers in turn: an exception, or the bytes saved to a file."""
    scraper = object.__new__(RIBillScraper)
    tried = []

    def urlretrieve(url):
        tried.append(url)
        answer = answers[len(tried) - 1]
        if isinstance(answer, Exception):
            raise answer
        path = tmp_path / ("f%d" % len(tried))
        path.write_bytes(answer)
        return str(path), None

    scraper.urlretrieve = urlretrieve
    monkeypatch.setattr(
        rb, "convert_pdf", lambda path, kind: _text("SJ-06-10-2026.txt").encode()
    )
    return scraper, tried


def test_journal_fetch_falls_back_to_the_2025_naming(tmp_path, monkeypatch):
    missing = scrapelib.HTTPError(
        types.SimpleNamespace(status_code=404, url="u", text="")
    )
    scraper, tried = _fetching_scraper(tmp_path, [missing, b"%PDF-1.7"], monkeypatch)
    url, cals = scraper.senate_journal_consent_calendars("6/10/2026")
    assert tried == journal_urls("6/10/2026")
    assert url == tried[1]
    assert len(cals) == 2


def test_journal_fetch_ignores_a_page_that_is_not_a_pdf(tmp_path, monkeypatch):
    scraper, tried = _fetching_scraper(
        tmp_path, [b"<html>not found</html>", b"<html></html>"], monkeypatch
    )
    assert scraper.senate_journal_consent_calendars("6/10/2026") == (None, [])
    assert len(tried) == 2


# --- the label --------------------------------------------------------------------------


@pytest.mark.parametrize("motion", ["Consent Calendar", "Consent Calendar #2"])
def test_consent_calendar_is_passage(motion):
    assert vote_classification(motion) == ["passage"]


@pytest.mark.parametrize("motion", ["CONSENT CALENDAR FOR SENATE STUDY", "#2"])
def test_other_consent_text_is_not_passage(motion):
    assert vote_classification(motion) == []
