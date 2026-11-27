"""OPEN-892: the Oklahoma bills scraper logs the address its requests leave from, and how long it
tried before a connect failed, so a connect timeout can be told apart from a dropped address or a
network-path problem (OPEN-887: three runs failed on the first request, no block signature).

No request here reaches the network: the address lookup is faked and the scraper's own requests go
to an adapter that times out.  Addresses below are documentation-range examples (RFC 5737).
"""
import logging
import os
import subprocess
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


# What the collector runs for a bills-only Oklahoma run (cloud_collector.py: `os-update <source>
# --scrape bills session=<s> --cachedir .. --datadir ..`), here in a child process through
# os-update's own main() so its real logging setup decides what reaches the log. The only fakes
# are at the network edge: the address lookup answers a documentation-range address and the
# legislature's site times out on connect, as in OPEN-887.
ENTRY = """
import sys, requests
from requests.adapters import HTTPAdapter
def send(self, request, **kwargs):
    if "api.ipify.org" in request.url:
        r = requests.Response()
        r.status_code, r._content, r.url = 200, MODE_LOOKUP, request.url
        if r._content is None:
            raise requests.exceptions.ConnectTimeout("lookup timed out")
        return r
    raise requests.exceptions.ConnectTimeout(
        "HTTPSConnectionPool(host='webapps.oklegislature.gov', port=443): "
        "Max retries exceeded (Caused by ConnectTimeoutError(connect timeout=60))"
    )
HTTPAdapter.send = send
from openstates.cli.update import main
sys.argv = ["os-update", "ok", "--scrape", "bills", "session=2026",
            "--cachedir", sys.argv[1], "--datadir", sys.argv[2]]
sys.exit(main())
"""


def run_collector_entry(tmp_path, lookup):
    script = ENTRY.replace("MODE_LOOKUP", repr(lookup))
    env = dict(
        os.environ,
        PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "scrapers"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    out = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "cache"), str(tmp_path / "data")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return out.returncode, out.stdout + out.stderr


def test_the_run_logs_the_address_and_the_first_requests_connection_error(tmp_path):
    code, log = run_collector_entry(tmp_path, b"203.0.113.7\n")
    assert code != 0  # the run fails on the timeout, as the real one did
    lines = log.splitlines()
    egress = [i for i, m in enumerate(lines) if "OK egress address: 203.0.113.7" in m]
    error = [
        i
        for i, m in enumerate(lines)
        if "OK connection error: ConnectTimeout after" in m
    ]
    assert len(egress) == 1  # once per run
    assert len(error) == 1
    assert egress[0] < error[0]
    assert (
        "GET https://webapps.oklegislature.gov/WebApplication3/WebForm1.aspx"
        in lines[error[0]]
    )
    assert "connect timeout=60" in lines[error[0]]


def test_a_failed_address_lookup_is_logged_and_the_run_goes_on(tmp_path):
    code, log = run_collector_entry(tmp_path, None)
    assert "OK egress address: lookup failed (ConnectTimeout)" in log
    assert (
        "OK connection error: ConnectTimeout" in log
    )  # still reached the session list


def test_an_odd_lookup_answer_is_not_logged(tmp_path):
    _, log = run_collector_entry(tmp_path, b"<html>502 Bad Gateway</html>")
    assert "OK egress address: lookup failed (ValueError)" in log
    assert "Bad Gateway" not in log


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
