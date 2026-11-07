import inspect
from unittest import mock

import pytest

from la.bills import LABillScraper
from ne.bills import NEBillScraper
from pa.bills import PABillScraper

START = "2026-11-03T04:12:48"


def make(cls, sessions):
    scraper = cls(jurisdiction="x", datadir="/tmp")
    scraper.jurisdiction = mock.Mock(legislative_sessions=sessions)
    return scraper


def test_pa_scrape_accepts_start_and_still_walks_both_chambers():
    """OPEN-500: run-scrape.sh appends start=<watermark> on every run after the first; PA's
    second run died with TypeError. start must be accepted and must not change what is scraped."""
    scraper = make(PABillScraper, [{"identifier": "2025-2026"}])
    with mock.patch.object(scraper, "scrape_session", return_value=iter(())) as walk:
        list(scraper.scrape(session="2025-2026", start=START))
    assert [c.args for c in walk.call_args_list] == [
        ("upper", "2025-2026"),
        ("lower", "2025-2026"),
    ]


def test_la_scrape_accepts_start_and_still_walks_both_chambers():
    scraper = make(LABillScraper, [{"identifier": "2026", "start_date": "2026-03-09"}])
    with mock.patch.object(
        scraper, "scrape_chamber", create=True, return_value=iter(())
    ):
        with mock.patch.object(scraper, "lxmlize", side_effect=RuntimeError("stop")):
            # LA fetches its first listing page right after the argument handling; reaching
            # that call (not a TypeError) is the proof start= was accepted.
            with pytest.raises(RuntimeError, match="stop"):
                list(scraper.scrape(session="2026", start=START))


def test_ne_scrape_accepts_start_and_still_walks_the_session_years():
    session = {
        "identifier": "109",
        "classification": "primary",
        "start_date": "2025-01-08",
        "end_date": "2026-04-17",
    }
    scraper = make(NEBillScraper, [session])
    with mock.patch.object(scraper, "scrape_priorities"):
        with mock.patch.object(scraper, "scrape_year", return_value=iter(())) as year:
            list(scraper.scrape(session="109", start=START))
    assert [c.args for c in year.call_args_list] == [("109", 2025), ("109", 2026)]


@pytest.mark.parametrize("cls", [PABillScraper, NEBillScraper, LABillScraper])
def test_start_defaults_to_none_and_old_call_shape_still_binds(cls):
    sig = inspect.signature(cls.scrape)
    assert sig.parameters["start"].default is None
    sig.bind(None, session="x")  # the pre-OPEN-500 call shape
