"""OPEN-744: Iowa's extraordinary sessions are scraped inside their General Assembly, and the
session check accepts the list legis.iowa.gov serves now.

The legislature's journals record four extraordinary sessions in the General Assemblies the
scraper lists (84 to 91), each convened by the Governor's proclamation and adjourned sine die the
same day:

* 2021-10-05, the 2021 Extraordinary Session of the 89th General Assembly;
* 2021-10-28, the 2021 Second Extraordinary Session of the 89th;
* 2023-07-11, the 2023 Extraordinary Session of the 90th;
* 2026-10-02, the 2026 Extraordinary Session of the 91st (the proclamation is in that day's
  House journal).

They were found by reading every House and Senate journal list the votes scraper reads
(legislation/journals/<chamber>?ga=84..91&session=1|2, 32 pages) for a journal outside the
regular session, then reading those journals; every other late journal is a "Supplement" or
"Reports received after adjournment". The site has no session of their own for them:
findLegislation and the BillBook's General Assembly menu list only General Assemblies, their
bills are numbered in the General Assembly's sequence and listed on its bill list, and their
journals are filed in its journal list. So the scraper reads them as part of their General
Assembly, and none is added as a separate session: one would have no page of its own to scrape.

The fixtures are the site's own pages, saved 2026-11-21 and trimmed to what the scrapers read:

* find_legislation.html: the General Assembly list of legislation/findLegislation (the page
  get_session_list reads).
* allbills_<ga>.html: findLegislation/allbills?ga=<ga> (the bills scraper's list), its first two
  rows and the extraordinary sessions' bills.
* journals_<chamber>_<ga>_<session>.html: legislation/journals/<chamber>?ga=..&session=.. (the
  votes scraper's list), the table of journals.
* <yyyymmdd>_HJNL.txt, <yyyymmdd>_SJNL.txt: each extraordinary session's House and Senate journal
  (docs/publications/HJNL|SJNL/<yyyymmdd>_HJNL|SJNL.pdf, pdftotext -layout), cut to its opening
  and its final adjournment.
"""
import logging
import os
import re
import sys
from datetime import date, datetime

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ia  # noqa: E402
from ia.bills import IABillScraper  # noqa: E402
from ia.votes import SITE_IDS, IAVoteScraper  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open744")

# session identifier, General Assembly, the journal list it is filed in (session=1 or 2),
# its one day, and its bills as the journals name them
EXTRAORDINARY = [
    ("2021-2022", "89", 1, "2021-10-05", ["SF 620"]),
    ("2021-2022", "89", 1, "2021-10-28", ["HF 901", "HF 902", "SF 621", "SF 622"]),
    ("2023-2024", "90", 1, "2023-07-11", ["HF 732", "SF 579"]),
    ("2025-2026", "91", 2, "2026-10-02", ["HF 2801", "SF 2508"]),
]
IDS = [e[3] for e in EXTRAORDINARY]


def read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def session(identifier):
    (found,) = [
        s for s in ia.Iowa.legislative_sessions if s["identifier"] == identifier
    ]
    return found


class _FakeResponse:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200

    def raise_for_status(self):
        pass


def test_session_check_accepts_the_sites_current_list(monkeypatch):
    page = read("find_legislation.html")
    # under the real url_xpath(), so get_session_list's own XPath reads the saved list
    monkeypatch.setattr(
        requests.Session, "get", lambda self, url, **kw: _FakeResponse(page)
    )
    jurisdiction = ia.Iowa()
    scraped = jurisdiction.get_session_list()
    assert scraped == ["General Assembly: {}".format(n) for n in range(91, 75, -1)]
    # openstates-core's own check: it raises on a listed session the scraper does not know,
    # and returns the active identifiers otherwise
    assert check_session_list(jurisdiction) == {"2025-2026"}


def test_session_check_accepts_general_assembly_92_once_listed(monkeypatch):
    # the site's list with General Assembly 92 added above 91, as it will read in 2027
    page = read("find_legislation.html")
    item = re.search(r'<li class="select nocsscolor" data-ga="91">.*?</li>', page, re.S)
    page = page.replace(
        item.group(0), item.group(0).replace("91", "92") + item.group(0)
    )
    monkeypatch.setattr(
        requests.Session, "get", lambda self, url, **kw: _FakeResponse(page)
    )
    jurisdiction = ia.Iowa()
    assert "General Assembly: 92" in jurisdiction.get_session_list()
    assert check_session_list(jurisdiction) == {"2025-2026"}


def test_no_extraordinary_session_is_a_session_of_its_own():
    sessions = ia.Iowa.legislative_sessions
    assert {s["classification"] for s in sessions} == {"primary"}
    # one entry per General Assembly, each named as the site lists it
    assert [s["_scraped_name"] for s in sessions] == [
        "General Assembly: {}".format(n) for n in range(84, 93)
    ]


@pytest.mark.parametrize("identifier,ga,sub,day,bills", EXTRAORDINARY, ids=IDS)
def test_the_journals_record_a_one_day_extraordinary_session(
    identifier, ga, sub, day, bills
):
    when = date.fromisoformat(day)
    spoken = "{}, {} {}, {}".format(
        when.strftime("%A"), when.strftime("%B"), when.day, when.year
    )
    for chamber in ("HJNL", "SJNL"):
        text = " ".join(read("{}_{}.txt".format(day.replace("-", ""), chamber)).split())
        opening, adjournment = text.split("[...]")
        # convened that day by the Governor's proclamation in an extraordinary session
        assert spoken.lower() in opening.lower()
        assert "Pursuant to the proclamation of the Governor" in opening
        assert "Extraordinary Session" in opening
        # and adjourned sine die the same day (the Senate's journal of that day)
        assert "FINAL ADJOURNMENT" in adjournment
        assert re.search(
            r"declared the {} (Second )?Extraordinary Session of the .+ adjourned sine die".format(
                when.year
            ),
            adjournment,
        )
        if chamber == "HJNL":
            assert "the day of {}, having arrived".format(spoken) in adjournment
    # it falls within its General Assembly's two years
    first, second = identifier.split("-")
    assert int(first) <= when.year <= int(second)
    assert session(identifier)["_scraped_name"] == "General Assembly: " + ga


class OfflineBills(IABillScraper):
    """Serves the saved bill lists through the real scrape(); records each bill."""

    def __init__(self, monkeypatch):
        self.jurisdiction = ia.Iowa()
        self.requested = []
        self.bills = []

        def fake_get(_session, url, **kw):
            self.requested.append(url)
            ga = url.rsplit("ga=", 1)[1]
            name = "allbills_{}.html".format(ga)
            if os.path.exists(os.path.join(FIXTURES, name)):
                return _FakeResponse(read(name))
            return _FakeResponse("<table id='sortableTable'><tbody></tbody></table>")

        monkeypatch.setattr(requests.Session, "get", fake_get)

    def scrape_prefiles(self, session):
        # the pre-filed list is one page for all sessions, not addressed by session
        return iter(())

    def get(self, url, **kwargs):
        # the BillBook page, read for its HSB/SSB study bills; none in the saved lists
        self.requested.append(url)
        return _FakeResponse("<html></html>")

    def scrape_bill(self, chamber, session, session_id, bill_id, url, *args):
        self.bills.append((session, bill_id, url))
        return bill_id


@pytest.mark.parametrize("identifier,ga,sub,day,bills", EXTRAORDINARY, ids=IDS)
def test_the_bills_scraper_reads_the_extraordinary_sessions_bills(
    monkeypatch, identifier, ga, sub, day, bills
):
    scraper = OfflineBills(monkeypatch)
    list(scraper.scrape(session=identifier))
    assert scraper.requested == [
        "https://www.legis.iowa.gov/legislation/findLegislation/allbills?ga=" + ga,
        "https://www.legis.iowa.gov/legislation/BillBook?ga=" + ga,
    ]
    scraped = {b[1]: b for b in scraper.bills}
    for bill in bills:
        assert scraped[bill][0] == identifier
        assert scraped[bill][2] == (
            "https://www.legis.iowa.gov/legislation/BillBook?ga={}&ba={}".format(
                ga, bill.replace(" ", "")
            )
        )


class OfflineVotes(IAVoteScraper):
    """Serves the saved journal lists through the real scrape_chamber(); records each journal."""

    def __init__(self):
        self.requested = []
        # the bound journals and indexes in the list are skipped with a log line
        self.logger = logging.getLogger("ia-votes-test")

    def get(self, url, params=None, **kwargs):
        self.requested.append((url, params))
        name = "journals_{}_{}_{}.html".format(
            url.rsplit("/", 1)[1], params["ga"], params["session"]
        )
        if os.path.exists(os.path.join(FIXTURES, name)):
            return _FakeResponse(read(name))
        return _FakeResponse("<html></html>")

    def scrape_journal(self, url, chamber, session, date):
        return (url, chamber, session, date.date().isoformat())


@pytest.mark.parametrize("identifier,ga,sub,day,bills", EXTRAORDINARY, ids=IDS)
@pytest.mark.parametrize(
    "chamber,name,code", [("lower", "house", "HJNL"), ("upper", "senate", "SJNL")]
)
def test_the_votes_scraper_reads_the_extraordinary_sessions_journal(
    chamber, name, code, identifier, ga, sub, day, bills
):
    scraper = OfflineVotes()
    journals = list(scraper.scrape_chamber(chamber, identifier))
    url = "https://www.legis.iowa.gov/legislation/journals/" + name
    assert scraper.requested == [
        (url, {"ga": ga, "session": 1}),
        (url, {"ga": ga, "session": 2}),
    ]
    filename = "{}_{}.pdf".format(day.replace("-", ""), code)
    assert (
        "https://www.legis.iowa.gov/docs/publications/{}/{}".format(code, filename),
        chamber,
        identifier,
        day,
    ) in journals


def test_2027_2028_is_addressed_as_general_assembly_92(monkeypatch):
    # both scrapers can address it when it is switched on
    assert SITE_IDS["2027-2028"] == "92"
    scraper = OfflineBills(monkeypatch)
    list(scraper.scrape(session="2027-2028"))
    assert scraper.requested[0].endswith("/findLegislation/allbills?ga=92")
    s = session("2027-2028")
    assert (s["classification"], s["active"]) == ("primary", False)
    assert datetime.strptime(s["start_date"], "%Y-%m-%d").date() > date(2026, 11, 21)
