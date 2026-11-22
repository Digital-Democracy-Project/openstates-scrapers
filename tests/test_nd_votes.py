"""Tests for OPEN-679: North Dakota's roll calls are classified from the vote modal's title.

Every motion below is a real roll call from ndlegis.gov bill-actions pages (read 2026-11-20), built the way
the scraper builds it: "Motion for <modal title> on <bill>". North Dakota shows only two titles. "Final
Passage" is the "Second reading, passed/failed" roll call, including the repeat after a concurrence or a
conference report; "Consideration of Amendments" is an amendment or division roll call.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from classify_motion import classify_motion  # noqa: E402
from nd.bills import vote_classification  # noqa: E402

REAL_ROLL_CALLS = [
    # 2025 HB 1001, House 02/20: "Second reading, passed, yeas 83 nays 4"
    ("Motion for Final Passage on HB 1001", ["passage"]),
    # 2025 HB 1163, House 02/25: "Second reading, failed to pass, yeas 5 nays 84" (a lost passage vote)
    ("Motion for Final Passage on HB 1163", ["passage"]),
    # 2025 SB 2400, House 04/24: failed to pass, yeas 14 nays 78
    ("Motion for Final Passage on SB 2400", ["passage"]),
    # 2023 HB 1297, House 04/25: the roll call right after "Conference committee report adopted"
    ("Motion for Final Passage on HB 1297", ["passage"]),
    # 2025 HB 1300, House 04/07: the roll call right after "Concurred" (failed, yeas 42 nays 48)
    ("Motion for Final Passage on HB 1300", ["passage"]),
    # 2025 HCR 3001 / SCR 4001: "Second reading, adopted" of a concurrent resolution
    ("Motion for Final Passage on HCR 3001", ["passage"]),
    ("Motion for Final Passage on SCR 4001", ["passage"]),
    # 2025 HB 1015, Senate 04/22: "Division A lost" (23-24) and "Division B adopted" (32-15)
    ("Motion for Consideration of Amendments on HB 1015", ["amendment"]),
    # 2023 HB 1522, Senate 04/03: "Amendment adopted" (31-16)
    ("Motion for Consideration of Amendments on HB 1522", ["amendment"]),
]


@pytest.mark.parametrize("motion,expected", REAL_ROLL_CALLS)
def test_real_roll_calls(motion, expected):
    assert vote_classification(motion) == expected


def test_amendment_roll_call_is_not_passage_in_the_shared_rules():
    assert (
        classify_motion("nd", "Motion for Consideration of Amendments on HB 1015") == []
    )


@pytest.mark.parametrize(
    "motion",
    [
        "Motion for Reconsideration on HB 1300",  # not seen on the site: must never default to passage
        "Motion for Final Passage Reconsideration on HB 1300",  # a longer title sharing the prefix
        "Motion for Consideration of Amendments Reconsidered on HB 1015",
        "",
    ],
)
def test_unseen_title_stays_unclassified(motion):
    assert vote_classification(motion) == []


def test_scraper_no_longer_hard_codes_passage():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "scrapers", "nd", "bills.py")
    ).read()
    assert 'classification="passage"' not in src
    assert "classification=vote_classification(motion)" in src


# OPEN-722: a voter's name comes from their ndlegis.gov biography page <h1>, which carries the title
# ("Representative Bert Anderson"). The scraper must give the bare name on the first lookup in a run
# (cache miss), not only on later ones (cache hit). The page is stubbed; nothing touches the network.
class _StubResponse:
    def __init__(self, html):
        self.content = html.encode()


def _name_lookup(monkeypatch, pages):
    import nd.bills as nd_bills

    calls = []

    def fake_get(url):
        calls.append(url)
        return _StubResponse(pages[url])

    monkeypatch.setattr(nd_bills.requests, "get", fake_get)
    bill_list = nd_bills.BillList(
        {"session": "69", "assembly": "69-2025", "site_session_id": "202501"}
    )
    bill_list.members_cache = {}  # the class-level cache would leak between tests
    return bill_list, calls


@pytest.mark.parametrize(
    "h1,expected",
    [
        ("Representative Bert Anderson", "Bert Anderson"),
        ("Senator Judy Lee", "Judy Lee"),
    ],
)
def test_first_and_second_lookup_both_return_the_bare_name(monkeypatch, h1, expected):
    url = "https://ndlegis.gov/biography/member"
    bill_list, calls = _name_lookup(
        monkeypatch, {url: f"<html><body><h1> {h1} </h1></body></html>"}
    )
    assert bill_list.get_voter_name_from_url_request(url) == expected  # cache miss
    assert bill_list.get_voter_name_from_url_request(url) == expected  # cache hit
    assert calls == [url]  # the second call really came from the cache


@pytest.mark.parametrize(
    "h1,expected",
    [
        ("Representative Pat Senatore", "Pat Senatore"),
        (
            "Pat Senator Smith",
            "Pat Senator Smith",
        ),  # a title word later in the name stays
        ("Bert Representative Anderson", "Bert Representative Anderson"),
    ],
)
def test_only_a_leading_title_word_is_removed(monkeypatch, h1, expected):
    url = "https://ndlegis.gov/biography/member"
    bill_list, _ = _name_lookup(
        monkeypatch, {url: f"<html><body><h1>{h1}</h1></body></html>"}
    )
    assert bill_list.get_voter_name_from_url_request(url) == expected


def test_missing_biography_falls_back_to_the_name_in_the_url(monkeypatch):
    url = "https://ndlegis.gov/biography/randy-a-schobinger"
    bill_list, _ = _name_lookup(monkeypatch, {url: "<html><body></body></html>"})
    assert bill_list.get_voter_name_from_url_request(url) == "Randy A Schobinger"
    assert bill_list.get_voter_name_from_url_request(url) == "Randy A Schobinger"
