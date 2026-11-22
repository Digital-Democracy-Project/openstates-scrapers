"""OPEN-746: every North Dakota special session is a session of its own, with its own dates, and
its bills and roll calls are filed under it, never under its Legislative Assembly's regular
session (Ramon 2026-11-21: "regular session and special session are two different things. don't
ever mix their dates together").

ndlegis.gov keeps one bill list per Legislative Assembly (api/assembly/<assembly>/data/bills.json)
and tags each bill with its own session (`session_id`, `session_name`): in 69-2025, 202501 "2025
Regular Session", 202502 "Special Session - Jan 2026", 202503 "Special Session - Sep 2026". Every
session reads its assembly's list and keeps only the bills with its tag (scrapers/nd/bills.py).
The bill-number table on ndlegis.gov/assembly (`special`/`special2`, the first number of each type
in a special session) agrees with the tags on every bill of 64-2015, 67-2021, 68-2023 and 69-2025
but one: it starts the September 2026 session's SCRs at 4029, yet SCR 4029 is a March 2025 regular
session resolution (its tag and its URL, .../69-2025/regular/..., both say so). So the tag decides,
not the number.

The fixtures (tests/fixtures/nd_open746/), saved from ndlegis.gov on 2026-11-21:

* bills_69-2025.json: api/assembly/69-2025/data/bills.json cut to HB 1620 (the last regular
  session HB), HB 1621 (the first January 2026 HB), SB 2405 (September 2026) and SCR 4029;
* bills_64-2015.json: api/assembly/64-2015/data/bills.json cut to SB 2378 (regular) and SB 2379
  (the one bill of the August 2016 special session);
* ba1621_special.html: assembly/69-2025/special/bill-actions/ba1621.html cut to its two vote
  modals (House 01/22/2026, Senate 01/23/2026).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import nd  # noqa: E402
import nd.bills as nd_bills  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402
from spatula import URL  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nd_open746")
SESSIONS = nd.NorthDakota.legislative_sessions

# each special session as the legislature's own pages give it: ndlegis.gov/assembly/<assembly>/
# special (and special-2), "Convened ... Adjourned ...", and the bill list's own session tag
SPECIALS = {
    "62S1": ("2011-11-07", "2011-11-11", "62-2011", "201102"),
    "64S1": ("2016-08-02", "2016-08-04", "64-2015", "201502"),
    "67S1": ("2021-11-08", "2021-11-12", "67-2021", "202102"),
    "68S1": ("2023-10-23", "2023-10-25", "68-2023", "202302"),
    "69S1": ("2026-01-21", "2026-01-23", "69-2025", "202502"),
    "69S2": ("2026-09-02", "2026-09-04", "69-2025", "202503"),
}


def session(identifier):
    (found,) = [s for s in SESSIONS if s["identifier"] == identifier]
    return found


class _Response:
    def __init__(self, path):
        self.content = open(path, "rb").read()

    def json(self):
        return json.loads(self.content)


def scrape(identifier, assembly_file, monkeypatch):
    """Everything the bill scraper yields for one session from a saved bill list; each bill's
    actions page is the saved HB 1621 page for HB 1621 and an empty page for the others."""
    assembly, site_session_id = nd_bills.site_session(session(identifier))

    def fake_get(url):
        if url.endswith("/69-2025/special/bill-actions/ba1621.html"):
            return _Response(os.path.join(FIXTURES, "ba1621_special.html"))
        if "/biography/" in url:
            r = _Response(os.devnull)
            r.content = b"<html><body><h1>Senator A Member</h1></body></html>"
            return r
        r = _Response(os.devnull)
        r.content = b"<html><body></body></html>"
        return r

    monkeypatch.setattr(nd_bills.requests, "get", fake_get)
    bill_list = nd_bills.BillList(
        {
            "session": identifier,
            "assembly": assembly,
            "site_session_id": site_session_id,
        }
    )
    bill_list.source = URL(bill_list.source)  # as spatula's do_scrape does
    bill_list.response = _Response(os.path.join(FIXTURES, assembly_file))
    return list(bill_list.process_page())


def test_every_special_session_has_its_own_entry_with_the_legislatures_dates():
    for identifier, (start, end, assembly, tag) in SPECIALS.items():
        s = session(identifier)
        assert s["classification"] == "special"
        assert (s["start_date"], s["end_date"]) == (start, end)
        assert nd_bills.site_session(s) == (assembly, tag)
        assert s["active"] is False  # switched on only when Ramon decides


def test_regular_sessions_read_their_own_assembly_and_tag():
    assert nd_bills.site_session(session("69")) == ("69-2025", "202501")
    assert nd_bills.site_session(session("64")) == ("64-2015", "201501")
    assert nd_bills.site_session(session("70")) == ("70-2027", "202701")


def test_no_regular_session_holds_a_special_session_day_or_the_reverse():
    regular = [s for s in SESSIONS if s["classification"] == "primary"]
    special = [s for s in SESSIONS if s["classification"] == "special"]
    assert {s["identifier"] for s in special} == set(SPECIALS)
    for r in regular:
        for sp in special:
            assert (
                sp["end_date"] < r["start_date"] or r["end_date"] < sp["start_date"]
            ), (r["identifier"], sp["identifier"])


@pytest.mark.parametrize(
    "identifier,bills",
    [
        (
            "69",
            ["HB 1620", "SCR 4029"],
        ),  # SCR 4029 stays regular, whatever the number table says
        ("69S1", ["HB 1621"]),
        ("69S2", ["SB 2405"]),
    ],
)
def test_each_bill_lands_in_its_own_session_only(identifier, bills, monkeypatch):
    out = [o for o in scrape(identifier, "bills_69-2025.json", monkeypatch)]
    found = [o for o in out if isinstance(o, Bill)]
    assert sorted(b.identifier for b in found) == bills
    assert {b.legislative_session for b in found} == {identifier}


def test_the_august_2016_bill_lands_in_64S1_not_64(monkeypatch):
    regular = scrape("64", "bills_64-2015.json", monkeypatch)
    special = scrape("64S1", "bills_64-2015.json", monkeypatch)
    assert [b.identifier for b in regular] == ["SB 2378"]
    assert [(b.identifier, b.legislative_session) for b in special] == [
        ("SB 2379", "64S1")
    ]


def test_a_special_session_bills_roll_calls_are_filed_under_it(monkeypatch):
    votes = [
        o
        for o in scrape("69S1", "bills_69-2025.json", monkeypatch)
        if isinstance(o, VoteEvent)
    ]
    assert [(v.legislative_session, str(v.start_date)[:10]) for v in votes] == [
        ("69S1", "2026-01-22"),
        ("69S1", "2026-01-23"),
    ]
    regular = scrape("69", "bills_69-2025.json", monkeypatch)
    assert not [o for o in regular if isinstance(o, VoteEvent)]


def test_the_source_is_the_assemblys_bill_list():
    bill_list = nd_bills.BillList(
        {"session": "69S2", "assembly": "69-2025", "site_session_id": "202503"}
    )
    assert bill_list.source == (
        "https://ndlegis.gov/api/assembly/69-2025/data/bills.json"
    )
