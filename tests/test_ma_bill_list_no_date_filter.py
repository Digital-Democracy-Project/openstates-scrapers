"""Tests for OPEN-128: MA's bill-list filter gated on the newest sponsor `ResponseDate`.

Sponsorship is set at filing and a later action never touches it, so a bill that passed a
chamber, was amended, or became a Public Act kept its original sponsor date, failed the filter,
and was skipped on every incremental run -- its actions then went stale indefinitely. Measured
against the production database, 8,098 of 11,289 MA bills (71%) have activity the sponsor date
cannot reflect, on the order of 80-100 bills a week.

The fix stops filtering. These tests pin that: `start` is still accepted, and it no longer
removes anything from the list. The filter had no test coverage at all before this file, which
is part of why it survived so long.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

SESSION = "194th"

# Shaped like the real /api/GeneralCourts/194/Documents payload: nine fields per record, and
# the sponsors' ResponseDate as the only date anywhere in it.
LIST_PAYLOAD = [
    {
        # The case the bug was about: sponsor date long before any plausible cutoff, but the
        # bill has since moved. Under the old filter this was skipped forever.
        "BillNumber": "H4010",
        "DocketNumber": "HD1234",
        "Title": "An Act making appropriations",
        "PrimarySponsor": {"ResponseDate": "2025-01-15T00:00:00.000"},
        "Cosponsors": [{"ResponseDate": "2025-01-16T00:00:00.000"}],
        "JointSponsor": None,
        "GeneralCourtNumber": 194,
        "Details": "/Bills/194/H4010",
        "IsDocketBookOnly": False,
    },
    {
        "BillNumber": "S2168",
        "DocketNumber": "SD999",
        "Title": "An Act relative to something",
        "PrimarySponsor": None,          # real payloads have these
        "Cosponsors": [],
        "JointSponsor": None,
        "GeneralCourtNumber": 194,
        "Details": "/Bills/194/S2168",
        "IsDocketBookOnly": False,
    },
    {
        # Recent sponsor date -- passed the old filter too, so it must not regress.
        "BillNumber": "H99",
        "DocketNumber": "HD5",
        "Title": "A third act",
        "PrimarySponsor": {"ResponseDate": "2026-08-20T00:00:00.000"},
        "Cosponsors": [],
        "JointSponsor": None,
        "GeneralCourtNumber": 194,
        "Details": "/Bills/194/H99",
        "IsDocketBookOnly": False,
    },
]


def make_scraper(payload=None) -> MABillScraper:
    scraper = MABillScraper(Massachusetts(), "/tmp/")
    scraper.house_pdf_cache = {}
    scraper.bill_list = []
    resp = mock.Mock()
    resp.content = __import__("json").dumps(
        LIST_PAYLOAD if payload is None else payload
    ).encode()
    scraper.get = mock.Mock(return_value=resp)
    scraper.info = mock.Mock()
    scraper.error = mock.Mock()
    return scraper


def queued(scraper):
    return [b["BillNumber"] for b in scraper.bill_list]


def test_every_bill_is_queued_when_start_is_given():
    """The regression guard for the actual bug.

    Two of the three fixtures have sponsor dates far older than this cutoff. Under the old
    filter they were dropped; all three must now be queued.
    """
    s = make_scraper()
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    assert queued(s) == ["H4010", "S2168", "H99"]


def test_a_bill_whose_sponsor_date_predates_the_cutoff_is_still_queued():
    # Stated separately from the test above because this single bill IS the bug: a stale sponsor
    # date on a bill that has since acted.
    s = make_scraper([LIST_PAYLOAD[0]])
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    assert queued(s) == ["H4010"]


def test_start_and_no_start_produce_the_same_list():
    """`start` must make no difference to what gets queued.

    This is the property that matters, and it holds regardless of how the cutoff is expressed --
    stronger than asserting against one hardcoded expected list.
    """
    with_start = make_scraper()
    with_start.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    without = make_scraper()
    without.scrape_bill_list(SESSION)
    assert queued(with_start) == queued(without)


def test_an_unparseable_start_is_harmless():
    # The old code swallowed a ValueError here and fell through to no filtering. Nothing should
    # now depend on parsing it at all.
    s = make_scraper()
    s.scrape_bill_list(SESSION, start="not-a-date")
    assert queued(s) == ["H4010", "S2168", "H99"]


def test_records_with_no_sponsor_data_do_not_crash():
    # Real payloads carry PrimarySponsor: None and empty Cosponsors. The old filter had to guard
    # for it; the new code must not reintroduce a dependency on those fields.
    s = make_scraper([{
        "BillNumber": "S1",
        "DocketNumber": "SD1",
        "Title": "t",
        "PrimarySponsor": None,
        "Cosponsors": None,
        "JointSponsor": None,
        "GeneralCourtNumber": 194,
        "Details": "/Bills/194/S1",
        "IsDocketBookOnly": False,
    }])
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    assert queued(s) == ["S1"]


def test_docket_number_is_used_when_bill_number_is_absent():
    # Pre-existing behaviour worth pinning while this function is being edited: bill_id falls
    # back to DocketNumber, and the chamber sanity check reads that fallback.
    s = make_scraper([{
        "BillNumber": None,
        "DocketNumber": "HD77",
        "Title": "t",
        "PrimarySponsor": None,
        "Cosponsors": [],
        "JointSponsor": None,
        "GeneralCourtNumber": 194,
        "Details": "/Bills/194/HD77",
        "IsDocketBookOnly": False,
    }])
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    assert s.bill_list == [{"BillNumber": None, "DocketNumber": "HD77"}]
    s.error.assert_not_called()


def test_a_bill_id_with_no_chamber_letter_is_reported():
    # Also pre-existing, and the only use of self.error in this function.
    s = make_scraper([{
        "BillNumber": "12345",
        "DocketNumber": "12345",
        "Title": "t",
        "PrimarySponsor": None,
        "Cosponsors": [],
        "JointSponsor": None,
        "GeneralCourtNumber": 194,
        "Details": "/Bills/194/12345",
        "IsDocketBookOnly": False,
    }])
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    assert s.error.called


def test_the_ignored_start_is_announced_once():
    """An operator reading the log should be told the cutoff was ignored, and why.

    Without this the run looks like a normal incremental one while doing a full walk, which is a
    ~6 hour difference in behaviour.
    """
    s = make_scraper()
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    msgs = [c.args[0] for c in s.info.call_args_list if c.args]
    assert any("OPEN-128" in m and "ignoring start=" in m for m in msgs), msgs


def test_nothing_is_announced_when_no_start_was_passed():
    # A full scrape was never filtered, so there is no cutoff to report being ignored.
    s = make_scraper()
    s.scrape_bill_list(SESSION)
    msgs = [c.args[0] for c in s.info.call_args_list if c.args]
    assert not any("ignoring start=" in m for m in msgs), msgs


def test_the_list_endpoint_is_fetched_once_per_call():
    # The whole cost argument for this change rests on the listing being a single request and
    # the per-bill fetches being 1.01 requests each. If this function started fetching per bill
    # the economics in the ticket would be wrong.
    s = make_scraper()
    s.scrape_bill_list(SESSION, start="2026-08-01T00:00:00")
    assert s.get.call_count == 1
