from unittest import mock

from nc.bills import NCBillScraper


def make_scraper():
    return NCBillScraper(jurisdiction="nc", datadir="/tmp")


def test_scrape_accepts_the_start_argument_both_runners_pass_on_every_incremental_run():
    """OPEN-321: run-scrape.sh and cloud_collector.py append start=<watermark> whenever a
    watermark exists. NC's second run crashed on it (TypeError: unexpected keyword argument
    'start'); it must be accepted, and must not change what gets scraped."""
    scraper = make_scraper()

    with mock.patch.object(scraper, "scrape_chamber", return_value=iter(())) as chamber:
        list(scraper.scrape(session="2025", start="2026-10-01T00:00:00"))

    assert [c.args for c in chamber.call_args_list] == [
        ("upper", "2025"),
        ("lower", "2025"),
    ]


def test_scrape_without_start_is_unchanged():
    scraper = make_scraper()

    with mock.patch.object(scraper, "scrape_chamber", return_value=iter(())) as chamber:
        list(scraper.scrape(session="2025", chamber="lower"))

    assert [c.args for c in chamber.call_args_list] == [("lower", "2025")]
