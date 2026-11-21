"""OPEN-742: Maryland's session list accepts the session menu mgaleg.maryland.gov serves now.

The menu (mgawebsite/Search/Legislation, the page get_session_list reads) added "2026 Special
Session" (2026s1) and "2027 Regular Session". openstates-core's check_session_list stops the
whole scrape when the site lists a session the scraper neither has nor ignores.

The fixtures are the site's own pages saved 2026-11-21, trimmed to the part the scraper reads:

* session_menu.html: the session <select> of Search/Legislation (41 sessions).
* legislation_<chamber>_2026s1.html: Legislation/Index/<chamber>?ys=2026s1, three bills each
  (HB2100-HB2102, SB2100-SB2102).
* legislation_<chamber>_2025s1.html: the same for 2025s1, which lists no bills.

The votes scraper's handling of 2026s1 (?ys=2026s1, its own session days) is tested in
test_md_votes_session.py (OPEN-717) on the site's saved floor-action pages.
"""
import datetime
import os
import sys
from urllib.parse import parse_qs, urlparse

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import md  # noqa: E402
from md.bills import MDBillScraper  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "md_open742")
LIST_PATH = "/mgawebsite/Legislation/Index/"


def read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def session(identifier):
    (found,) = [
        s for s in md.Maryland.legislative_sessions if s["identifier"] == identifier
    ]
    return found


class _FakeResponse:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        pass


def test_session_check_accepts_the_sites_current_menu(monkeypatch):
    page = read("session_menu.html")
    # under the real url_xpath(), so its own XPath reads the saved menu
    monkeypatch.setattr(
        requests.Session, "get", lambda self, url, **kw: _FakeResponse(page)
    )
    jurisdiction = md.Maryland()
    scraped = jurisdiction.get_session_list()
    assert len(scraped) == 41
    assert {"2026 Special Session", "2025 Special Session"} <= set(scraped)
    # openstates-core's own check: it raises on a listed session the scraper does not know,
    # and returns the active identifiers otherwise
    assert check_session_list(jurisdiction) == {"2026", "2026s1"}


def test_2026s1_is_the_sites_special_session_on_its_sitting_days():
    s = session("2026s1")
    assert s["_scraped_name"] == "2026 Special Session"
    assert s["classification"] == "special"
    # the floor-action indexes list sittings on August 3 and 4, 2026 (both chambers)
    assert (s["start_date"], s["end_date"]) == ("2026-08-03", "2026-08-04")
    assert s["active"] is True


def test_2027_dates_follow_the_constitutions_rule():
    # Md. Constitution Art. III, Sec. 14: from the second Wednesday of January, for 90 days
    january = [datetime.date(2027, 1, d) for d in range(1, 32)]
    start = [d for d in january if d.weekday() == 2][1]
    s = session("2027")
    assert s["_scraped_name"] == "2027 Regular Session"
    assert s["classification"] == "primary"
    assert s["start_date"] == start.isoformat()
    assert s["end_date"] == (start + datetime.timedelta(days=89)).isoformat()
    # no 2027 bills on the site yet (2026-11-21): switched on once pre-files appear
    assert not s.get("active")


def test_2025_special_session_stays_ignored():
    assert "2025 Special Session" in md.Maryland.ignored_scraped_sessions
    assert "2025s1" not in {s["identifier"] for s in md.Maryland.legislative_sessions}


class OfflineBills(MDBillScraper):
    """Serves the saved bill lists through the real scrape_chamber(); records each bill."""

    def __init__(self):
        self.requested = []
        self.bills = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        parsed = urlparse(url)
        assert parsed.path.startswith(LIST_PATH), url
        chamber = parsed.path[len(LIST_PATH) :]
        code = parse_qs(parsed.query)["ys"][0].lower()
        return _FakeResponse(read("legislation_{}_{}.html".format(chamber, code)))

    def scrape_bill(self, chamber, session, url):
        self.bills.append((chamber, session, url))
        yield url


@pytest.mark.parametrize(
    "chamber,name,prefix", [("lower", "house", "hb"), ("upper", "senate", "sb")]
)
def test_bills_scraper_reads_2026s1s_own_bill_list(chamber, name, prefix):
    scraper = OfflineBills()
    list(scraper.scrape_chamber(chamber, "2026s1"))
    assert scraper.requested == [
        "http://mgaleg.maryland.gov/mgawebsite/Legislation/Index/{}?ys=2026s1".format(
            name
        )
    ]
    assert [b[:2] for b in scraper.bills] == [(chamber, "2026s1")] * 3
    assert [urlparse(b[2]).path for b in scraper.bills] == [
        "/mgawebsite/Legislation/Details/{}{}".format(prefix, n)
        for n in (2100, 2101, 2102)
    ]
    assert all("ys=2026S1" in b[2] for b in scraper.bills)


@pytest.mark.parametrize("chamber", ["lower", "upper"])
def test_2025s1_lists_no_bills(chamber):
    # why 2025s1 stays ignored: neither chamber's bill list has a bill
    scraper = OfflineBills()
    assert list(scraper.scrape_chamber(chamber, "2025s1")) == []
