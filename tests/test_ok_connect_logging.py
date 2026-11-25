"""OPEN-892: the Oklahoma bills scraper logs the address its requests leave from, and how long it
tried before a connect failed, so a connect timeout can be told apart from a dropped address or a
network-path problem (OPEN-887: three runs failed on the first request, no block signature).

No request here reaches the network: the address lookup is faked and the scraper's own requests go
to an adapter that times out.  Addresses below are documentation-range examples (RFC 5737).
"""
import logging
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from requests.adapters import BaseAdapter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ok.bills import OKBillScraper  # noqa: E402

FORM = "https://webapps.oklegislature.gov/WebApplication3/WebForm1.aspx"


class TimingOutAdapter(BaseAdapter):
    def send(self, request, **kwargs):
        raise requests.exceptions.ConnectTimeout(
            "HTTPSConnectionPool(host='webapps.oklegislature.gov', port=443): "
            "Max retries exceeded (Caused by ConnectTimeoutError(connect timeout=60))"
        )

    def close(self):
        pass


@pytest.fixture
def logs():
    records = []
    handler = logging.Handler(logging.INFO)
    handler.emit = records.append
    logger = logging.getLogger("openstates")
    old = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield lambda: [r.getMessage() for r in records]
    logger.removeHandler(handler)
    logger.setLevel(old)


@pytest.fixture
def scraper(tmp_path):
    jurisdiction = SimpleNamespace(
        jurisdiction_id="ocd-jurisdiction/country:us/state:ok/government",
        name="Oklahoma",
        legislative_sessions=[],
    )
    with mock.patch("openstates.settings.CACHE_DIR", None):
        s = OKBillScraper(jurisdiction, str(tmp_path))
    s.requests_per_minute = 0
    s.retry_attempts = 0
    s.mount("https://", TimingOutAdapter())
    return s


def fake_lookup(text=None, error=None):
    def get(url, **kwargs):
        assert url == "https://api.ipify.org"
        assert kwargs.get("timeout")  # a hung lookup must not hold the scrape
        if error:
            raise error
        return SimpleNamespace(text=text)

    return mock.patch("ok.bills.checked_requests.get", side_effect=get)


def test_the_address_is_logged_once_at_the_start_of_a_run(scraper, logs):
    with fake_lookup("203.0.113.7\n"), mock.patch.object(
        OKBillScraper, "scrape_chamber", return_value=iter(())
    ):
        list(scraper.scrape(session="2026"))
    assert [m for m in logs() if "egress" in m] == ["OK egress address: 203.0.113.7"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"error": requests.exceptions.ConnectTimeout("x")},
        {"text": "<html>502 Bad Gateway</html>"},
    ],
)
def test_a_failed_or_odd_lookup_is_logged_and_the_scrape_goes_on(scraper, logs, kwargs):
    with fake_lookup(**kwargs), mock.patch.object(
        OKBillScraper, "scrape_chamber", return_value=iter(())
    ) as chamber:
        list(scraper.scrape(session="2026"))
    assert chamber.call_count == 2  # both chambers still scraped
    assert any(m.startswith("OK egress address: lookup failed") for m in logs())
    assert not any("Bad Gateway" in m for m in logs())


def test_a_connection_error_logs_the_time_tried_and_still_raises(scraper, logs):
    ticks = iter([100.0, 161.5])
    with mock.patch("ok.bills.time.monotonic", side_effect=lambda: next(ticks)):
        with pytest.raises(requests.exceptions.ConnectTimeout):
            scraper.get(FORM)
    (line,) = [m for m in logs() if m.startswith("OK connection error")]
    assert "ConnectTimeout after 61.5s of tries: GET " + FORM in line
    assert "connect timeout=60" in line


def test_a_read_timeout_is_not_reported_as_a_connect_failure(scraper, logs):
    class Slow(TimingOutAdapter):
        def send(self, request, **kwargs):
            raise requests.exceptions.ReadTimeout("read timeout=60")

    scraper.mount("https://", Slow())
    with pytest.raises(requests.exceptions.ReadTimeout):
        scraper.get(FORM)
    assert not any(m.startswith("OK connection error") for m in logs())
