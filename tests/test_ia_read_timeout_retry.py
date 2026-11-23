"""Tests for OPEN-797: Iowa's scrapers ride out a run of read timeouts from www.legis.iowa.gov.

A 60 s read timeout on one page ended Iowa's whole 2025 collection (2026-11-23). The fix is a bigger
budget on scrapelib's own per-request retry, with the scraper's own user-agent (never
--http-resilience, which sends made-up browser user-agents). No request here reaches the network:
every one goes to a fake adapter that times out a set number of times, and any request that gets
past it to a real adapter fails the test.
"""

import logging
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.models import Response

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ia.bills import IABillScraper  # noqa: E402
from ia.votes import IAVoteScraper  # noqa: E402

LISTING = '<table id="sortableTable"><tbody></tbody></table>'


class FlakyAdapter(BaseAdapter):
    """Times out the first `fails` requests to each URL, then answers 200 with `body`."""

    def __init__(self, fails, body="<html></html>"):
        super().__init__()
        self.fails = fails
        self.body = body
        self.requests = []
        self.timeouts = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        self.timeouts.append(kwargs.get("timeout"))
        if sum(1 for r in self.requests if r.url == request.url) <= self.fails:
            raise requests.exceptions.ReadTimeout(
                "HTTPSConnectionPool(host='www.legis.iowa.gov', port=443): "
                "Read timed out. (read timeout=60)"
            )
        response = Response()
        response.status_code = 200
        response._content = self.body.encode()
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


@pytest.fixture
def sleeps():
    waits = []
    with mock.patch("time.sleep", side_effect=waits.append), mock.patch(
        "requests.adapters.HTTPAdapter.send",
        side_effect=AssertionError("a test request reached the real network"),
    ):
        yield waits


def make(cls, adapter, tmp_path):
    jurisdiction = SimpleNamespace(
        jurisdiction_id="ocd-jurisdiction/country:us/state:ia/government",
        name="Iowa",
        legislative_sessions=[
            {
                "identifier": "2025",
                "classification": "primary",
                "extras": {"ordinal": 91},
            }
        ],
    )
    with mock.patch("openstates.settings.CACHE_DIR", None):
        scraper = cls(jurisdiction, str(tmp_path))
    # the throttle's own sleeps are not what is measured
    scraper.requests_per_minute = 0
    scraper.mount("https://", adapter)
    return scraper


@pytest.mark.parametrize("cls", [IABillScraper, IAVoteScraper])
def test_five_timeouts_in_a_row_are_retried_with_backoff_and_a_log_line_each(
    cls, sleeps, tmp_path
):
    adapter = FlakyAdapter(fails=5)
    scraper = make(cls, adapter, tmp_path)
    # on scrapelib's own logger: openstates-core's logging config stops it propagating to root
    records = []
    handler = logging.Handler(logging.WARNING)
    handler.emit = records.append
    logger = logging.getLogger("scrapelib")
    logger.addHandler(handler)
    try:
        response = scraper.get("https://www.legis.iowa.gov/legislation/BillBook?ga=91")
    finally:
        logger.removeHandler(handler)
    assert response.status_code == 200
    assert len(adapter.requests) == 6
    assert sleeps == [10, 20, 40, 80, 160]
    retry_lines = [r for r in records if "before retry" in r.getMessage()]
    assert len(retry_lines) == 5
    assert all("read timeout=60" in r.getMessage() for r in retry_lines)


@pytest.mark.parametrize("cls", [IABillScraper, IAVoteScraper])
def test_the_retry_is_bounded(cls, sleeps, tmp_path):
    adapter = FlakyAdapter(fails=1000)
    scraper = make(cls, adapter, tmp_path)
    with pytest.raises(requests.exceptions.ReadTimeout):
        scraper.get("https://www.legis.iowa.gov/legislation/BillBook?ga=91")
    assert len(adapter.requests) == 6


@pytest.mark.parametrize("cls", [IABillScraper, IAVoteScraper])
def test_every_try_sends_the_scrapers_own_user_agent(cls, sleeps, tmp_path):
    adapter = FlakyAdapter(fails=5)
    scraper = make(cls, adapter, tmp_path)
    scraper.get("https://www.legis.iowa.gov/legislation/BillBook?ga=91")
    agents = {r.headers["User-Agent"] for r in adapter.requests}
    assert agents == {scraper.headers["User-Agent"]}
    (agent,) = agents
    assert agent.startswith("scrapelib ")
    assert "Mozilla" not in agent
    assert not scraper.http_resilience_mode


def test_the_bill_list_is_fetched_through_the_retrying_get(sleeps, tmp_path):
    """The allbills listing was read with a bare requests.Session: no timeout and no retry."""
    adapter = FlakyAdapter(fails=2, body=LISTING)
    scraper = make(IABillScraper, adapter, tmp_path)
    assert list(scraper.scrape(session="2025")) == []
    listing = [r for r in adapter.requests if "/findLegislation/allbills" in r.url]
    assert len(listing) == 3
    assert all(r.headers["X-Requested-With"] == "XMLHttpRequest" for r in listing)
    # and with the scraper's 60 s timeout, which the bare session did not have
    assert set(adapter.timeouts) == {60}
