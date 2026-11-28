import datetime
import json

import lxml.html
from openstates.scrape import Bill
from spatula import URL

from nv import bills as nv_bills
from nv import events as nv_events
from nv.bills import BillStub, BillTabDetail, NVBillScraper
from nv.events import CurrentMeetings, Meetings, NVEventScraper

# OPEN-937 (upstream openstates-scrapers #5981): the bill and event pages run with the scraper's own
# settings (timeout, retries, request rate), and the committees an action names are kept on the action.


def test_bill_list_runs_with_the_scrapers_settings(monkeypatch):
    seen = []
    monkeypatch.setattr(nv_bills, "get_session_slug", lambda jurisdiction, session: "83rd2025")
    monkeypatch.setattr(
        nv_bills.BillList,
        "do_scrape",
        lambda self, scraper=None: seen.append(scraper) or iter(()),
    )
    scraper = NVBillScraper.__new__(NVBillScraper)
    scraper.jurisdiction = None
    list(scraper.scrape("83"))
    assert seen == [scraper]


def test_event_pages_all_run_with_the_scrapers_settings(monkeypatch):
    seen = []

    def record(name, result):
        def do_scrape(self, scraper=None):
            seen.append((name, scraper))
            return iter(result)

        return do_scrape

    scraper = NVEventScraper.__new__(NVEventScraper)
    monkeypatch.setattr(Meetings, "do_scrape", record("meetings", ()))
    list(scraper.scrape())
    assert seen == [("meetings", scraper)]

    # Meetings hands the scraper on to the page that reads each agenda PDF
    meetings = Meetings(scraper)
    meetings.root = lxml.html.fromstring(
        '<div><div aria-labelledby="session"><a href="/x/83rd2025">s</a></div></div>'
    )
    next_page = next(iter(meetings.process_page()))
    assert next_page.input is scraper

    seen.clear()
    # one fetch per agenda PDF (OPEN-938): Agenda returns the start time and the bills together
    monkeypatch.setattr(nv_events.Agenda, "do_scrape", record("agenda", [("9:00 AM", {"AB 1"})]))
    page = CurrentMeetings(scraper, source=URL("https://example.invalid/m"))
    page.root = lxml.html.fromstring(
        "<div>"
        '<div><h3><a>Assembly Committee on Government Affairs</a><a>Monday, February 3, 2025 [x]</a></h3></div>'
        '<div><a title="View the agenda for this meeting" href="https://example.invalid/a.pdf">a</a></div>'
        "<div><ul><li>Room 4100</li></ul></div><hr/>"
        "</div>"
    )
    events = list(page.process_page())
    assert len(events) == 1
    assert seen == [("agenda", scraper)]


# Real action lines read back from the Mac replica (Nevada 84th and 2025 special 36), 2026-11-27.
REAL_ACTIONS = [
    ("Prefiled. Referred to Committee on Government Affairs. To printer.", ["Government Affairs"]),
    ("Prefiled. Referred to Committee on Health and Human Services. To printer.", ["Health and Human Services"]),
    ("Prefiled. Referred to Committee on Ways and Means. To printer.", ["Ways and Means"]),
    ("Prefiled. Referred to Committee on Revenue and Economic Development. To printer.", ["Revenue and Economic Development"]),
    ("Read first time. Referred to Select Committee on Public Safety and Security. To committee.", ["Public Safety and Security"]),
    ("From printer. To engrossment. Engrossed. First reprint.", []),
    ("From committee: Do pass.", []),
]


def _bill_after(description):
    bill = Bill("AB 1", "84", "t", chamber="lower", classification="bill")
    stub = BillStub("https://example.invalid/b", "AB1", "84", "84th2027", [])
    page = BillTabDetail(stub, source=URL("https://example.invalid/b"))
    page.add_action(bill, datetime.datetime(2026, 11, 1), description, "lower")
    return bill.actions[0]


def test_each_committee_an_action_names_is_kept():
    for description, names in REAL_ACTIONS:
        got = [json.loads(json.dumps(e)) for e in _bill_after(description)["related_entities"]]
        assert got == [
            {"name": n, "entity_type": "organization", "organization_id": None} for n in names
        ], description
