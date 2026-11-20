"""OPEN-717: Maryland's votes scraper asks the site for the session it is scraping.

scrape_chamber() fetched FloorActions/Index/<chamber> with no session, and the site now
answers that with its newest session (2027RS), which is empty: the scraper returned 0
votes. It now asks for ?ys=<session code> (2026 -> 2026rs, 2026s1 -> 2026s1).

The fixtures are the site's own pages saved 2026-11-20, trimmed to their first table:

* index_<chamber>_2026rs.html: ?ys=2026rs, 81 House and 76 Senate session days.
* index_<chamber>_2026s1.html: ?ys=2026s1, 4 House and 5 Senate session days.
* index_house_default.html: no ?ys= (the site's default, 2027RS), no session days.
* day_house-1_2026rs.html: House day 1 of 2026RS, two roll-call PDFs.

The fake site below answers like the real one: an index request without a session code
it knows gets the empty default page.
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from md.votes import MDVoteScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "md_open717")
INDEX = "/mgawebsite/FloorActions/Index/"
SAVED_INDEXES = {
    ("house", "2026rs"): "index_house_2026rs.html",
    ("senate", "2026rs"): "index_senate_2026rs.html",
    ("house", "2026s1"): "index_house_2026s1.html",
    ("senate", "2026s1"): "index_senate_2026s1.html",
}


def read(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


class FakeResponse:
    def __init__(self, text):
        self.text = text


class OfflineMD(MDVoteScraper):
    """Serves saved pages through the real lxmlize(); records every request."""

    def __init__(self):
        self.requested = []
        self.votes_seen = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        parsed = urlparse(url)
        if parsed.path.startswith(INDEX):
            chamber = parsed.path[len(INDEX) :]
            code = parse_qs(parsed.query).get("ys", [""])[0].lower()
            name = SAVED_INDEXES.get((chamber, code), "index_house_default.html")
            return FakeResponse(read(name))
        if parsed.path.endswith("/house-1-") and "year=2026RS" in parsed.query:
            return FakeResponse(read("day_house-1_2026rs.html"))
        return FakeResponse("<html><body></body></html>")

    def scrape_vote(self, url, session):
        self.votes_seen.append(url)
        return url


def run(session, chamber):
    scraper = OfflineMD()
    emitted = list(scraper.scrape(chamber=chamber, session=session))
    index_requests = [u for u in scraper.requested if INDEX in u]
    day_requests = [u for u in scraper.requested if INDEX not in u]
    return scraper, emitted, index_requests, day_requests


@pytest.mark.parametrize(
    "chamber,name,days", [("lower", "house", 81), ("upper", "senate", 76)]
)
def test_2026_regular_session_lists_its_session_days(chamber, name, days):
    _, _, index_requests, day_requests = run("2026", chamber)
    assert index_requests == [
        "http://mgaleg.maryland.gov/mgawebsite/FloorActions/Index/{}?ys=2026rs".format(
            name
        )
    ]
    assert len(day_requests) == days
    assert len(set(day_requests)) == days
    assert all(u.endswith("?year=2026RS") for u in day_requests)


def test_2026_day_page_roll_calls_reach_scrape_vote():
    scraper, emitted, _, _ = run("2026", "lower")
    expected = [
        "http://mgaleg.maryland.gov/2026RS/votes/house/0002.pdf",
        "http://mgaleg.maryland.gov/2026RS/votes/house/0003.pdf",
    ]
    assert scraper.votes_seen == expected
    assert emitted == expected


@pytest.mark.parametrize("session", ["2026s1", "2026S1"])
@pytest.mark.parametrize(
    "chamber,name,days", [("lower", "house", 4), ("upper", "senate", 5)]
)
def test_special_session_is_fetched_by_its_own_code(session, chamber, name, days):
    _, _, index_requests, day_requests = run(session, chamber)
    assert index_requests == [
        "http://mgaleg.maryland.gov/mgawebsite/FloorActions/Index/{}?ys=2026s1".format(
            name
        )
    ]
    assert len(day_requests) == days
    assert all(u.endswith("?year=2026S1") for u in day_requests)


def test_the_sites_default_index_is_empty():
    # why the fix is needed: the page the scraper used to read lists no session days
    scraper = OfflineMD()
    doc = scraper.lxmlize(
        "http://mgaleg.maryland.gov/mgawebsite/FloorActions/Index/house"
    )
    assert doc.xpath("//table[1]/tbody/tr/td[3]/a/@href") == []
