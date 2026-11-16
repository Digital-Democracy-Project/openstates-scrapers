"""OPEN-574: Pennsylvania's incremental bill scrape, driven by the legislature's daily
"Bill History Data" export (https://www.palegis.us/data).

The fixture is seven real bills cut, unchanged, out of the 2025-2026 export downloaded on
2026-11-15 (exportDate "November 15, 2026 7:30:14 PM EST"); the bill-index links are copied
from the real 2025 House bill-index page of the same day. No request leaves the test.
"""
import datetime
import io
import os
import zipfile
from unittest import mock

import lxml.html
import pytest
from openstates.exceptions import EmptyScrape

from pa import bills as pa_bills
from pa import utils
from pa.bills import PABillScraper

FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "pa_open574",
    "PA-Bill-History-2025-RegularSession-sample.xml",
)
EXPORT_URL = (
    "https://www.palegis.us/data/file?documentType=BillHistoryData&session=2025_0"
)
UTC = datetime.timezone.utc
# the fixture's exportDate, 7:30:14 PM EST on 2026-11-15
EXPORT_DATE = datetime.datetime(2026, 11, 16, 0, 30, 14, tzinfo=UTC)

LINKS = [
    # real links from the 2025 House bill-index page (2026-11-15)
    '<a class="bill" data-id="172846" href="/legislation/bills/2025/hb17" data-number="17">HB 17</a>',
    '<a class="bill" data-id="174992" href="/legislation/bills/2025/hb1088" data-number="1088">HB 1088</a>',
    '<a class="bill" data-id="179298" href="/legislation/bills/2025/hb2659" data-number="2659">HB 2659</a>',
    # HB 2891 is not in the fixture export: it stands for a bill filed after the export
    '<a class="bill" data-id="180027" href="/legislation/bills/2025/hb2891" data-number="2891">HB 2891</a>',
    '<a class="bill" data-id="179461" href="/legislation/bills/2025/hr590" data-number="590">HR 590</a>',
    '<a class="bill" data-id="180028" href="/legislation/bills/2025/hr676" data-number="676">HR 676</a>',
]


def xml_bytes():
    with open(FIXTURE, "rb") as f:
        return f.read()


def zipped_export():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("PA-Bill-History-2025-RegularSession.xml", xml_bytes())
    return buf.getvalue()


def make_scraper(
    links=LINKS, export=None, now=EXPORT_DATE + datetime.timedelta(hours=4)
):
    scraper = PABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.jurisdiction = mock.Mock(legislative_sessions=[{"identifier": "2025-2026"}])
    index = lxml.html.fromstring("<html><body>%s</body></html>" % "".join(links))
    scraper.get_page = mock.Mock(return_value=index)
    scraper.get = mock.Mock(
        return_value=mock.Mock(content=zipped_export() if export is None else export)
    )
    scraper.parsed = []

    def parse_bill(chamber, session, special, link):
        scraper.parsed.append(link.text.strip())
        return iter(())

    scraper.parse_bill = parse_bill
    patcher = mock.patch.object(pa_bills, "_utcnow", return_value=now)
    patcher.start()
    return scraper, patcher


def run(scraper, patcher, **kwargs):
    try:
        return list(scraper.scrape(chamber="lower", session="2025-2026", **kwargs))
    finally:
        patcher.stop()


# --- the export reader -------------------------------------------------------------


def test_export_date_and_every_bill_is_known():
    export_date, changed, known = utils.bills_changed_since(
        xml_bytes(), datetime.datetime(2030, 1, 1, tzinfo=UTC)
    )
    assert export_date == EXPORT_DATE
    assert known == {"HB17", "HB1088", "HB1505", "HB2659", "HR590", "HR676", "SR414"}
    assert changed == set()


def test_last_update_is_read_as_eastern_time_to_the_minute():
    # HB 2659's lastUpdate is "November 10, 2026 12:05:00 PM EST" (17:05 UTC) and its last
    # action is from June, so only lastUpdate can select it: a change that is not an action
    since = datetime.datetime(2026, 11, 10, 17, 5, tzinfo=UTC)
    _, changed, _ = utils.bills_changed_since(xml_bytes(), since)
    assert changed == {"HB2659", "HR676", "SR414"}
    _, changed, _ = utils.bills_changed_since(
        xml_bytes(), since + datetime.timedelta(minutes=1)
    )
    assert "HB2659" not in changed


def test_an_action_newer_than_last_update_still_selects_the_bill():
    # HR 590: lastUpdate "September 8, 2026 1:05:01 PM EDT", yet its "Adopted, Sept. 9,
    # 2026" action is dated 09/10/26. lastUpdate alone would miss it.
    since = datetime.datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    _, changed, _ = utils.bills_changed_since(xml_bytes(), since)
    assert "HR590" in changed


def test_action_dates_are_compared_on_the_eastern_day_not_the_utc_day():
    # HB 1505: lastUpdate "July 12, 2026 6:05:01 PM EDT"; its last actions are dated
    # 07/13/26. A cutoff of 2026-07-14 02:00 UTC is still July 13 (10 PM EDT) in
    # Pennsylvania, so the July 13 actions are on or after it; a UTC-day comparison
    # (July 14) would drop the bill.
    since = datetime.datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
    _, changed, _ = utils.bills_changed_since(xml_bytes(), since)
    assert "HB1505" in changed
    # the next Eastern day no longer reaches them
    _, changed, _ = utils.bills_changed_since(
        xml_bytes(), datetime.datetime(2026, 7, 14, 4, 0, tzinfo=UTC)
    )
    assert "HB1505" not in changed


def test_bill_key_matches_index_link_text():
    assert utils.bill_key("HB 1088") == "HB1088"
    assert utils.bill_key("hr 590") == "HR590"


# --- scrape() --------------------------------------------------------------------


def test_incremental_fetches_only_changed_and_unlisted_bills():
    # start 2026-11-12 17:00 UTC, so the cutoff is 2026-11-10 17:00 UTC (two-day lookback)
    scraper, patcher = make_scraper()
    run(scraper, patcher, start="2026-11-12T17:00:00")
    scraper.get.assert_called_once()
    assert scraper.get.call_args.args[0] == EXPORT_URL
    assert scraper.parsed == ["HB 2659", "HB 2891", "HR 676"]


def test_lookback_reaches_two_days_before_start():
    # HB 2659 changed at 17:05 UTC on 11-10: one minute inside a start of 11-12 17:05
    scraper, patcher = make_scraper()
    run(scraper, patcher, start="2026-11-12T17:05:00")
    assert "HB 2659" in scraper.parsed
    scraper, patcher = make_scraper()
    run(scraper, patcher, start="2026-11-12T17:06:00")
    assert "HB 2659" not in scraper.parsed


def test_without_start_every_bill_is_fetched_and_the_export_is_not():
    scraper, patcher = make_scraper()
    run(scraper, patcher)
    scraper.get.assert_not_called()
    assert scraper.parsed == [
        "HB 17",
        "HB 1088",
        "HB 2659",
        "HB 2891",
        "HR 590",
        "HR 676",
    ]


@pytest.mark.parametrize(
    "export",
    [b"not a zip", b""],
    ids=["garbage", "empty"],
)
def test_unreadable_export_means_a_full_walk(export):
    scraper, patcher = make_scraper(export=export)
    run(scraper, patcher, start="2026-11-12T17:00:00")
    assert len(scraper.parsed) == len(LINKS)


def test_failed_export_download_means_a_full_walk():
    scraper, patcher = make_scraper()
    scraper.get.side_effect = RuntimeError("503")
    run(scraper, patcher, start="2026-11-12T17:00:00")
    assert len(scraper.parsed) == len(LINKS)


def test_stale_export_means_a_full_walk():
    stale_now = EXPORT_DATE + pa_bills.EXPORT_MAX_AGE + datetime.timedelta(minutes=1)
    scraper, patcher = make_scraper(now=stale_now)
    run(scraper, patcher, start="2026-11-12T17:00:00")
    assert len(scraper.parsed) == len(LINKS)
    fresh_now = EXPORT_DATE + pa_bills.EXPORT_MAX_AGE - datetime.timedelta(minutes=1)
    scraper, patcher = make_scraper(now=fresh_now)
    run(scraper, patcher, start="2026-11-12T17:00:00")
    assert len(scraper.parsed) == 3


def test_invalid_start_means_a_full_walk():
    scraper, patcher = make_scraper()
    run(scraper, patcher, start="last tuesday")
    scraper.get.assert_not_called()
    assert len(scraper.parsed) == len(LINKS)


def test_nothing_changed_is_an_empty_scrape_not_a_failure():
    scraper, patcher = make_scraper(links=LINKS[:2])  # HB 17 and HB 1088, both quiet
    with pytest.raises(EmptyScrape):
        run(scraper, patcher, start="2026-11-12T17:00:00")
    assert scraper.parsed == []


def test_a_full_walk_that_finds_nothing_is_not_turned_into_an_empty_scrape():
    scraper, patcher = make_scraper(links=[])
    assert run(scraper, patcher) == []
    scraper, patcher = make_scraper(links=[])
    # incremental, but the index page listed nothing: not a quiet week, leave it to do_scrape
    assert run(scraper, patcher, start="2026-11-12T17:00:00") == []
