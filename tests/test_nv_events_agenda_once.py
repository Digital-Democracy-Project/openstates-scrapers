"""Tests for OPEN-938: the Nevada events scraper fetches each agenda PDF once, not twice.

The meetings page below is built the way NELIS serves it (title + date, agenda link, locations,
then an <hr>). The agenda text has the shape of a real Nevada agenda (a "Start Time" line and bill
numbers written as "AB 12", "S.B. 0034", ...). Only the network is faked: page and PDF fetches go
through spatula's own URL.get_response, and pdftotext is replaced by a dict lookup.
"""
import os
import sys
from collections import Counter
from types import SimpleNamespace

import pytest
import scrapelib
import spatula
from spatula import URL

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from nv import events  # noqa: E402

MEETINGS_URL = "https://www.leg.state.nv.us/App/NELIS/REL/83rd2025/Meetings"
AGENDA_A = "https://www.leg.state.nv.us/Session/83rd2025/Agendas/A.pdf"
AGENDA_B = "https://www.leg.state.nv.us/Session/83rd2025/Agendas/B.pdf"
AGENDA_404 = "https://www.leg.state.nv.us/Session/83rd2025/Agendas/missing.pdf"


def _meeting(title, date, agenda):
    return (
        f'<div><h3><a href="#">{title}</a><a href="#">{date}</a></h3></div>'
        f'<div><a title="View the agenda for this meeting" href="{agenda}">Agenda</a></div>'
        "<div><ul><li>Room 4100</li></ul></div><hr>"
    )


MEETINGS_HTML = (
    "<div>"
    + _meeting(
        "Assembly Committee on Ways and Means",
        "Monday, March 3, 2025 8:00 AM",
        AGENDA_A,
    )
    # "upon adjournment" dates take their time from the agenda's start time
    + _meeting(
        "Senate Committee on Finance",
        "Tuesday, March 4, 2025 [upon adjournment]",
        AGENDA_B,
    )
    + _meeting(
        "Senate Committee on Taxation",
        "Wednesday, March 5, 2025 [upon adjournment]",
        AGENDA_404,
    )
    + "</div>"
)

PDF_TEXT = {
    AGENDA_A: "Start Time 8 AM\nWork session on A.B. 0012 and AB 12, SB 34, S.J.R. 5.\n",
    # no "Start Time" line at all: defaults to 12:00 AM
    AGENDA_B: "Hearing on sb 7 and AB 99\n",
}


@pytest.fixture
def fetches(monkeypatch):
    """Count every URL spatula fetches while the Nevada events scraper runs."""
    seen = Counter()

    def fake_get_response(self, scraper):
        seen[self.url] += 1
        if self.url == AGENDA_404:
            raise scrapelib.HTTPError(
                SimpleNamespace(status_code=404, url=self.url, text="")
            )
        if self.url == MEETINGS_URL:
            return SimpleNamespace(
                text=MEETINGS_HTML, content=MEETINGS_HTML.encode(), fromcache=False
            )
        return SimpleNamespace(url=self.url, content=b"", fromcache=False)

    def fake_postprocess(self):
        self.text = PDF_TEXT[self.source.url]

    monkeypatch.setattr(URL, "get_response", fake_get_response)
    monkeypatch.setattr(spatula.PdfPage, "postprocess_response", fake_postprocess)
    return seen


def run_events():
    return list(events.CurrentMeetings(source=MEETINGS_URL).do_scrape())


def _bills(event_dict):
    return sorted(
        rel["name"]
        for item in event_dict.get("agenda", [])
        for rel in item.get("related_entities", [])
        if rel["entity_type"] == "bill"
    )


def test_each_agenda_pdf_is_fetched_once(fetches):
    run_events()
    assert fetches[AGENDA_A] == 1
    assert fetches[AGENDA_B] == 1
    assert fetches[MEETINGS_URL] == 1


def test_events_keep_start_time_and_bills(fetches):
    evs = {e.name: e for e in run_events()}
    assert len(evs) == 3

    ways = evs["Assembly Committee on Ways and Means"].as_dict()
    assert ways["start_date"].isoformat().startswith("2025-03-03T08:00")
    # the same bill written two ways is one bill; S.J.R. 5 is kept
    assert _bills(ways) == ["AB 12", "SB 34", "SJR 5"]

    finance = evs["Senate Committee on Finance"].as_dict()
    # no Start Time in the PDF -> 12:00 AM default, so the date is midnight
    assert finance["start_date"].isoformat().startswith("2025-03-04T00:00")
    assert _bills(finance) == ["AB 99", "SB 7"]


def test_agenda_that_404s_still_yields_an_event_without_bills(fetches):
    evs = {e.name: e for e in run_events()}
    tax = evs["Senate Committee on Taxation"].as_dict()
    assert tax["start_date"].isoformat().startswith("2025-03-05")
    assert _bills(tax) == []
    assert tax["documents"] == []
