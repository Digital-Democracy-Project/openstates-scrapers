"""OPEN-758: every Oklahoma bill and roll call is filed under its own yearly session (the Iowa
rule, OPEN-745; Ramon 2026-11-21: "bills by filing year").

The legislature's search form (webapps.oklegislature.gov/WebApplication3/WebForm1.aspx, the form
the bills scraper posts) keeps a Legislature's whole record under its second year: the 2026
Regular Session (code 2600) lists every 2025 bill too (3,706 House and 2,322 Senate measures,
against 2,017 and 1,256 under 2500, all of them also in 2600), and only the 2600 pages carry a
carried-over bill's 2026 actions (HB 1002: 18 actions to 2026-04-16 under 2600, 7 to 2025-03-10
under 2500). So both years read the 2600 list and keep only their own (scrapers/ok/sessions.py):

* HB 1002, first read 2025-02-03 and still moving in 2026, is filed under 2025 with its 2026
  actions; its 2025 roll calls go to 2025 and its 2026 ones to 2026, all linked to it;
* HB 2929, first read 2026-02-02, is filed under 2026;
* SR 34 sits in the 2025 list as an empty row but was first acted on 2026-03-16: it goes to 2026.
  The 2025 list is not a reliable record of 2025's bills; the first dated action is.

The fixtures (tests/fixtures/ok_open758/) are the site's own pages, saved 2026-11-22:

* search_2600_house.html, search_2600_senate.html: the form's result for the 2026 Regular
  Session (House HB/HJR/HCR/HR, Senate SB/SJR/SCR/SR), cut to the rows named above;
* billinfo_<bill>_2600.html: www.oklegislature.gov/BillInfo.aspx?Bill=<bill>&session=2600, without
  its scripts, styles and form state;
* votes_<bill>_<chamber>.htm: oklegislature.gov/cf/2025-26 SUPPORT DOCUMENTS/votes/<chamber>/
  <bill>_VOTES.HTM, as served;
* form_sessions.html: the form's session menu (what get_session_list reads).
"""
import datetime
import os
import re
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ok  # noqa: E402
from ok.bills import OKBillScraper  # noqa: E402
from ok.sessions import listing_session, session_for_day  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ok_open758")
SESSIONS = ok.Oklahoma.legislative_sessions
FORM = "<html><body><form><input type='hidden' name='__VIEWSTATE' value=''/></form></body></html>"


def read(name):
    raw = open(os.path.join(FIXTURES, name), "rb").read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


class _Response:
    def __init__(self, text):
        self.text = text
        self.status_code = 200


class OfflineBills(OKBillScraper):
    """The real scrape_chamber() and scrape_bill() over saved pages; `edit` can change a bill
    page before it is read."""

    def __init__(self, tmp_path, monkeypatch, edit=None):
        super().__init__(ok.Oklahoma(), str(tmp_path))
        self.posted = []
        self.edit = edit or (lambda bill, text: text)
        listing = {
            "lower": "search_2600_house.html",
            "upper": "search_2600_senate.html",
        }

        def post(session, url, data=None, **kw):
            self.posted.append(data["cbxSessionId"])
            house = any(t.startswith("H") for t in data["lbxTypes"])
            return _Response(read(listing["lower" if house else "upper"]))

        monkeypatch.setattr(
            requests.Session, "get", lambda s, url, **kw: _Response(FORM)
        )
        monkeypatch.setattr(requests.Session, "post", post)

    def get(self, url, **kwargs):
        if "WebForm1.aspx" in url:
            return _Response(FORM)
        votes = re.search(r"votes/(House|Senate)/(\w+)_VOTES\.HTM", url)
        if votes:
            return _Response(read("votes_{}_{}.htm".format(votes[2], votes[1])))
        bill, code = re.search(r"Bill=(\w+)&session=(\w+)", url).groups()
        name = "billinfo_{}_{}.html".format(bill, code)
        return _Response(self.edit(bill, read(name)))


def scrape(tmp_path, monkeypatch, session, chamber, edit=None):
    scraper = OfflineBills(tmp_path, monkeypatch, edit)
    items = list(scraper.scrape_chamber(chamber, session, None))
    bills = {i.identifier: i for i in items if isinstance(i, Bill)}
    votes = [i for i in items if not isinstance(i, Bill)]
    return scraper, bills, votes


def test_a_carried_over_bill_is_filed_under_its_filing_year(tmp_path, monkeypatch):
    scraper, bills, votes = scrape(tmp_path, monkeypatch, "2025", "lower")
    # the 2025 scrape reads the 2026 list, the one that carries 2025's bills with their 2026
    # actions
    assert scraper.posted == ["2600"]
    assert set(bills) == {"HB1002"}
    hb1002 = bills["HB1002"]
    assert hb1002.legislative_session == "2025"
    dates = [a["date"] for a in hb1002.actions]
    assert min(dates) == "2025-02-03" and max(dates) == "2026-04-16"
    # its roll calls, each filed under the session of its own date and linked to the bill
    filed = sorted((v.start_date, v.legislative_session) for v in votes)
    assert filed == [
        ("2025-02-19", "2025"),
        ("2025-03-06", "2025"),
        ("2026-03-24", "2026"),
        ("2026-04-07", "2026"),
    ]
    assert {v.bill for v in votes} == {hb1002._id}


def test_a_2026_bill_is_filed_under_2026(tmp_path, monkeypatch):
    scraper, bills, votes = scrape(tmp_path, monkeypatch, "2026", "lower")
    assert scraper.posted == ["2600"]
    assert set(bills) == {"HB2929"}
    assert bills["HB2929"].legislative_session == "2026"
    assert votes and {v.legislative_session for v in votes} == {"2026"}
    assert {v.bill for v in votes} == {bills["HB2929"]._id}


def test_no_bill_is_filed_under_two_sessions(tmp_path, monkeypatch):
    filed = []
    for session in ("2025", "2026"):
        for chamber in ("lower", "upper"):
            _, bills, _ = scrape(tmp_path, monkeypatch, session, chamber)
            filed += [(b, session) for b in bills]
    assert sorted(filed) == [("HB1002", "2025"), ("HB2929", "2026"), ("SR34", "2026")]


def test_a_number_in_the_2025_list_first_acted_on_in_2026_goes_to_2026(
    tmp_path, monkeypatch
):
    _, bills, _ = scrape(tmp_path, monkeypatch, "2026", "upper")
    assert bills["SR34"].legislative_session == "2026"
    _, bills, _ = scrape(tmp_path, monkeypatch, "2025", "upper")
    assert bills == {}


def test_a_bill_with_no_dated_action_is_left_out(tmp_path, monkeypatch):
    def no_actions(bill, text):
        # the action table without its rows
        return re.sub(
            r"(<table[^>]*tblHouseActions[^>]*>)(.*?)(</table>)",
            lambda m: m[1] + "<tr></tr><tr></tr>" + m[3],
            text,
            flags=re.S | re.I,
        )

    for session in ("2025", "2026"):
        _, bills, votes = scrape(tmp_path, monkeypatch, session, "lower", no_actions)
        assert bills == {} and votes == []


@pytest.mark.parametrize(
    "session,listing",
    [
        ("2025", "2026"),
        ("2026", "2026"),
        ("2011", "2012"),
        ("2017", "2018"),
        ("2019", "2020"),
        ("2023", "2024"),
        ("2027", "2027"),  # 2028 is not in the list yet
        ("2023S1", "2023S1"),
        ("2012SS1", "2012SS1"),
    ],
)
def test_each_session_reads_its_legislatures_newest_list(session, listing):
    assert listing_session(SESSIONS, session) == listing


@pytest.mark.parametrize(
    "session,day,owner",
    [
        (
            "2026",
            "2025-02-03",
            "2025",
        ),  # the first year, read by the second year's scrape
        ("2025", "2025-05-30", "2025"),  # 2025's sine die
        ("2025", "2025-12-01", "2026"),  # between the two years: filed for the second
        ("2025", "2026-02-02", "2026"),
        (
            "2026",
            "2026-06-01",
            "2026",
        ),  # after the Legislature's last close: its last year
        ("2027", "2027-03-01", "2027"),
        ("2011", "2012-03-01", "2012"),
        ("2024S3", "2024-03-01", "2024S3"),  # a special session's own, alongside 2024's
        ("2024", "2024-03-01", "2024"),  # and 2024's own the same day
    ],
)
def test_the_session_of_a_day(session, day, owner):
    day = datetime.date.fromisoformat(day)
    assert session_for_day(SESSIONS, session, day) == owner


def test_one_regular_session_per_year_and_the_odd_years_are_no_longer_ignored():
    regular = sorted(
        s["identifier"] for s in SESSIONS if s["classification"] == "primary"
    )
    assert regular == [str(y) for y in range(2011, 2028)]
    names = {s["_scraped_name"] for s in SESSIONS}
    for year in (2011, 2013, 2015, 2017):
        name = "{} Regular Session".format(year)
        assert name in names
        assert name not in ok.Oklahoma.ignored_scraped_sessions
    for year in range(2011, 2028):
        assert str(year) in OKBillScraper.meta_session_id


def test_the_session_check_accepts_the_menu_and_2025_and_2026_are_active(monkeypatch):
    import utils

    menu = read("form_sessions.html")

    def url_xpath(url, path, verify=None, user_agent=None):
        from lxml import html

        return html.fromstring(menu).xpath(path)

    monkeypatch.setattr(utils, "url_xpath", url_xpath)
    jurisdiction = ok.Oklahoma()
    assert "2011 Regular Session" in jurisdiction.get_session_list()
    assert check_session_list(jurisdiction) == {"2025", "2026"}
