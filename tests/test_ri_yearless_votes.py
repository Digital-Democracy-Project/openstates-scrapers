"""Tests for OPEN-701: Rhode Island roll calls whose bill number is printed without its year.

Every fixture in tests/fixtures/ri_open701/ is a real vote report
(webserver.rilegislature.gov/SVotes|HVotes/votereport.asp?id=..., read 2026-11-20). Late in a
session a calendar item prints its bill as "3225 SUB A as amended", "S 122 SUB A as amended" or
"-S 70 SUB A as amended" (no "2026-S" prefix). Those roll calls used to be dropped. A Senate
consent-calendar roll call ("CONSENT CALENDAR", "Consent #2") names no bill at all and is still
not tied to one.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ri.bills import YEARLESS_ITEM, RIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ri_open701")

# bills a real scrape would have found; numbers do not overlap between chambers in a session
BILLS = {
    ("upper", "3225"): "S 3225",
    ("lower", "5229"): "H 5229",
    ("upper", "122"): "S 122",
    ("upper", "70"): "S 70",
    ("upper", "640"): "S 640",
    ("upper", "2036"): "S 2036",
}


def _page(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


def _scraper(bills=BILLS):
    scraper = object.__new__(RIBillScraper)
    scraper.warnings = []
    # the OPEN-785 presiding-officer warning (no manifest here) is tested in test_ri_presiding_officers.py
    scraper.warning = lambda *a, **k: "OPEN-785" in a[0] or scraper.warnings.append(a)
    scraper._bill_id_by_type = dict(bills)
    scraper._tz = types.SimpleNamespace(localize=lambda d: d)
    return scraper


def _scrape_votes(names, chamber, session, bills=BILLS, setup=None):
    """scrape_chamber_votes over a date list naming these real reports."""
    scraper = _scraper(bills)
    if setup:
        setup(scraper)
    by_id = {n.split("_")[1].split(".")[0]: n for n in names}
    listing = "<html><body><center>%s</center></body></html>" % "".join(
        '<div class="vote"><a href="votereport.asp?id=%s">Details</a></div>' % i
        for i in by_id
    )
    scraper.get_vote_dates = lambda url, session: ["6/20/%s" % session]
    scraper.post_to = lambda url, date: listing
    scraper.get = lambda url: types.SimpleNamespace(
        text=_page(by_id[url.split("=")[1]])
    )
    return list(scraper.scrape_chamber_votes(chamber, session)), scraper


@pytest.mark.parametrize(
    "name,session,chamber,bill,bill_chamber,motion,classification",
    [
        # House 6/11/2026: "ITEM 31    3225 SUB A as amended" -> Senate bill 3225
        (
            "H_23043.html",
            "2026",
            "lower",
            "S 3225",
            "upper",
            "PASSAGE / IN CONCURRENCE",
            ["passage"],
        ),
        # Senate 6/21/2025: "ITEM 22    5229 SUB A as amended" -> House bill 5229
        (
            "S_17263.html",
            "2025",
            "upper",
            "H 5229",
            "lower",
            "In Concurrence / Passage",
            ["passage"],
        ),
        # Senate 6/20/2025: "ITEM 24   S 122 SUB A as amended"
        (
            "S_17188.html",
            "2025",
            "upper",
            "S 122",
            "upper",
            "In Concurrence / Passage",
            ["passage"],
        ),
        # Senate 6/20/2025: "ITEM 34   -S 70 SUB A as amended"
        (
            "S_17196.html",
            "2025",
            "upper",
            "S 70",
            "upper",
            "In Concurrence / Passage",
            ["passage"],
        ),
        # House 6/12/2025: "ITEM 20   S 640 SUB A as amended"
        (
            "H_21914.html",
            "2025",
            "lower",
            "S 640",
            "upper",
            "PASSAGE / IN CONCURRENCE",
            ["passage"],
        ),
        # Senate 6/11/2026: "ITEM 4     2036 SUB A as amended"
        (
            "S_18030.html",
            "2026",
            "upper",
            "S 2036",
            "upper",
            "In Concurrence",
            ["passage"],
        ),
    ],
)
def test_yearless_roll_call_is_tied_to_its_bill(
    name, session, chamber, bill, bill_chamber, motion, classification
):
    (vote,), scraper = _scrape_votes([name], chamber, session)
    assert vote.bill_identifier == bill
    # the vote is the page's chamber; the bill keeps its own
    assert vote.organization == '~{"classification": "%s"}' % chamber
    assert '"from_organization__classification": "%s"' % bill_chamber in vote.bill
    assert vote.motion_text == motion
    assert vote.motion_classification == classification
    assert len(vote.votes) > 30
    assert scraper.warnings == []


def test_yearless_number_found_in_neither_chamber_is_still_dropped():
    votes, scraper = _scrape_votes(["H_23043.html"], "lower", "2026", bills={})
    assert votes == []
    assert scraper.warnings


def test_yearless_number_found_in_both_chambers_is_not_guessed():
    bills = {("upper", "3225"): "S 3225", ("lower", "3225"): "H 3225"}
    votes, _ = _scrape_votes(["H_23043.html"], "lower", "2026", bills=bills)
    assert votes == []


def test_yearless_number_with_chamber_letter_looks_only_in_that_chamber():
    # "S 122": a House bill 122 alone must not be used
    votes, _ = _scrape_votes(
        ["S_17188.html"], "upper", "2025", bills={("lower", "122"): "H 122"}
    )
    assert votes == []


@pytest.mark.parametrize("name", ["S_17915.html", "S_18007.html"])
def test_senate_consent_calendar_names_no_bill(name):
    # Senate 6/11/2026 "CONSENT CALENDAR" (id 17915) and "Consent #2" (id 18007): the report
    # page carries no item and no bill number. OPEN-711 reads the bills from that day's Senate
    # Journal (tests/test_ri_consent_calendar.py); with no journal it is not tied to a bill.
    def no_journal(scraper):
        scraper.senate_journal_consent_calendars = lambda date: (None, [])

    votes, _ = _scrape_votes([name], "upper", "2026", setup=no_journal)
    assert votes == []


def test_bills_of_both_chambers_are_known_before_any_votes():
    scraper = _scraper(bills={})
    calls = []

    def scrape_bills(chamber, session, subjects):
        calls.append(("bills", chamber))
        return iter(())

    def scrape_chamber_votes(chamber, session):
        calls.append(("votes", chamber))
        return iter(())

    scraper.scrape_bills = scrape_bills
    scraper.scrape_chamber_votes = scrape_chamber_votes
    list(scraper.scrape(session="2025"))
    assert calls == [
        ("bills", "upper"),
        ("bills", "lower"),
        ("votes", "upper"),
        ("votes", "lower"),
    ]


def test_get_votes_reads_yearless_item():
    scraper = _scraper()
    html = _page("H_23043.html")
    scraper.get = lambda url: types.SimpleNamespace(text=html)
    (vote,) = scraper.get_votes("https://example/H_23043.html", "2026").values()
    assert vote["meta"]["chamber"] is None
    assert vote["meta"]["bill"] == "3225"


@pytest.mark.parametrize(
    "line",
    [
        # Senate 5/26/2026 (id 17540): a nomination, "Appointment of Alan Goulart ..."
        "ITEM 8                        0",
        # Senate 3/20/2025 (id 16656)
        "ITEM 1                        0",
    ],
)
def test_nomination_item_is_not_a_bill(line):
    assert YEARLESS_ITEM.match(line) is None


def test_year_prefixed_house_vote_on_senate_bill_is_a_house_vote():
    # House 6/11/2026 (id 23006) consent calendar "ITEM 1              2026-S 2824": tied to
    # Senate bill 2824 as before, but recorded as a House vote (it was recorded as a Senate one)
    (vote,), _ = _scrape_votes(
        ["H_23006.html"], "lower", "2026", bills={("upper", "2824"): "S 2824"}
    )
    assert vote.bill_identifier == "S 2824"
    assert '"from_organization__classification": "upper"' in vote.bill
    assert vote.organization == '~{"classification": "lower"}'
    assert vote.motion_text == "PASSAGE / IN CONCURRENCE"
