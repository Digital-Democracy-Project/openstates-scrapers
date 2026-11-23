"""OPEN-770: an Idaho roll call is stored under the chamber that took it.

A bill page names no chamber on its rows; the scraper follows the bill from row to row. Two ways it lost track:

* It moved the bill on every roll call's closing "to House"/"to Senate". When the Senate failed 2026 H 760 on 03/24
  ("Ret'd to House") and reconsidered it on 03/25, the Senate's re-vote (15-20-0) was stored as a House vote. A failed
  roll call no longer moves the bill; the House has it from its own "Returned from Senate Failed" row (each "Received
  from ..." / "Returned from ..." row puts the bill in the chamber that wrote it). A passed roll call's "Title apvd -
  to Senate" still moves it: on a same-day passage the Senate may print no "Received from the House" row (2025 H 480).
* A committee report in the second chamber ("Reported out of Committee without Recommendation") flipped the chamber,
  so 2025 S 1180's House vote (45-24-1) was stored as a Senate vote.

The fixtures are legislature.idaho.gov's own bill pages: tests/fixtures/id_open769 (2026 H 760, 2025 H 96), id_open682
(2025 H 231) and id_open770 (2026 H 610, a Senate failure "Ret'd to House"; 2026 S 1221, a Senate bill through the
House; 2025 H 480, passed by both chambers in two days; 2025 S 1180), read 2026-11-22.
"""
import json
import os
import sys
import types
from collections import defaultdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from id.bills import IDBillScraper  # noqa: E402

from openstates.scrape import Bill, VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
H760_2026 = os.path.join(FIXTURES, "id_open769", "h0760_2026.html")
H96_2025 = os.path.join(FIXTURES, "id_open769", "h0096_2025.html")
H231_2025 = os.path.join(FIXTURES, "id_open682", "h0231_2025.html")
H610_2026 = os.path.join(FIXTURES, "id_open770", "h0610_2026.html")
S1221_2026 = os.path.join(FIXTURES, "id_open770", "s1221_2026.html")
H480_2025 = os.path.join(FIXTURES, "id_open770", "h0480_2025.html")
S1180_2025 = os.path.join(FIXTURES, "id_open770", "s1180_2025.html")
PAGES = [
    (H760_2026, "2026", "H 760"),
    (H96_2025, "2025", "H 96"),
    (H231_2025, "2025", "H 231"),
    (H610_2026, "2026", "H 610"),
    (S1221_2026, "2026", "S 1221"),
    (H480_2025, "2025", "H 480"),
    (S1180_2025, "2025", "S 1180"),
]
# Idaho's chambers: 70 representatives, 35 senators
SEATS = {"lower": 70, "upper": 35}


@pytest.fixture
def scraper(tmp_path, monkeypatch):
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text("id: {}\n")
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    scraper = IDBillScraper.__new__(IDBillScraper)
    scraper._subjects = defaultdict(list)
    scraper.warning = lambda *a, **k: None
    return scraper


def scrape(scraper, path, session, bill_id):
    page = open(path, encoding="utf-8").read()
    scraper.get = lambda url, *a, **k: types.SimpleNamespace(text=page)
    chamber = "lower" if bill_id[0] == "H" else "upper"
    found = list(scraper.scrape_bill(chamber, session, bill_id))
    votes = [v for v in found if isinstance(v, VoteEvent)]
    (bill,) = [b for b in found if isinstance(b, Bill)]
    return votes, bill


def chamber(pseudo_id):
    # a vote's or action's chamber is stored as a pseudo id: ~{"classification": "upper"}
    return json.loads(pseudo_id[1:])["classification"]


def voters(vote):
    return {v["voter_name"] for v in vote.votes}


def action_chambers(bill, start):
    """(chamber, start of the text) of each action from the first one whose text starts with `start`."""
    texts = [a["description"] for a in bill.actions]
    first = next(i for i, t in enumerate(texts) if t.startswith(start))
    return [
        (chamber(a["organization_id"]), a["description"][:30])
        for a in bill.actions[first:]
    ]


def test_h760_senate_revote_is_a_senate_vote(scraper):
    votes, _ = scrape(scraper, H760_2026, "2026", "H 760")
    assert [(v.start_date, chamber(v.organization)) for v in votes] == [
        ("2026-03-09", "lower"),
        ("2026-03-24", "upper"),
        ("2026-03-25", "upper"),
    ]
    house, senate, revote = votes
    # the re-vote names the 35 senators of the 03/24 roll call (Harris is a name in both chambers)
    assert len(voters(revote)) == 35
    assert voters(revote) == voters(senate)
    assert voters(revote) & voters(house) == {"Harris"}


def test_h760_rows_after_ret_d_to_house_stay_in_the_senate_until_it_returns_the_bill(
    scraper,
):
    _, bill = scrape(scraper, H760_2026, "2026", "H 760")
    assert action_chambers(bill, "Read third time in full") == [
        ("upper", "Read third time in full – FAIL"),
        ("upper", "Notice to reconsider - Held at"),
        ("upper", "Motion to reconsider - PASSED"),
        ("upper", "FAILED - 15-20-0AYES – Bernt, "),
        ("lower", "Returned from Senate Failed; F"),
    ]


def test_h610_senate_failure_returned_to_the_house(scraper):
    votes, bill = scrape(scraper, H610_2026, "2026", "H 610")
    assert [(v.start_date, chamber(v.organization)) for v in votes] == [
        ("2026-02-17", "lower"),
        ("2026-03-10", "upper"),
    ]
    assert action_chambers(bill, "Read third time in full") == [
        ("upper", "Read third time in full – FAIL"),
        ("lower", "Returned from Senate Failed; F"),
    ]


def test_s1221_moves_on_the_other_chambers_arrival_rows(scraper):
    """A Senate bill: "Received from the Senate" puts it in the House, its House passage ("Title apvd - to Senate") back
    in the Senate, the Speaker's signature ("Received from Senate; ...") in the House."""
    votes, bill = scrape(scraper, S1221_2026, "2026", "S 1221")
    assert [(v.start_date, chamber(v.organization)) for v in votes] == [
        ("2026-02-03", "upper"),
        ("2026-02-25", "lower"),
    ]
    assert action_chambers(bill, "Read third time in full") == [
        ("upper", "Read third time in full – PASS"),
        ("lower", "Received from the Senate, File"),
        ("lower", "Read First Time, Referred to C"),
        ("lower", "Reported out of Committee with"),
        ("lower", "Read second time; Filed for Th"),
        ("lower", "U.C. to hold place on third re"),
        ("lower", "Read Third Time in Full – PASS"),
        ("upper", "Returned From House Passed; re"),
        ("upper", "Reported enrolled; signed by P"),
        ("lower", "Received from Senate; Signed b"),
        ("upper", "Reported signed by the Speaker"),
        ("upper", "Reported delivered to Governor"),
        ("upper", "Signed by Governor on 03/04/26"),
    ]


def test_h480_a_passed_roll_call_moves_the_bill_without_an_arrival_row(scraper):
    """The House passed it 04/02 ("Title apvd - to Senate"); the Senate's next row is its own introduction, 04/03."""
    votes, bill = scrape(scraper, H480_2025, "2025", "H 480")
    assert [(v.start_date, chamber(v.organization)) for v in votes] == [
        ("2025-04-02", "lower"),
        ("2025-04-03", "upper"),
    ]
    assert action_chambers(bill, "Introduced, read first time; ref")[:3] == [
        ("upper", "Introduced, read first time; r"),
        ("upper", "Reported out of Committee with"),
        ("upper", "Rules Suspended (2/3 Vote - Re"),
    ]


def test_s1180_a_committee_report_in_the_house_does_not_move_the_bill(scraper):
    votes, bill = scrape(scraper, S1180_2025, "2025", "S 1180")
    assert [(v.start_date, chamber(v.organization)) for v in votes] == [
        ("2025-03-27", "upper"),
        ("2025-04-03", "lower"),
    ]
    assert action_chambers(bill, "Reported out of Committee without")[:4] == [
        ("lower", "Reported out of Committee with"),
        ("lower", "Motion to suspend failed: Ayes"),
        ("lower", "Read second time; Filed for Th"),
        ("lower", "Rules Suspended: Ayes 69 Nays "),
    ]


@pytest.mark.parametrize("path,session,bill_id", PAGES)
def test_every_tally_fits_the_chamber_it_is_stored_under(
    scraper, path, session, bill_id
):
    """An Idaho roll call counts the whole chamber (absent and excused included): more than the Senate's 35 is a
    House vote, 35 or fewer a Senate vote, and no tally exceeds its chamber's seats."""
    votes, _ = scrape(scraper, path, session, bill_id)
    assert votes
    for v in votes:
        total = sum(c["value"] for c in v.counts)
        assert total <= SEATS[chamber(v.organization)], (v.start_date, total)
        assert (total > SEATS["upper"]) == (chamber(v.organization) == "lower"), (
            v.start_date,
            total,
        )
