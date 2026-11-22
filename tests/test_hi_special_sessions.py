"""OPEN-748: Hawaii's special sessions are sessions of their own, and 2011 and 2012 are two regular
sessions (Ramon 2026-11-21: "regular session and special session are two different things. don't
ever mix their dates together"; "Sessions now, bills later"; "All 28", which on the journals'
own count is 27).

The 27 special sessions since 2011, with the dates on each Senate journal's title page
(data.capitol.hawaii.gov/sessions/journal/Senate/<year>/Senate_Journal_<year>_..._Special_Session.pdf,
read 2026-11-21: "Special Session of 2011, Convened Wednesday, August 31, 2011, Adjourned
Thursday, September 1, 2011", ...), are written out in SPECIAL below, apart from the list in
hi/__init__.py. The site's bill lists and measure pages hold only regular measures, so a special
session's own measures are read from its PDFs instead (OPEN-751, test_hi_special_session_bills.py;
the Senate-only sessions have none). A roll call a regular measure page dates on a
special-session day is filed under that special session and stays linked to its regular bill.

The fixtures are the site's own pages:

* hi_open709/HB862-2021.html (OPEN-709): HB 862 of 2021, whose House and Senate veto overrides
  were taken on 7/6/2021 in the Special Session of 2021 ("Act 001, Special Session 2021");
* hi_open748/ (saved 2026-11-21, scripts and hidden form fields removed):
  SB41-2011.html and SB41-2012.html, measure_indiv_Archives.aspx?billtype=SB&billnumber=41 with
  year=2011 and year=2012 (SB 41 was introduced in 2011 and carried over; only the 2012 page has
  its two 2012 actions, of 4/13/2012); SB2001-2012.html, a 2012 bill, and HB2039-2012.html, the
  companion it lists; report-sb-2011.html and report-sb-2012.html, the advreports Senate-bill
  lists (advreport.aspx?report=deadline&measuretype=sb&year=...), cut to the rows of SB 2 (2011
  only) and SB 41 (both lists) and of SB 41 and SB 2001; archives-main.html, the year menu of
  session/archives/main.aspx (the page get_session_list reads), cut to the menu.
"""
import logging
import os
import sys
from datetime import date

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import hi  # noqa: E402
from hi import members as hi_members  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402
from openstates.exceptions import EmptyScrape  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

TESTS = os.path.dirname(__file__)
FIX709 = os.path.join(TESTS, "fixtures", "hi_open709")
FIX748 = os.path.join(TESTS, "fixtures", "hi_open748")

# identifier, convened, adjourned (Senate journal title pages); * = the House sat too
SPECIAL = [
    ("2011 Special Session", "2011-08-31", "2011-09-01"),
    ("2012 Special Session", "2012-06-28", "2012-06-29"),
    ("2013 Special Session", "2013-08-05", "2013-08-06"),
    ("2013 Second Special Session", "2013-10-28", "2013-11-12"),  # *
    ("2014 Special Session", "2014-10-22", "2014-10-23"),
    ("2015 Special Session", "2015-11-05", "2015-11-06"),
    ("2016 Special Session", "2016-06-23", "2016-06-24"),
    ("2016 Second Special Session", "2016-07-12", "2016-07-20"),  # *
    ("2016 Third Special Session", "2016-09-13", "2016-09-14"),
    ("2017 Special Session", "2017-08-28", "2017-09-01"),  # *
    ("2017 Second Special Session", "2017-09-25", "2017-09-26"),
    ("2017 Third Special Session", "2017-11-14", "2017-11-15"),
    ("2018 Special Session", "2018-07-09", "2018-07-10"),
    ("2018 Second Special Session", "2018-10-24", "2018-10-25"),
    ("2019 Special Session", "2019-09-16", "2019-09-17"),
    ("2019 Second Special Session", "2019-11-12", "2019-11-13"),
    ("2020 Special Session", "2020-10-05", "2020-10-06"),
    ("2020 Second Special Session", "2020-11-18", "2020-11-19"),
    ("2021 Special Session", "2021-07-06", "2021-07-08"),  # *
    ("2021 Second Special Session", "2021-07-28", "2021-08-27"),
    ("2021 Third Special Session", "2021-10-28", "2021-10-29"),
    ("2022 Special Session", "2022-06-20", "2022-06-21"),
    ("2022 Second Special Session", "2022-08-22", "2022-08-23"),
    ("2022 Third Special Session", "2022-10-19", "2022-10-20"),
    ("2023 Special Session", "2023-08-21", "2023-08-22"),
    ("2023 Second Special Session", "2023-11-20", "2023-11-21"),
    ("2024 Special Session", "2024-06-26", "2024-06-27"),
]


def read(directory, name):
    with open(os.path.join(directory, name), encoding="utf-8") as f:
        return f.read()


def sessions():
    return hi.Hawaii.legislative_sessions


def by_kind(kind):
    return [s for s in sessions() if s["classification"] == kind]


def days(s):
    return date.fromisoformat(s["start_date"]), date.fromisoformat(s["end_date"])


def test_every_special_session_has_its_journal_dates():
    got = [
        (s["identifier"], s["start_date"], s["end_date"]) for s in by_kind("special")
    ]
    assert got == SPECIAL
    assert all(s["name"] == s["identifier"] for s in by_kind("special"))
    assert not any(s.get("active") for s in by_kind("special"))


def test_2011_and_2012_are_two_regular_sessions_with_their_own_dates():
    regular = {s["identifier"]: s for s in by_kind("primary")}
    assert days(regular["2011 Regular Session"]) == (
        date(2011, 1, 19),
        date(2011, 5, 5),
    )
    assert days(regular["2012 Regular Session"]) == (
        date(2012, 1, 18),
        date(2012, 5, 3),
    )
    assert regular["2011 Regular Session"]["_scraped_name"] == "2011"
    assert regular["2012 Regular Session"]["_scraped_name"] == "2012"


def test_no_session_holds_a_day_of_another():
    # no regular session's dates hold a special-session day, nor the reverse, nor two specials
    # the same day (all sessions are day ranges, so this is "no two ranges overlap")
    spans = sorted((days(s), s["identifier"]) for s in sessions())
    for ((_, end), a), ((start, _), b) in zip(spans, spans[1:]):
        assert end < start, f"{a} and {b} share a day"


def test_session_check_accepts_the_sites_list(monkeypatch):
    page = read(FIX748, "archives-main.html")

    class Response:
        content = page.encode("utf-8")

    monkeypatch.setattr(requests, "get", lambda url, **kw: Response())
    jurisdiction = hi.Hawaii()
    scraped = jurisdiction.get_session_list()
    assert [str(y) for y in range(2025, 1998, -1)] == scraped[:-1]
    # openstates-core's own check: it raises on a listed year the scraper does not know
    assert check_session_list(jurisdiction) == {"2026"}


def _members():
    # OPEN-709's saved people data, for the House tallies that print no aye count
    os.environ[hi_members.PEOPLE_DIR_ENV] = os.path.join(FIX709, "people")
    try:
        return hi_members.load_members(None)
    finally:
        del os.environ[hi_members.PEOPLE_DIR_ENV]


def _scraper(pages):
    scraper = object.__new__(HIBillScraper)
    scraper.jurisdiction = hi.Hawaii()
    scraper.short_ids = {}
    scraper.members = _members()
    scraper.logger = logging.getLogger("test")
    scraper.info = scraper.warning = scraper.error = scraper.logger.info
    scraper.requested = []

    def get(url, **kw):
        scraper.requested.append(url)
        for key, text in pages.items():
            if key in url:
                return type("Response", (), {"text": text})
        raise AssertionError(f"unexpected request {url}")

    scraper.get = get
    return scraper


def _bill_url(number, year, billtype="SB"):
    return (
        "https://www.capitol.hawaii.gov/session/archives/measure_indiv_Archives.aspx?"
        f"billtype={billtype}&billnumber={number}&year={year}"
    )


def _session_of(vote):
    return (
        vote.legislative_session,
        get_pseudo_id(vote.bill)["legislative_session__identifier"],
    )


def test_a_roll_call_on_a_special_session_day_is_filed_under_that_session():
    scraper = _scraper({"billnumber=862": read(FIX709, "HB862-2021.html")})
    out = list(
        scraper.scrape_bill(
            "2021 Regular Session", "lower", "bill", _bill_url(862, 2021, "HB")
        )
    )
    (bill,) = [o for o in out if isinstance(o, Bill)]
    assert bill.legislative_session == "2021 Regular Session"
    votes = {
        (v.start_date, v.motion_text[:24]): v for v in out if isinstance(v, VoteEvent)
    }
    overrides = [v for (d, _), v in votes.items() if d == "2021-07-06"]
    assert len(overrides) == 2  # the House's and the Senate's
    for v in overrides:
        # the special session's roll call, still linked to the regular bill
        assert _session_of(v) == ("2021 Special Session", "2021 Regular Session")
        assert get_pseudo_id(v.bill)["identifier"] == "HB862"
    # the Senate's Final Reading of 4/27/2021, in the regular session
    (final,) = [v for (d, m), v in votes.items() if d == "2021-04-27"]
    assert _session_of(final) == ("2021 Regular Session", "2021 Regular Session")
    # every other roll call on the page is from the regular session
    for (d, _), v in votes.items():
        if d != "2021-07-06":
            assert v.legislative_session == "2021 Regular Session"


def test_the_2011_session_reads_a_carried_over_bill_from_its_2012_page(monkeypatch):
    scraper = _scraper(
        {
            "measuretype=sb&year=2011": read(FIX748, "report-sb-2011.html"),
            "measuretype=sb&year=2012": read(FIX748, "report-sb-2012.html"),
        }
    )
    asked = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda session, chamber, kind, url: asked.append((session, url)) or [],
        raising=False,
    )
    list(scraper.scrape_type("upper", "2011 Regular Session", "bill"))
    # SB 2 is on the 2011 list only; SB 41, on both, was carried over into 2012
    assert [(s, u.split("?")[1]) for s, u in asked] == [
        ("2011 Regular Session", "billtype=SB&billnumber=2&year=2011"),
        ("2011 Regular Session", "billtype=SB&billnumber=41&year=2012"),
    ]


def test_a_carried_over_2011_bill_stays_in_2011_with_its_2012_actions():
    pages = {"billnumber=41": read(FIX748, "SB41-2012.html")}
    in_2011 = list(
        _scraper(pages).scrape_bill(
            "2011 Regular Session", "upper", "bill", _bill_url(41, 2012)
        )
    )
    (bill,) = [o for o in in_2011 if isinstance(o, Bill)]
    assert bill.legislative_session == "2011 Regular Session"
    assert {a["date"] for a in bill.actions} >= {"2011-01-20", "2012-04-13"}
    # the 2012 session skips it: it was first acted on in 2011
    assert (
        list(
            _scraper(pages).scrape_bill(
                "2012 Regular Session", "upper", "bill", _bill_url(41, 2012)
            )
        )
        == []
    )


def test_a_2012_bill_is_filed_under_2012():
    scraper = _scraper(
        {
            "billnumber=2001": read(FIX748, "SB2001-2012.html"),
            "billnumber=2039": read(FIX748, "HB2039-2012.html"),
        }
    )
    out = list(
        scraper.scrape_bill(
            "2012 Regular Session", "upper", "bill", _bill_url(2001, 2012)
        )
    )
    (bill,) = [o for o in out if isinstance(o, Bill)]
    assert bill.legislative_session == "2012 Regular Session"
    # its companion, first acted on 1/19/2012, is a 2012 bill too
    (companion,) = bill.related_bills
    assert (companion["identifier"], companion["legislative_session"]) == (
        "HB 2039",
        "2012 Regular Session",
    )


def test_a_2012_listed_bill_with_no_dated_action_follows_its_companion():
    # SB 2001's page with its status rows removed (constructed), its companion standing in for
    # a 2011 bill (SB 41's 2011 page) and for a 2012 bill (HB 2039's page)
    page = read(FIX748, "SB2001-2012.html")
    start = page.index("</tr>", page.index("Sort by Date")) + len("</tr>")
    bare = page[:start] + page[page.index("</table>", start) :]
    for companion, kept in (("SB41-2011.html", False), ("HB2039-2012.html", True)):
        scraper = _scraper(
            {"billnumber=2001": bare, "billnumber=2039": read(FIX748, companion)}
        )
        out = list(
            scraper.scrape_bill(
                "2012 Regular Session", "upper", "bill", _bill_url(2001, 2012)
            )
        )
        assert bool(out) is kept


def test_a_companion_first_acted_on_in_2011_is_linked_under_2011():
    # the 2012 pages link every companion as year=2012; SB 41's 2011 page stands in for a
    # carried-over 2011 companion of SB 2001 (constructed pairing)
    scraper = _scraper(
        {
            "billnumber=2001": read(FIX748, "SB2001-2012.html"),
            "billnumber=2039": read(FIX748, "SB41-2011.html"),
        }
    )
    out = list(
        scraper.scrape_bill(
            "2012 Regular Session", "upper", "bill", _bill_url(2001, 2012)
        )
    )
    (bill,) = [o for o in out if isinstance(o, Bill)]
    (companion,) = bill.related_bills
    assert companion["legislative_session"] == "2011 Regular Session"


def test_a_senate_only_special_session_scrapes_no_measures():
    scraper = _scraper({})
    with pytest.raises(EmptyScrape):
        list(scraper.scrape(session="2019 Special Session"))
    assert scraper.requested == []
