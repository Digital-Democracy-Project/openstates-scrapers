"""OPEN-853: Washington scrapes 2025-2026 and 2027-2028 in one run, before 2027-2028 convenes.

openstates-core scrapes every active session one after the other in the same process, with a new
scraper for each (cli/update.py do_scrape), and fails the whole run when one session yields
nothing (scrape/base.py do_scrape). So:
* the second session must not start with the first one's bill list or version links;
* 2027-2028 before pre-filing opens (no bills listed) must not fail the run, while a session
  that has convened and lists nothing still does;
* an incremental run where one session has no change since the cutoff must not stop the other.

Fixtures (tests/fixtures/wa_open853), from wslwebservices.leg.wa.gov on 2026-11-24:
* GetPreFiledLegislationInfo_2026-11-24.xml and GetLegislationByYear_2027_2026-11-24.xml: the
  real, empty answers before pre-filing opened;
* GetLegislationByYear_2026_trimmed.xml: the real 2026 list cut to four records (HB 1000,
  SB 5001, the appointment SGA 9016, the initiative HI IL26-001);
* GetPreFiledLegislationInfo_handbuilt.xml: built by hand in the same record shape (no bill was
  pre-filed yet): HB 1001, SB 5002 and SGA 9001 in 2027-28, HB 1999 in 2025-26.
"""
import datetime
import os
import sys

import pytest
import scrapelib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.exceptions import EmptyScrape, ScrapeError  # noqa: E402
from wa import Washington  # noqa: E402
from wa.bills import WABillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wa_open853")
PREFILED_EMPTY = "GetPreFiledLegislationInfo_2026-11-24.xml"
PREFILED_HANDBUILT = "GetPreFiledLegislationInfo_handbuilt.xml"
BY_YEAR = {
    2025: "GetLegislationByYear_2026_trimmed.xml",
    2026: "GetLegislationByYear_2026_trimmed.xml",
    2027: "GetLegislationByYear_2027_2026-11-24.xml",
}


class _Response:
    def __init__(self, name):
        with open(os.path.join(FIXTURES, name), "rb") as f:
            self.content = f.read()


@pytest.fixture(autouse=True)
def _wa_date(monkeypatch):
    """Freeze the bill scraper's today at 2026-11-24 (2027-2028 not convened)."""
    set_today(monkeypatch, datetime.date(2026, 11, 24))


def set_today(monkeypatch, day):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(datetime, "date", FrozenDate)


def make_scraper(tmp_path, prefiled=PREFILED_EMPTY, versions_page=None):
    """A WA bill scraper reading the fixtures. scrape_bill is replaced by a recorder that yields
    one placeholder per bill (or nothing, with quiet=True, as when a bill predates start=)."""
    s = WABillScraper(Washington(), str(tmp_path))
    s.fetched, s.scraped, s.quiet = [], [], False
    # the year lists are cached on the class, by year (2025-26 and 2027-28 share no year); each
    # test reads its own
    s._legislation_by_year = {}

    def get(url, *args, **kwargs):
        s.fetched.append(url)
        if url.endswith("/GetPreFiledLegislationInfo"):
            return _Response(prefiled)
        if "GetLegislationByYear?year=" in url:
            return _Response(BY_YEAR[int(url.rsplit("=", 1)[1])])
        raise AssertionError(f"unexpected fetch {url}")

    def lxmlize(url, *args, **kwargs):
        # the version and document listings: 2025-26 House Bills has one version, the rest 404
        import lxml.html

        if versions_page and versions_page in url:
            return lxml.html.fromstring(
                '<html><body><a href="..">up</a>'
                f'<a href="{url}/1000.htm">1000.htm</a></body></html>'
            )
        raise scrapelib.HTTPError(_NotFound(url))

    def scrape_bill(chamber, session, bill_id, year):
        s.scraped.append((session, bill_id, list(s.versions.get(bill_id, []))))
        if not s.quiet:
            yield (session, bill_id)

    s.get = get
    s.lxmlize = lxmlize
    s.scrape_bill = scrape_bill
    return s


class _NotFound:
    status_code = 404
    text = "404 - File or directory not found."

    def __init__(self, url):
        self.url = url


def scraped_ids(s):
    return sorted(bill_id for _, bill_id, _ in s.scraped)


def test_pre_filed_bills_are_read_for_their_own_biennium(tmp_path):
    s = make_scraper(tmp_path, prefiled=PREFILED_HANDBUILT)
    s.biennium = "2027-28"
    s._bill_id_list = []
    # HB 1999 is 2025-26's, SGA 9001 is an appointment: neither is a 2027-2028 bill to scrape
    assert s.get_prefiles(None, "2027-2028", 2027) == ["HB 1001", "SB 5002"]


def test_2027_28_scrapes_its_pre_filed_bills(tmp_path):
    s = make_scraper(tmp_path, prefiled=PREFILED_HANDBUILT)
    list(s.scrape(session="2027-2028"))
    assert scraped_ids(s) == ["HB 1001", "SB 5002"]
    assert {session for session, _, _ in s.scraped} == {"2027-2028"}


def test_2025_26_is_unchanged_and_ignores_2027_28_pre_files(tmp_path):
    s = make_scraper(tmp_path, prefiled=PREFILED_HANDBUILT)
    list(s.scrape(session="2025-2026"))
    # the bills of its own year lists, as before (the appointment and the initiative skipped),
    # plus the one pre-file record of its own biennium (HB 1999); none of 2027-28's pre-files
    assert scraped_ids(s) == ["HB 1000", "HB 1999", "SB 5001"]


def test_a_year_list_holding_the_other_bienniums_bills_keeps_only_its_own(tmp_path):
    s = make_scraper(tmp_path)
    s.biennium = "2025-26"
    s._bill_id_list = []
    s._legislation_by_year = {
        2025: _parse(PREFILED_HANDBUILT),
        2026: _parse(BY_YEAR[2027]),
    }
    s.scrape_chamber("lower", "2025-2026")
    s.scrape_chamber("upper", "2025-2026")
    # HB 1001 and SB 5002 are 2027-28's; HB 1999 is 2025-26's
    assert sorted(s._bill_id_list) == ["HB 1999"]


def _parse(name):
    import lxml.etree

    return lxml.etree.fromstring(_Response(name).content)


def test_the_second_session_does_not_start_with_the_firsts_bills_or_versions(tmp_path):
    # the order openstates-core may use: 2025-2026 first, then a new scraper for 2027-2028
    first = make_scraper(
        tmp_path, versions_page="/Biennium/2025-26/Htm/Bills/House Bills"
    )
    list(first.scrape(session="2025-2026"))
    assert ("2025-2026", "HB 1000") in [(a, b) for a, b, _ in first.scraped]
    assert first.versions["HB 1000"]  # the 2025-26 version links were loaded

    second = make_scraper(tmp_path, prefiled=PREFILED_HANDBUILT)
    list(second.scrape(session="2027-2028"))
    assert scraped_ids(second) == ["HB 1001", "SB 5002"]
    assert second.versions == {}


def test_2027_28_with_no_bills_before_it_convenes_does_not_fail_the_run(tmp_path):
    s = make_scraper(tmp_path)
    with pytest.raises(EmptyScrape):
        list(s.scrape(session="2027-2028"))
    # and openstates-core's own do_scrape takes that as a quiet session, not a failure
    record = make_scraper(tmp_path).do_scrape(session="2027-2028")
    assert sum(record["objects"].values()) == 0


@pytest.mark.parametrize(
    "answer",
    [
        "http-error",
        b"<html><body>Service unavailable</body></html>",
        b"not xml at all",
        b'<?xml version="1.0"?><ArrayOfLegislation xmlns="http://WSLWebServices.leg.wa.gov/" />',
    ],
)
def test_a_failed_pre_file_read_before_it_convenes_still_fails(tmp_path, answer):
    s = make_scraper(tmp_path)
    year_lists = s.get

    class _Raw:
        content = answer

    def get(url, *a, **k):
        if url.endswith("/GetPreFiledLegislationInfo"):
            if answer == "http-error":
                raise scrapelib.HTTPError(_NotFound(url))
            return _Raw()
        return year_lists(url, *a, **k)

    s.get = get
    with pytest.raises(ScrapeError, match="no objects returned"):
        s.do_scrape(session="2027-2028")


def test_2027_28_with_no_bills_after_it_convenes_still_fails(monkeypatch, tmp_path):
    set_today(monkeypatch, datetime.date(2027, 1, 11))
    with pytest.raises(ScrapeError, match="no objects returned"):
        make_scraper(tmp_path).do_scrape(session="2027-2028")


def test_2025_26_listing_nothing_still_fails(monkeypatch, tmp_path):
    s = make_scraper(tmp_path)
    s.get = lambda url, *a, **k: _Response(
        PREFILED_EMPTY
        if url.endswith("/GetPreFiledLegislationInfo")
        else BY_YEAR[2027]  # an empty year list
    )
    with pytest.raises(ScrapeError, match="no objects returned"):
        s.do_scrape(session="2025-2026")


START = "2026-11-23T02:30:00"


def test_incremental_with_no_change_in_one_session_does_not_fail_the_run(tmp_path):
    s = make_scraper(tmp_path)
    s.quiet = True  # every listed bill predates start=
    with pytest.raises(EmptyScrape):
        list(s.scrape(session="2025-2026", start=START))
    assert scraped_ids(s) == ["HB 1000", "SB 5001"]


def test_an_empty_bill_answer_in_an_incremental_run_is_an_error_not_a_quiet_session(
    tmp_path,
):
    # the real scrape_bill: HB 1000 is not in the bulk list (the real, empty answer of
    # 2026-11-24), and GetLegislation answers with no record. That raises; it is not taken as
    # "no change since the cutoff".
    s = make_scraper(tmp_path)
    del s.scrape_bill
    year_lists = s.get
    empty = "GetLegislationIntroducedSince_2026-11-01_2026-11-24.xml"

    def get(url, *a, **k):
        if "GetLegislationIntroducedSince" in url or "GetLegislation?" in url:
            return _Response(empty)
        return year_lists(url, *a, **k)

    s.get = get
    with pytest.raises(IndexError):
        s.do_scrape(session="2025-2026", start=START)


def test_a_full_run_that_yields_nothing_still_fails(tmp_path):
    s = make_scraper(tmp_path)
    s.quiet = True
    with pytest.raises(ScrapeError, match="no objects returned"):
        s.do_scrape(session="2025-2026")


def test_an_incremental_run_with_changes_is_not_empty(tmp_path):
    s = make_scraper(tmp_path)
    assert sorted(s.scrape(session="2025-2026", start=START)) == [
        ("2025-2026", "HB 1000"),
        ("2025-2026", "SB 5001"),
    ]


def test_a_targeted_bill_no_run_keeps_its_own_handling(tmp_path):
    s = make_scraper(tmp_path)
    s.quiet = True
    # bill_no= with nothing yielded is not swallowed as an empty session
    assert list(s.scrape(session="2025-2026", start=START, bill_no="HB1000")) == []
