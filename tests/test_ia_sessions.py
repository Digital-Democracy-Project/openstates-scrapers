"""OPEN-744, OPEN-745: Iowa's extraordinary sessions, read from their General Assembly's lists,
and the session check accepts the list legis.iowa.gov serves now.

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
"Reports received after adjournment". The site has no list of their own for them:
findLegislation and the BillBook's General Assembly menu list only General Assemblies, their
bills are numbered in the General Assembly's sequence and listed on its bill list, and their
journals are filed in its journal list. Since OPEN-745 each is a session of its own (Ramon
2026-11-21: "Separate sessions, own dates"), and so is each year of a General Assembly ("Two
yearly sessions, bills by filing year"). Every one of them reads its General Assembly's lists and
keeps only its own bills and journals (tests/test_ia_special_sessions.py); the regular session of
the same year leaves the extraordinary session's out.

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
from ia.votes import IAVoteScraper  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open744")

# session identifier, General Assembly, the journal list it is filed in (session=1 or 2),
# its one day, its bills as the journals name them, and the regular session of its year
EXTRAORDINARY = [
    ("2021s1", "89", 1, "2021-10-05", ["SF 620"], "2021"),
    (
        "2021s2",
        "89",
        1,
        "2021-10-28",
        ["HF 901", "HF 902", "SF 621", "SF 622"],
        "2021",
    ),
    ("2023s1", "90", 1, "2023-07-11", ["HF 732", "SF 579"], "2023"),
    ("2026s1", "91", 2, "2026-10-02", ["HF 2801", "SF 2508"], "2026"),
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
    assert check_session_list(jurisdiction) == {"2025", "2026"}


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
    assert check_session_list(jurisdiction) == {"2025", "2026"}


def test_each_extraordinary_session_is_a_session_of_its_own():
    sessions = ia.Iowa.legislative_sessions
    regular = [s for s in sessions if s["classification"] == "primary"]
    special = [s for s in sessions if s["classification"] != "primary"]
    # one regular entry per year, two per General Assembly, each filed under it as the site
    # lists it
    assert [(s["identifier"], s["_scraped_name"]) for s in regular] == [
        (str(year), "General Assembly: {}".format(84 + (year - 2011) // 2))
        for year in range(2011, 2029)
    ]
    # and one special entry per extraordinary session, which the site does not list
    assert [s["identifier"] for s in special] == [e[0] for e in EXTRAORDINARY]
    assert {s["classification"] for s in special} == {"special"}
    assert not any("_scraped_name" in s for s in special)


@pytest.mark.parametrize("identifier,ga,sub,day,bills,assembly", EXTRAORDINARY, ids=IDS)
def test_the_journals_record_a_one_day_extraordinary_session(
    identifier, ga, sub, day, bills, assembly
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
    # its session spans that day only, and is filed under its General Assembly on the site
    assert (session(identifier)["start_date"], session(identifier)["end_date"]) == (
        day,
        day,
    )
    assert str(session(identifier)["extras"]["ordinal"]) == ga
    assert session(assembly)["_scraped_name"] == "General Assembly: " + ga


class OfflineBills(IABillScraper):
    """Serves the saved bill lists through the real scrape(); records each bill."""

    def __init__(self):
        self.jurisdiction = ia.Iowa()
        self.requested = []
        self.bills = []

    def scrape_prefiles(self, session):
        # the pre-filed list is one page for all sessions, not addressed by session
        return iter(())

    def get(self, url, **kwargs):
        self.requested.append(url)
        if "/findLegislation/allbills?" in url:
            name = "allbills_{}.html".format(url.rsplit("ga=", 1)[1])
            if os.path.exists(os.path.join(FIXTURES, name)):
                return _FakeResponse(read(name))
            return _FakeResponse("<table id='sortableTable'><tbody></tbody></table>")
        # the BillBook page, read for its HSB/SSB study bills; none in the saved lists
        return _FakeResponse("<html></html>")

    def scrape_bill(self, chamber, session, session_id, bill_id, url, *args, **kwargs):
        self.bills.append((session, bill_id, url))
        return bill_id


@pytest.mark.parametrize("identifier,ga,sub,day,bills,assembly", EXTRAORDINARY, ids=IDS)
def test_the_bills_scraper_reads_the_extraordinary_sessions_bills(
    identifier, ga, sub, day, bills, assembly
):
    scraper = OfflineBills()
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
        self.jurisdiction = ia.Iowa()
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


@pytest.mark.parametrize("identifier,ga,sub,day,bills,assembly", EXTRAORDINARY, ids=IDS)
@pytest.mark.parametrize(
    "chamber,name,code", [("lower", "house", "HJNL"), ("upper", "senate", "SJNL")]
)
def test_the_votes_scraper_reads_the_extraordinary_sessions_journal(
    chamber, name, code, identifier, ga, sub, day, bills, assembly
):
    scraper = OfflineVotes()
    journals = list(scraper.scrape_chamber(chamber, identifier))
    url = "https://www.legis.iowa.gov/legislation/journals/" + name
    assert scraper.requested == [
        (url, {"ga": ga, "session": 1}),
        (url, {"ga": ga, "session": 2}),
    ]
    filename = "{}_{}.pdf".format(day.replace("-", ""), code)
    journal = "https://www.legis.iowa.gov/docs/publications/{}/{}".format(
        code, filename
    )
    # the extraordinary session's scrape reads that day's journal and no other
    assert journals == [(journal, chamber, identifier, day)]
    # and the regular session of that year reads the same lists but leaves that journal out
    scraper = OfflineVotes()
    journals = list(scraper.scrape_chamber(chamber, assembly))
    assert scraper.requested == [
        (url, {"ga": ga, "session": 1}),
        (url, {"ga": ga, "session": 2}),
    ]
    assert journals
    assert journal not in [j[0] for j in journals]
    assert {j[2] for j in journals} == {assembly}


@pytest.mark.parametrize("identifier", ["2027", "2028"])
def test_general_assembly_92s_years_are_addressed_as_ga_92(identifier):
    # both scrapers can address them when they are switched on
    scraper = OfflineBills()
    list(scraper.scrape(session=identifier))
    assert scraper.requested[0].endswith("/findLegislation/allbills?ga=92")
    votes = OfflineVotes()
    list(votes.scrape_chamber("lower", identifier))
    assert votes.requested[0][1] == {"ga": "92", "session": 1}
    s = session(identifier)
    assert (s["classification"], s["active"]) == ("primary", False)
    assert datetime.strptime(s["start_date"], "%Y-%m-%d").date() > date(2026, 11, 21)
