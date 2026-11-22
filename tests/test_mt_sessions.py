"""OPEN-749: Montana's November 2017 Special Session (20172) is a session of its own, 2017s1.

It was in ignored_scraped_sessions, so its bills and roll calls were never scraped. Ramon
(2026-11-21): regular and special sessions are separate, each with its own dates, as the
legislature itself keeps them.

The fixtures (mt_open749/) are the legislature's own records, saved 2026-11-21:

* archive_sessions.json: api.legmt.gov/archive/v1/sessions, the first list get_session_list
  reads (16 sessions, 1999 to 2023; its specials are 20052, 20072 and 20172).
* legislators_sessions.json: api.legmt.gov/legislators/v1/sessions, the second list (2025 and
  2027, both REGULAR).
* archive_bills_search_20172.json: the archive's bill search for sessionId 20172 (the answer
  lists 27 bills; six are kept: HB 2, HB 5, SB 1, SJ 1, SR 1 and the draft LC0018).
* house_journal_day1_head.txt, senate_journal_day1_head.txt, house_journal_day2_sine_die.txt,
  senate_journal_day2_sine_die.txt: the text of the House and Senate Journals of the special
  session (leg.mt.gov/bills/Specsess/1117/HJrnl/HJ0001.pdf, HJ0002.pdf, SJrnl/SJ0001.pdf,
  SJ0002.pdf), the heading of each first day and the sine die of each second day.
"""
import datetime
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import mt  # noqa: E402
from mt.bills import MTBillScraper  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mt_open749")


def read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def load(name):
    return json.loads(read(name))


def session(identifier):
    (found,) = [
        s for s in mt.Montana.legislative_sessions if s["identifier"] == identifier
    ]
    return found


def by_scraped_name():
    return {s["_scraped_name"]: s for s in mt.Montana.legislative_sessions}


class _Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_session_check_accepts_the_saved_session_lists(monkeypatch):
    answers = {
        "https://api.legmt.gov/archive/v1/sessions": load("archive_sessions.json"),
        "https://api.legmt.gov/legislators/v1/sessions": load(
            "legislators_sessions.json"
        ),
    }
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Resp(answers[url]))
    jurisdiction = mt.Montana()
    scraped = jurisdiction.get_session_list()
    assert len(scraped) == 18
    assert "20172" in scraped
    # openstates-core's own check: it raises on a listed session the scraper neither has nor
    # ignores, and returns the active identifiers otherwise
    assert check_session_list(jurisdiction) == {"2027"}
    # 20172 is scraped now, not ignored
    assert "20172" not in mt.Montana.ignored_scraped_sessions


def test_every_special_the_archive_lists_in_the_scrapers_span_is_its_own_session():
    archive = load("archive_sessions.json")
    first_year = min(int(s["start_date"][:4]) for s in mt.Montana.legislative_sessions)
    specials = [r for r in archive if r["sessionTypeDesc"] == "Special"]
    in_span = {str(r["sessionId"]) for r in specials if r["sessionYear"] >= first_year}
    # the only special session from 2011 on (the legislators endpoint lists none)
    assert in_span == {"20172"}
    assert all(r["type"] == "REGULAR" for r in load("legislators_sessions.json"))
    sessions = by_scraped_name()
    for row in specials:
        scraped_name = str(row["sessionId"])
        if row["sessionYear"] >= first_year:
            s = sessions[scraped_name]
            assert s["classification"] == "special"
            # the document endpoints need the legislature's ordinal, as the archive gives it
            assert s["extras"]["legislatureOrdinal"] == row["ordinal"]
            assert s["extras"]["newAPIIdentifier"] is None
        else:
            # 2005 and 2007 are before the scraper's span, ignored like their regular sessions
            assert scraped_name in mt.Montana.ignored_scraped_sessions
            assert scraped_name not in sessions


def journal_date(text, pattern):
    (day,) = re.findall(pattern, " ".join(text.split()))
    return datetime.datetime.strptime(day, "%B %d, %Y").date().isoformat()


def test_2017s1_dates_are_the_journals():
    s = session("2017s1")
    assert s["_scraped_name"] == "20172"
    assert s["name"] == "2017 November Special Session"
    for chamber in ("house", "senate"):
        head = read(f"{chamber}_journal_day1_head.txt")
        assert "SPECIAL SESSION NOVEMBER 2017" in head
        assert "FIRST LEGISLATIVE DAY" in head
        assert (
            journal_date(head, r"Helena, Montana \w+ Chambers (\w+ \d+, \d{4})")
            == s["start_date"]
        )
    house = read("house_journal_day2_sine_die.txt")
    senate = read("senate_journal_day2_sine_die.txt")
    assert "Adjourn Sine Die" in house and "adjourn sine die" in senate
    # both chambers adjourned after midnight, on the day after their second legislative day
    assert (
        journal_date(house, r"adjourned Sine Die .* at 1:07 a\.m\. on (\w+ \d+, \d{4})")
        == s["end_date"]
    )
    assert (
        journal_date(senate, r"Senate adjourned at 12:36 a\.m\., (\w+ \d+, \d{4})")
        == s["end_date"]
    )


def test_no_regular_session_includes_a_special_session_day():
    sessions = mt.Montana.legislative_sessions
    specials = [s for s in sessions if s["classification"] == "special"]
    assert specials
    for special in specials:
        start = datetime.date.fromisoformat(special["start_date"])
        end = datetime.date.fromisoformat(special["end_date"])
        assert start <= end
        for regular in sessions:
            if regular["classification"] != "primary":
                continue
            r_start = datetime.date.fromisoformat(regular["start_date"])
            r_end = datetime.date.fromisoformat(regular["end_date"])
            assert end < r_start or start > r_end, (special, regular)


def test_bills_scraper_reaches_2017s1_by_its_session_id(monkeypatch):
    page = load("archive_bills_search_20172.json")
    empty = {"bills": dict(page["bills"], content=[], numberOfElements=0)}
    posted = []

    def post(url, params=None, json=None, **kw):
        posted.append((url, params, json))
        return _Resp(page if params["offset"] == "0" else empty)

    monkeypatch.setattr(requests, "post", post)
    doc_urls = []

    def get(url):
        doc_urls.append(url)
        return _Resp([])

    scraper = MTBillScraper.__new__(MTBillScraper)
    scraper.jurisdiction = mt.Montana()
    scraper.info = lambda *a, **k: None
    scraper.warning = lambda *a, **k: None
    scraper.get = get
    out = list(scraper.scrape(session="2017s1"))

    # the archive's bill search, by the legislature's session id
    assert posted
    assert {(u, j["sessionId"]) for u, _, j in posted} == {
        ("https://api.legmt.gov/archive/v1/bills/search", "20172")
    }
    bills = [o for o in out if isinstance(o, Bill)]
    votes = [o for o in out if isinstance(o, VoteEvent)]
    assert sorted(b.identifier for b in bills) == [
        "HB 2",
        "HB 5",
        "LC0018",
        "SB 1",
        "SJ 1",
        "SR 1",
    ]
    assert {b.legislative_session for b in bills} == {"2017s1"}
    # the archive's roll calls (counts on the bill's actions) come with their bills
    expected_votes = sum(
        1
        for r in page["bills"]["content"]
        for a in r["billActions"]
        if a["yesVotes"] or a["noVotes"]
    )
    assert expected_votes == 24
    assert len(votes) == expected_votes
    # versions and fiscal notes are asked for with the special session's own ordinals
    assert doc_urls
    assert all(
        "legislatureOrdinal=65&sessionOrdinal=20172" in u for u in doc_urls
    ), doc_urls
