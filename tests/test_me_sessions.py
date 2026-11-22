"""OPEN-747: Maine's sessions mirror the legislature's own: the First and Second Regular Sessions
of each two-year Legislature and each special session, every one with its own dates, and every
bill and roll call is filed under exactly one of them.

The dates are the "Convened" and "Adjourned" days of each session's Legislative Statistics page
in the Laws of Maine (lldc.mainelegislature.org/Open/Laws/<year>/..._LegStats_<session>.pdf,
read 2026-11-21), copied here by hand from those pages, not from the scraper's list. The 122nd's
Second Regular Session has no statistics page; its dates are on the title page of its volume
(Laws2005v3_f0006_LegStats_S2.pdf: "SECOND REGULAR SESSION January 4, 2006 to May 24, 2006").

LawMakerWeb keeps one bill list per Legislature, so each session reads it and keeps a bill only
when the bill's first dated action falls in that session or, between sessions, before it
convenes (scrapers/me/sessions.py). The fixtures (tests/fixtures/me_open747/) are the site's own
Actions tabs (LawMakerWeb/dockets.asp?ID=<paper>, saved 2026-11-21, cut to the bill's name and
its action table). The session each bill is expected in is the one printed at the head of the
bill itself (bills/getPDF.asp, or the Law Library's copy lldc.mainelegislature.org/Open/LDs/),
e.g. "132nd MAINE LEGISLATURE / FIRST SPECIAL SESSION-2025" on LD 1223.

The roll calls are OPEN-698's saved rollcall.asp pages (tests/fixtures/me_open698/).
"""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import me  # noqa: E402
from me import Maine  # noqa: E402
from me.bills import MEBillScraper, first_action_date  # noqa: E402
from me.events import MEEventScraper  # noqa: E402
from me.sessions import session_for_bill  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

TESTS = os.path.dirname(__file__)
FIXTURES = os.path.join(TESTS, "fixtures", "me_open747")
ROLL_CALLS = os.path.join(TESTS, "fixtures", "me_open698")
BASE = "https://legislature.maine.gov/LawMakerWeb/"

# (identifier, classification, convened, adjourned), from the Legislative Statistics pages
LEGSTATS = [
    ("121R1", "primary", "2002-12-04", "2003-06-14"),
    ("121S1", "special", "2003-08-21", "2003-08-22"),
    ("121R2", "primary", "2004-01-07", "2004-01-30"),
    ("121S2", "special", "2004-02-03", "2004-04-30"),
    ("122R1", "primary", "2004-12-01", "2005-03-30"),
    ("122S1", "special", "2005-04-04", "2005-06-18"),
    ("122S2", "special", "2005-07-29", "2005-07-29"),
    ("122R2", "primary", "2006-01-04", "2006-05-24"),
    ("123R1", "primary", "2006-12-06", "2007-06-21"),
    ("123R2", "primary", "2008-01-02", "2008-03-31"),
    ("123S1", "special", "2008-04-01", "2008-04-18"),
    ("124R1", "primary", "2008-12-03", "2009-06-13"),
    ("124R2", "primary", "2010-01-06", "2010-04-12"),
    ("125R1", "primary", "2010-12-01", "2011-06-29"),
    ("125S1", "special", "2011-09-27", "2011-09-27"),
    ("125R2", "primary", "2012-01-04", "2012-05-31"),
    ("126R1", "primary", "2012-12-05", "2013-07-10"),
    ("126S1", "special", "2013-08-29", "2013-08-29"),
    ("126R2", "primary", "2014-01-08", "2014-05-02"),
    ("127R1", "primary", "2014-12-03", "2015-07-16"),
    ("127R2", "primary", "2016-01-06", "2016-04-29"),
    ("128R1", "primary", "2016-12-07", "2017-08-02"),
    ("128S1", "special", "2017-10-23", "2017-11-06"),
    ("128R2", "primary", "2018-01-03", "2018-05-02"),
    ("128S2", "special", "2018-06-19", "2018-09-13"),
    ("129R1", "primary", "2018-12-05", "2019-06-20"),
    ("129S1", "special", "2019-08-26", "2019-08-26"),
    ("129R2", "primary", "2020-01-08", "2020-03-17"),
    ("130R1", "primary", "2020-12-02", "2021-03-30"),
    ("130S1", "special", "2021-04-28", "2021-07-19"),
    ("130S2", "special", "2021-09-29", "2021-09-29"),
    ("130R2", "primary", "2022-01-05", "2022-05-09"),
    ("131R1", "primary", "2022-12-07", "2023-03-30"),
    ("131S1", "special", "2023-04-05", "2023-07-26"),
    ("131R2", "primary", "2024-01-03", "2024-05-10"),
    ("132R1", "primary", "2024-12-04", "2025-03-21"),
    ("132S1", "special", "2025-03-25", "2025-06-25"),
    ("132R2", "primary", "2026-01-07", "2026-04-29"),
]
ORDINAL = {"R1": "First Regular", "R2": "Second Regular"}
ORDINAL.update({"S1": "First Special", "S2": "Second Special"})


def _days(start, end):
    day = datetime.date.fromisoformat(start)
    while day <= datetime.date.fromisoformat(end):
        yield day
        day += datetime.timedelta(days=1)


def test_sessions_are_the_legislatures_own():
    assert [
        (s["identifier"], s["classification"], s["start_date"], s["end_date"])
        for s in Maine.legislative_sessions
    ] == LEGSTATS


@pytest.mark.parametrize(
    "session", Maine.legislative_sessions, ids=lambda s: s["identifier"]
)
def test_each_session_is_named_and_numbered_as_maine_does(session):
    number, code = int(session["identifier"][:3]), session["identifier"][3:]
    assert session["extras"]["legislature"] == number
    suffix = {121: "st", 122: "nd", 123: "rd", 131: "st", 132: "nd"}.get(number, "th")
    assert session["name"] == f"{number}{suffix} Legislature, {ORDINAL[code]} Session"
    # the site's menu names the Legislature; every one is listed on a regular session
    if session["classification"] == "primary":
        assert session["_scraped_name"] == f"{number}{suffix} Legislature"


def test_no_regular_session_includes_a_special_session_day_or_the_reverse():
    special_days, regular_days = set(), set()
    for s in Maine.legislative_sessions:
        days = set(_days(s["start_date"], s["end_date"]))
        (special_days if s["classification"] == "special" else regular_days).update(
            days
        )
    assert special_days and regular_days
    assert not special_days & regular_days
    # and no two sessions share a day at all
    total = sum(
        len(list(_days(s["start_date"], s["end_date"])))
        for s in Maine.legislative_sessions
    )
    assert total == len(special_days | regular_days)


def test_the_132nd_legislatures_three_sessions_are_switched_on(monkeypatch):
    # the LegSession menu of LawMakerWeb/advancedsearch.asp (read 2026-11-21)
    menu = ["2001-2002", "121st Legislature", "122nd Legislature", "123rd Legislature"]
    menu += [f"{n}th Legislature" for n in range(124, 131)]
    menu += ["131st Legislature", "132nd Legislature"]
    monkeypatch.setattr(me, "url_xpath", lambda url, xpath: menu)
    assert check_session_list(Maine()) == {"132R1", "132S1", "132R2"}


# Legislature, LD, the session printed at the head of the bill, and why
BILLS = [
    (
        132,
        1222,
        "132R1",
        "the last bill introduced in the First Regular Session (2025-03-20)",
    ),
    (
        132,
        216,
        "132R1",
        "introduced 2025-01-16, carried over into the First Special Session",
    ),
    (132, 1223, "132S1", "introduced on the First Special Session's first day"),
    (132, 1988, "132S1", "introduced 2025-06-13"),
    (
        132,
        1989,
        "132R2",
        "received 2025-12-03, a month before the Second Regular Session",
    ),
    (131, 2019, "131S1", "introduced 2023-07-06"),
    (131, 2020, "131R2", "received 2023-12-11, before the Second Regular Session"),
    (130, 1737, "130S1", "introduced on the First Special Session's last day"),
    (130, 1738, "130S2", "the Second Special Session's one day, 2021-09-29"),
    (
        130,
        1742,
        "130R2",
        "received 2021-11-30, between the special and the regular session",
    ),
    (129, 1847, "129S1", "the First Special Session's one day, 2019-08-26"),
    (129, 1853, "129R2", "received 2019-12-23"),
    (128, 1647, "128S1", "introduced on the First Special Session's first day"),
    (128, 1652, "128R2", "received 2017-11-29, after the First Special Session"),
    (123, 2187, "123R2", "introduced 2008-02-05; enacted in the First Special Session"),
    (122, 1693, "122S2", "the Second Special Session's one day, 2005-07-29"),
    (121, 1636, "121S1", "introduced on the First Special Session's first day"),
    (
        121,
        1640,
        "121R2",
        "received in December 2003, before the Second Regular Session",
    ),
]


def _docket(number, ld):
    (name,) = [
        f for f in os.listdir(FIXTURES) if f.startswith(f"dockets_{number}_LD{ld}_")
    ]
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return name.rsplit("_", 1)[1].split(".")[0], f.read()


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class OfflineBills(MEBillScraper):
    """The real _recursively_process_bills() over one page of search results for the bills
    above and their saved Actions tabs. scrape_bill() is replaced: it reads the summary,
    sponsor, roll-call, subject and text pages, none of which decides the session."""

    def __init__(self, tmp_path, papers):
        super().__init__(Maine(), str(tmp_path))
        self.papers = papers  # paper ID -> (LD, Actions tab)
        self.scraped = []

    def get(self, url, **kwargs):
        assert url.startswith(BASE + "dockets.asp?ID="), url
        return _Response(self.papers[url.split("=")[1]][1])

    def scrape_bill(self, bill, chamber):
        self.scraped.append(bill)
        # the Actions tab read for the session decision is kept, not fetched again
        self.scrape_actions(bill, BASE + "dockets.asp?ID=" + self.paper_of(bill))
        return iter(())

    def paper_of(self, bill):
        (paper,) = [
            p for p, (ld, _) in self.papers.items() if f"LD {ld}" == bill.identifier
        ]
        return paper


class _SearchSession:
    """LawMakerWeb's searchresults.asp: one page of results, then an empty one."""

    def __init__(self, papers):
        rows = "".join(
            f'<tr><td><b><a href="summary.asp?ID={p}">LD {ld}</a></b></td></tr>'
            for p, (ld, _) in papers.items()
        )
        self.pages = {1: f"<html><body><table>{rows}</table></body></html>"}

    def get(self, url, params, timeout):
        return _Response(self.pages.get(params["StartWith"], "<html></html>"))

    def post(self, url, data, timeout):
        # the search is started again once before an empty page is believed
        return _Response("")


def _bills_of(number, tmp_path, session):
    papers = {}
    for n, ld, _, _ in BILLS:
        if n == number:
            paper, html = _docket(n, ld)
            papers[paper] = (ld, html)
    scraper = OfflineBills(tmp_path, papers)
    scraper.dockets = {}
    scraper.seen = set()
    bills = list(
        scraper._recursively_process_bills(_SearchSession(papers), "lower", session)
    )
    assert [b.identifier for b in bills] == [b.identifier for b in scraper.scraped]
    assert all(b.legislative_session == session for b in bills)
    assert not scraper.dockets  # every kept Actions tab was used
    return {int(b.identifier.split()[1]) for b in bills}, bills


@pytest.mark.parametrize(
    "number,ld,owner,why", BILLS, ids=[f"{b[0]} LD {b[1]}" for b in BILLS]
)
def test_bill_lands_only_in_the_session_printed_on_it(number, ld, owner, why, tmp_path):
    _, html = _docket(number, ld)
    sessions = [
        s["identifier"]
        for s in Maine.legislative_sessions
        if s["extras"]["legislature"] == number
    ]
    assert (
        session_for_bill(Maine.legislative_sessions, number, first_action_date(html))
        == owner
    )
    for session in sessions:
        kept, _ = _bills_of(number, tmp_path, session)
        assert (ld in kept) == (session == owner), (session, why)


def test_carried_over_bill_keeps_its_later_actions(tmp_path):
    _, bills = _bills_of(132, tmp_path, "132R1")
    (ld216,) = [b for b in bills if b.identifier == "LD 216"]
    # its First Special Session action (2025-03-27) comes with it
    assert sorted({str(a["date"]) for a in ld216.actions}) == [
        "2025-01-16",
        "2025-03-21",
        "2025-03-27",
    ]


def test_first_action_is_the_earliest_date_not_the_first_row():
    html = (
        "<html><body><table><tr><td><div><b>Date</b></div></td><td>Chamber</td><td>Action</td></tr>"
        "<tr><td>4/2/2025</td><td>House</td><td>later</td></tr>"
        "<tr><td>3/20/2025</td><td>Senate</td><td>earlier</td></tr></table></body></html>"
    )
    assert first_action_date(html) == datetime.date(2025, 3, 20)


def test_bill_with_no_dated_action_belongs_to_no_session():
    html = "<html><body><table><tr><td><div><b>Date</b></div></td></tr></table></body></html>"
    assert first_action_date(html) is None
    assert session_for_bill(Maine.legislative_sessions, 132, None) is None
    # nor one first acted on after the Legislature's last session adjourned
    late = datetime.date(2026, 5, 1)
    assert session_for_bill(Maine.legislative_sessions, 132, late) is None


def _roll_call_page(fid):
    with open(os.path.join(ROLL_CALLS, f"rollcall_{fid}.html"), encoding="utf-8") as f:
        return f.read()


class OfflineVotes(MEBillScraper):
    def __init__(self, tmp_path, pages):
        super().__init__(Maine(), str(tmp_path))
        self.pages = pages

    def get(self, url, **kwargs):
        return _Response(self.pages[url])


# roll call (OPEN-698 fixture), its date, and the session sitting that day
ROLL_CALLS_132 = [
    ("280095829_House_4", "Feb. 11, 2025", "132R1"),
    (
        "280095665_House_59",
        "March 25, 2025",
        "132S1",
    ),  # the special session's first day
    ("280095733_Senate_651", "June 25, 2025", "132S1"),  # and its last
    (
        "280095566_Senate_963",
        "April 29, 2026",
        "132R2",
    ),  # the second session's last day
]


@pytest.mark.parametrize(
    "fid,day,sitting", ROLL_CALLS_132, ids=[r[0] for r in ROLL_CALLS_132]
)
def test_roll_call_is_filed_under_the_session_sitting_that_day(
    fid, day, sitting, tmp_path
):
    paper, chamber, rc = fid.split("_")
    url = BASE + f"rollcall.asp?ID={paper}&chamber={chamber}&serialnumber={rc}"
    page = _roll_call_page(fid)
    assert day in page
    # the bill is filed under the First Regular Session, where it was introduced
    bill = Bill("LD 1", legislative_session="132R1", chamber="lower", title="t")
    (vote,) = OfflineVotes(tmp_path, {url: page}).scrape_vote(bill, "Enactment", url)
    assert vote.legislative_session == sitting
    assert vote.bill == bill._id  # still linked to its bill


def test_roll_call_on_no_sitting_day_is_skipped(tmp_path):
    fid = "280095829_House_4"
    url = BASE + "rollcall.asp?ID=280095829&chamber=House&serialnumber=4"
    # the same page, dated 2025-03-23: between the First Regular and First Special Sessions
    page = _roll_call_page(fid).replace("Feb. 11, 2025", "March 23, 2025")
    assert "March 23, 2025" in page
    bill = Bill("LD 1", legislative_session="132R1", chamber="lower", title="t")
    assert (
        list(OfflineVotes(tmp_path, {url: page}).scrape_vote(bill, "Enactment", url))
        == []
    )


def test_events_ask_the_site_for_the_legislatures_number(tmp_path):
    seen = []

    class Stop(Exception):
        pass

    class OfflineEvents(MEEventScraper):
        def get(self, url, **kwargs):
            if "getCommittees" in url:
                seen.append(url)
                raise Stop
            return _Response("{}")

        def scrape_bills_by_event(self, end_date, start_date):
            return {}

    with pytest.raises(Stop):
        list(OfflineEvents(Maine(), str(tmp_path)).scrape(session="132S1"))
    assert seen == [
        "https://legislature.maine.gov/backend/breeze/data/getCommittees?legislature=132"
    ]
