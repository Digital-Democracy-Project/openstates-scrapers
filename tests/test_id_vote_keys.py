"""OPEN-769: every Idaho roll call keeps its own identity at the import (North Dakota's OPEN-757 pattern).

North Dakota's first load stopped on two roll calls with the same motion text, chamber and minute: with no `dedupe_key`
the vote importer (openstates-core `vote_events.py`, `get_object()`) matches on session + bill + motion text + start
date + organization. An Idaho bill page prints no roll-call number and only a day, no time, so two roll calls on one
bill in one chamber on one day under the same reading would be taken for one. The key is the bill page's address
(sessioninfo/<session>/legislation/<bill>/) plus the day and the roll call's place among that day's roll calls on the
page. A row printed twice word for word on one day is one roll call and is kept once.

No two roll calls on the saved pages share a motion text, day and chamber (10 roll calls on four pages), so the
colliding pair below is built from 2026 H 760's real Senate third reading (03/24, 17-17-1): a copy with its own tally.

The fixtures are legislature.idaho.gov's own bill pages (tests/fixtures/id_open769, read 2026-11-22; id_open682).
"""
import collections
import os
import sys
import types
from collections import defaultdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from id.bills import IDBillScraper  # noqa: E402

from openstates.scrape import VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
H760_2026 = os.path.join(FIXTURES, "id_open769", "h0760_2026.html")
H96_2025 = os.path.join(FIXTURES, "id_open769", "h0096_2025.html")
H231_2025 = os.path.join(FIXTURES, "id_open682", "h0231_2025.html")
PAGE = "https://legislature.idaho.gov/sessioninfo/{}/legislation/{}/"
SENATE_TALLY = "FAILED&#160;-&#160;17-17-1"


@pytest.fixture
def scraper(tmp_path, monkeypatch):
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text("id: {}\n")
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    scraper = IDBillScraper.__new__(IDBillScraper)
    scraper._subjects = defaultdict(list)
    scraper.warnings = []
    scraper.warning = scraper.warnings.append
    return scraper


def read(path):
    return open(path, encoding="utf-8").read()


def votes(scraper, page, session, bill_id):
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(text=page)
    chamber = "lower" if bill_id[0] == "H" else "upper"
    return [
        v
        for v in scraper.scrape_bill(chamber, session, bill_id)
        if isinstance(v, VoteEvent)
    ]


def senate_row(page):
    """The <tr> of H 760's Senate third reading on 03/24."""
    start = page.rindex("<tr", 0, page.index(SENATE_TALLY))
    end = page.index("</tr>", start) + len("</tr>")
    return start, end


def import_match_key(vote):
    """What the importer matches a vote on: its dedupe_key alone when it has one, otherwise session + bill + motion
    text + start date + organization (Idaho's votes have no identifier)."""
    return getattr(vote, "dedupe_key", None) or (
        vote.legislative_session,
        str(vote.bill),
        vote.motion_text,
        str(vote.start_date),
        str(vote.organization),
    )


def test_each_roll_call_is_keyed_on_its_page_day_and_place(scraper):
    page = PAGE.format("2026", "H760")
    assert [v.dedupe_key for v in votes(scraper, read(H760_2026), "2026", "H 760")] == [
        page + "#2026-03-09-1",
        page + "#2026-03-24-1",
        page + "#2026-03-25-1",
    ]


def test_keys_are_unique_across_sessions_and_bills(scraper):
    keys = [
        v.dedupe_key
        for page, session, bill in [
            (H760_2026, "2026", "H 760"),
            (H96_2025, "2025", "H 96"),
            (H231_2025, "2025", "H 231"),
        ]
        for v in votes(scraper, read(page), session, bill)
    ]
    assert len(keys) == len(set(keys)) == 3 + 3 + 2
    # the same bill's page in another session is another address
    again = votes(scraper, read(H760_2026), "2027", "H 760")
    assert {v.dedupe_key.split("#")[0] for v in again} == {PAGE.format("2027", "H760")}
    assert not {v.dedupe_key for v in again} & set(keys)


def test_two_roll_calls_with_the_same_motion_and_day_get_their_own_keys(scraper):
    page = read(H760_2026)
    start, end = senate_row(page)
    row = page[start:end]
    # the earlier roll call, without the real row's closing "Ret'd to House" (a roll call's own closing text no
    # longer moves the bill since OPEN-770; dropping it keeps the copy a plain earlier Senate roll call)
    first = row.replace(SENATE_TALLY, "FAILED&#160;-&#160;16-18-1").replace(
        "Ret&#8217;d&#160;to&#160;House", ""
    )
    assert first.count("16-18-1") == 1 and "to&#160;House" not in first
    found = votes(scraper, page[:start] + first + page[start:], "2026", "H 760")
    senate = [v for v in found if v.start_date == "2026-03-24"]
    assert len(senate) == 2
    a, b = senate
    # without a key the importer would take the second for the first
    assert (a.motion_text, a.start_date, a.organization) == (
        b.motion_text,
        b.start_date,
        b.organization,
    )
    url = PAGE.format("2026", "H760")
    assert [a.dedupe_key, b.dedupe_key] == [
        url + "#2026-03-24-1",
        url + "#2026-03-24-2",
    ]
    assert [c["value"] for c in a.counts] == [16, 18, 1]
    assert [c["value"] for c in b.counts] == [17, 17, 1]
    keys = collections.Counter(import_match_key(v) for v in found)
    assert [k for k, n in keys.items() if n > 1] == []


def test_a_row_printed_twice_is_kept_once(scraper):
    page = read(H760_2026)
    start, end = senate_row(page)
    found = votes(scraper, page[:end] + page[start:end] + page[end:], "2026", "H 760")
    assert [v.dedupe_key.rsplit("#", 1)[1] for v in found] == [
        "2026-03-09-1",
        "2026-03-24-1",
        "2026-03-25-1",
    ]
    assert len(scraper.warnings) == 1


def test_the_same_tally_row_under_another_motion_is_another_roll_call(scraper):
    """2025 H 231, House 02/14: the real text-less tally row "PASSED - 61-6-3" under the reading above it, then the
    same row word for word under a "Motion to reconsider" row (pm-review): two roll calls, not one printed twice."""
    page = read(H231_2025)
    tally = "PASSED&#160;-&#160;61-6-3"
    start = page.rindex("<tr", 0, page.index(tally))
    end = page.index("</tr>", start) + len("</tr>")
    reconsider = (
        "<tr><td></td><td></td><td>Motion&#160;to&#160;reconsider&#160;-&#160;PASSED</td>"
        "<td></td></tr>"
    )
    page = page[:end] + reconsider + page[start:end] + page[end:]
    house = [
        v for v in votes(scraper, page, "2025", "H 231") if v.start_date == "2025-02-14"
    ]
    assert [v.motion_text.split(",")[0] for v in house] == [
        "Rules Suspended: Ayes 62 Nays 6 Abs/Excd 2",
        "Motion to reconsider  PASSED",
    ]
    url = PAGE.format("2025", "H231")
    assert [v.dedupe_key for v in house] == [
        url + "#2025-02-14-1",
        url + "#2025-02-14-2",
    ]
    assert scraper.warnings == []


def test_which_votes_count_as_passage_is_unchanged(scraper):
    """OPEN-682's labels stand (the same as clean main gives for these pages)."""
    found = votes(scraper, read(H760_2026), "2026", "H 760")
    found += votes(scraper, read(H96_2025), "2025", "H 96")
    assert [
        (v.start_date, v.motion_text, v.motion_classification, v.result) for v in found
    ] == [
        ("2026-03-09", "Read Third Time in Full –", ["passage"], "pass"),
        ("2026-03-24", "Read third time in full –", ["passage"], "fail"),
        ("2026-03-25", "Motion to reconsider  PASSED", ["passage"], "fail"),
        ("2025-02-18", "Read Third Time in Full –", ["passage"], "pass"),
        (
            "2025-03-26",
            "Read third time as amended in the Senate –",
            ["passage"],
            "pass",
        ),
        (
            "2025-03-28",
            "Rules Suspended: Ayes 68 Nays 0 Abs/Excd 2, read in full as required –",
            ["passage"],
            "pass",
        ),
    ]
