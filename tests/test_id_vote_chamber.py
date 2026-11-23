"""OPEN-770: an Idaho roll call is stored under the chamber that took it.

A bill page names no chamber on its rows; the scraper follows the bill from row to row. It moved the bill on a roll
call's own closing text ("Title apvd - to Senate", "Ret'd to House"), so when the Senate failed 2026 H 760 on 03/24
("Ret'd to House") and then reconsidered it on 03/25, the Senate's re-vote (15-20-0) was stored as a House vote and its
senators matched no one. The bill is now in the other chamber from the row that says that chamber received it
("Received from the House passed", "Returned from Senate Failed", "Returned From House Passed").

The fixtures are legislature.idaho.gov's own bill pages: tests/fixtures/id_open769 (2026 H 760, 2025 H 96), id_open682
(2025 H 231) and id_open770 (2026 H 610, a Senate failure "Ret'd to House"; 2026 S 1221, a Senate bill through the
House), read 2026-11-22.
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
PAGES = [
    (H760_2026, "2026", "H 760"),
    (H96_2025, "2025", "H 96"),
    (H231_2025, "2025", "H 231"),
    (H610_2026, "2026", "H 610"),
    (S1221_2026, "2026", "S 1221"),
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
    """A Senate bill: "Received from the Senate" puts it in the House, "Returned From House Passed" (capital F on the
    page) back in the Senate, the Speaker's signature ("Received from Senate; ...") in the House."""
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
