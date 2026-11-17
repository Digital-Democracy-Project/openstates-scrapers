"""OPEN-607: the Oregon votes scraper reports "nothing to scrape" only when Oregon answered.

A session in pre-filing has bills but no roll calls. When Oregon's data service answers and lists
none, the scraper raises EmptyScrape (as or/events.py does), so a run that collected bills still
succeeds. When the service fails, the run must still fail. The requests go through the real
OregonLegislatorODataClient to a fake HTTP layer; no request leaves the test.
"""
import importlib
from unittest import mock

import pytest
import requests
import scrapelib

from openstates.exceptions import EmptyScrape

ORVoteScraper = importlib.import_module(
    "or.votes"
).ORVoteScraper  # "or" is a Python keyword

LEGISLATOR = {"LegislatorCode": "Smith", "FirstName": "Ann", "LastName": "Smith"}

# A pre-filing measure: on the list, with a history action, but no roll call.
PREFILED = {
    "MeasurePrefix": "HB",
    "MeasureNumber": 2001,
    "MeasureHistoryActions": [{"ActionText": "Presession filed.", "MeasureVotes": []}],
    "CommitteeAgendaItems": [],
}

FLOOR_VOTE = {
    "ActionText": "Third reading. Passed.",
    "ActionDate": "2026-02-10T11:00:00",
    "Chamber": "H",
    "MeasureVotes": [{"VoteName": "Smith", "Vote": "Aye"}],
}


def answer(value):
    response = mock.Mock(status_code=200)
    response.json.return_value = {"value": value}
    return response


def http_error(status):
    response = requests.Response()
    response.status_code = status
    response.url = "https://api.oregonlegislature.gov/odata/odataservice.svc/"
    response._content = b"Service Unavailable"
    return scrapelib.HTTPError(response)


def scrape(get):
    """Run ORVoteScraper.scrape() for 2026R1 with `get` standing in for the scraper's HTTP get."""
    scraper = ORVoteScraper.__new__(ORVoteScraper)
    scraper.get = get
    return list(scraper.scrape(session="2026R1"))


def oregon(measures):
    """A fake Oregon service that answers every request; `measures` is the votes listing."""

    def get(url, *args, **kwargs):
        if "/Legislators" in url:
            return answer([LEGISLATOR] if "$skip=" not in url else [])
        # The votes resource is paged ($top/$skip): first page holds everything, next is empty.
        return answer(measures if "$skip=0" in url else [])

    return get


def test_answered_with_no_roll_calls_is_empty_scrape():
    with pytest.raises(EmptyScrape):
        scrape(oregon([PREFILED]))


def test_answered_with_no_measures_is_empty_scrape():
    with pytest.raises(EmptyScrape):
        scrape(oregon([]))


def test_answered_with_a_roll_call_yields_it_and_is_not_empty():
    measure = dict(PREFILED, MeasureHistoryActions=[FLOOR_VOTE])
    votes = scrape(oregon([measure]))
    assert [v.motion_text for v in votes] == ["Third reading. Passed."]


@pytest.mark.parametrize("status", [500, 503, 404])
def test_service_error_on_the_votes_listing_fails_and_is_not_empty(status):
    def get(url, *args, **kwargs):
        if "/Legislators" in url:
            return answer([LEGISLATOR])
        raise http_error(status)

    with pytest.raises(Exception) as caught:
        scrape(get)
    assert not isinstance(caught.value, EmptyScrape)


def test_service_error_on_the_legislators_listing_fails_and_is_not_empty():
    def get(url, *args, **kwargs):
        raise http_error(503)

    with pytest.raises(Exception) as caught:
        scrape(get)
    assert not isinstance(caught.value, EmptyScrape)


def test_connection_failure_fails_and_is_not_empty():
    def get(url, *args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    with pytest.raises(Exception) as caught:
        scrape(get)
    assert not isinstance(caught.value, EmptyScrape)


def test_non_json_answer_fails_and_is_not_empty():
    """A block or error page served with status 200 is not an answer from the data service."""

    def get(url, *args, **kwargs):
        response = mock.Mock(status_code=200)
        response.json.side_effect = requests.exceptions.JSONDecodeError(
            "Expecting value", "<html>", 0
        )
        return response

    with pytest.raises(Exception) as caught:
        scrape(get)
    assert not isinstance(caught.value, EmptyScrape)


def test_core_run_finishes_with_no_objects_when_oregon_answered_empty(tmp_path):
    """What os-update sees: do_scrape logs the EmptyScrape and returns, rather than raising
    "no objects returned from ORVoteScraper scrape" (the message the cloud collector fails on)."""
    scraper = ORVoteScraper(mock.Mock(), str(tmp_path))
    with mock.patch.object(scraper, "get", oregon([PREFILED])):
        record = scraper.do_scrape(session="2026R1")
    assert sum(record["objects"].values()) == 0


def test_core_run_fails_when_oregon_errors(tmp_path):
    scraper = ORVoteScraper(mock.Mock(), str(tmp_path))

    def get(url, *args, **kwargs):
        raise http_error(503)

    with mock.patch.object(scraper, "get", get), pytest.raises(Exception) as caught:
        scraper.do_scrape(session="2026R1")
    assert not isinstance(caught.value, EmptyScrape)
