import tempfile

import pytest

from openstates.exceptions import EmptyScrape

from va.bills import VaBillScraper


class _FakeJurisdiction:
    legislative_sessions = [
        {"identifier": "2026", "extras": {"session_code": "20261"}}
    ]


def make_scraper():
    return VaBillScraper(_FakeJurisdiction(), tempfile.mkdtemp())


def _bill_row(number, chamber_code="H", legislation_id="1"):
    return {
        "LegislationNumber": number,
        "Description": f"A bill about {number}",
        "LegislationTitle": None,
        "LegislationSummary": None,
        "ChamberCode": chamber_code,
        "LegislationID": legislation_id,
        "SummaryVersion": None,
    }


def _event(date, description="Referred to Committee"):
    return {
        "EventDate": date,
        "Description": description,
        "VoteTally": None,
        "ChamberCode": "H",
        "ActorType": None,
        "ReferenceNumber": None,
        "LegislationEventID": "e1",
    }


class _FakeListResponse:
    def __init__(self, bill_rows):
        self._bill_rows = bill_rows

    def json(self):
        return {"Legislations": self._bill_rows}


def _mock_bill_list(monkeypatch, bill_rows, api_key="test-key"):
    if api_key is not None:
        monkeypatch.setenv("VA_API_KEY", api_key)
    else:
        monkeypatch.delenv("VA_API_KEY", raising=False)

    monkeypatch.setattr(
        "va.bills.requests.post",
        lambda *args, **kwargs: _FakeListResponse(bill_rows),
    )


def _mock_downstream(monkeypatch, events_by_id=None):
    # _fetch_events is the one call scrape() makes unconditionally (before the cutoff
    # decision) -- these are the calls that only happen once a bill has actually cleared
    # the cutoff check, so mocking them out isolates the thing this ticket changes: whether
    # scrape() raises EmptyScrape, not the real VA API's response shapes.
    events_by_id = events_by_id or {}

    def fake_fetch_events(self, legislation_id):
        return events_by_id.get(legislation_id, [])

    monkeypatch.setattr(VaBillScraper, "_fetch_events", fake_fetch_events)
    monkeypatch.setattr(
        VaBillScraper, "add_versions", lambda self, bill, legislation_id: None
    )
    monkeypatch.setattr(
        VaBillScraper, "add_sponsors", lambda self, bill, legislation_id: None
    )
    monkeypatch.setattr(
        VaBillScraper, "add_votes", lambda self, bill, legislation_id: iter(())
    )


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-220: a real incremental window with zero new bills must raise EmptyScrape, not let
# openstates-core's do_scrape() hard-fail the whole run -- mirrors usa/bills.py's OPEN-216
# fix and ut/bills.py's original EmptyScrape precedent. Applies that pair's round-1
# pm-review lesson proactively: the guard is keyed on whether a real candidate was newer
# than the cutoff, never on whether it was actually yielded, so a genuine downstream
# failure isn't swallowed as a benign no-op.
# ═══════════════════════════════════════════════════════════════════════════


def test_incremental_scrape_with_zero_new_bills_raises_empty_scrape(monkeypatch):
    rows = [_bill_row("HB1", legislation_id="1"), _bill_row("HB2", legislation_id="2")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(
        monkeypatch,
        events_by_id={
            "1": [_event("2020-01-01T00:00:00")],
            "2": [_event("2019-06-01T00:00:00")],
        },
    )
    scraper = make_scraper()

    with pytest.raises(EmptyScrape):
        list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))


def test_full_scrape_with_zero_bills_does_not_raise_empty_scrape(monkeypatch):
    # No start= -- a full scrape finding nothing is still worth a hard failure, unchanged
    # by this fix. scrape() itself never raises ScrapeError directly (that's
    # openstates-core's do_scrape(), one layer up, not re-tested here); this only confirms
    # the new guard doesn't fire outside the incremental case.
    _mock_bill_list(monkeypatch, [])
    _mock_downstream(monkeypatch)
    scraper = make_scraper()

    assert list(scraper.scrape(session="2026")) == []


def test_incremental_scrape_with_no_real_candidates_does_not_raise_empty_scrape(monkeypatch):
    # An empty bill list (e.g. a session with nothing filed yet) leaves candidates_seen at
    # 0 -- this must not be mistaken for "asked and got nothing new". A genuinely broken
    # source is covered separately below (missing VA_API_KEY).
    _mock_bill_list(monkeypatch, [])
    _mock_downstream(monkeypatch)
    scraper = make_scraper()

    assert list(scraper.scrape(session="2026", start="2026-01-01T00:00:00")) == []


def test_incremental_scrape_with_a_real_newer_bill_does_not_raise_empty_scrape(monkeypatch):
    rows = [_bill_row("HB1", legislation_id="1")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(
        monkeypatch, events_by_id={"1": [_event("2026-06-01T00:00:00")]}
    )
    scraper = make_scraper()

    results = list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))

    assert len(results) == 1
    assert results[0].identifier == "HB1"


def test_incremental_scrape_with_no_event_history_does_not_raise_empty_scrape(monkeypatch):
    # A candidate with zero fetched events has nothing to compare against the cutoff, so
    # the pre-existing cutoff check (bills.py, the `if event_dates:` guard) lets it through
    # unconditionally. That must count as "newer than cutoff", not as evidence supporting a
    # benign no-op.
    rows = [_bill_row("HB1", legislation_id="1")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(monkeypatch, events_by_id={"1": []})
    scraper = make_scraper()

    results = list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))

    assert len(results) == 1


def test_invalid_start_falls_back_to_full_scrape_and_does_not_raise_empty_scrape(
    monkeypatch,
):
    # bills.py already treats an unparseable start= as a full scrape (with its own
    # warning) -- is_incremental must track that real fallback, not the raw presence of
    # start=, so this must behave identically to the no-start= case above.
    rows = [_bill_row("HB1", legislation_id="1")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(
        monkeypatch, events_by_id={"1": [_event("2020-01-01T00:00:00")]}
    )
    scraper = make_scraper()

    warnings = []
    scraper.warning = lambda msg: warnings.append(msg)

    results = list(scraper.scrape(session="2026", start="not-a-real-date"))

    assert len(results) == 1
    assert any("Invalid start=" in w for w in warnings)


def test_bill_no_targeting_does_not_raise_empty_scrape_even_with_zero_newer_matches(
    monkeypatch,
):
    # bill_no= targeting has its own separate zero-match handling (a warning per missing
    # bill, matching USA's OPEN-123 pattern) -- the new EmptyScrape guard must never apply
    # while it's active, regardless of whether the matched bill(s) are older than the
    # incremental cutoff. (Unlike USA, VA's bill_no= filter does not itself bypass the
    # cutoff check -- that's a pre-existing, separate behavior this ticket doesn't touch.)
    rows = [_bill_row("HB1", legislation_id="1"), _bill_row("HB2", legislation_id="2")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(
        monkeypatch, events_by_id={"1": [_event("2020-01-01T00:00:00")]}
    )
    scraper = make_scraper()

    results = list(
        scraper.scrape(session="2026", start="2026-01-01T00:00:00", bill_no="HB1")
    )

    assert results == []


def test_missing_api_key_does_not_raise_empty_scrape_on_incremental_run(monkeypatch):
    # AC2: a genuinely broken/misconfigured source (no API key -- can't even fetch the
    # bill list) must not be mistaken for "nothing changed". scrape() returns before
    # bill_list is ever fetched, so candidates_seen stays 0 and the EmptyScrape guard never
    # fires -- openstates-core's own do_scrape() still raises the ordinary ScrapeError for
    # "yielded nothing", exactly as it did before this fix.
    _mock_bill_list(monkeypatch, [], api_key=None)
    scraper = make_scraper()

    errors = []
    scraper.error = lambda msg: errors.append(msg)

    results = list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))

    assert results == []
    assert len(errors) == 1


def test_missing_legislations_key_does_not_raise_empty_scrape(monkeypatch):
    # pm-review: a malformed bill-list response (unexpected shape) must still surface as a
    # real exception, not be masked as EmptyScrape -- candidates_seen is only ever touched
    # inside the per-row loop, which this never reaches.
    monkeypatch.setenv("VA_API_KEY", "test-key")

    class _BadResponse:
        def json(self):
            return {"UnexpectedShape": True}

    monkeypatch.setattr("va.bills.requests.post", lambda *args, **kwargs: _BadResponse())
    scraper = make_scraper()

    with pytest.raises(KeyError):
        list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))


def test_bill_list_json_decode_failure_does_not_raise_empty_scrape(monkeypatch):
    # Same shape as above, for the case where the response body itself isn't valid JSON at
    # all rather than just being missing a key.
    monkeypatch.setenv("VA_API_KEY", "test-key")

    class _BrokenResponse:
        def json(self):
            raise ValueError("not valid JSON")

    monkeypatch.setattr(
        "va.bills.requests.post", lambda *args, **kwargs: _BrokenResponse()
    )
    scraper = make_scraper()

    with pytest.raises(ValueError):
        list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))


@pytest.mark.parametrize("method_name", ["add_versions", "add_sponsors"])
def test_downstream_failure_propagates_not_masked_as_empty_scrape(monkeypatch, method_name):
    # pm-review: the property claimed in this fix's comments/PR body -- that a real failure
    # in add_versions/add_sponsors/add_votes still surfaces as a hard failure, never gets
    # silently converted into EmptyScrape -- proven directly rather than only asserted. This
    # bill is genuinely newer than the cutoff (newer_than_cutoff gets incremented for it)
    # before the failure hits, so a masking bug would show up as a swallowed exception here.
    rows = [_bill_row("HB1", legislation_id="1")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(monkeypatch, events_by_id={"1": [_event("2026-06-01T00:00:00")]})

    class _Boom(Exception):
        pass

    def raise_boom(self, bill, legislation_id):
        raise _Boom("simulated downstream failure")

    monkeypatch.setattr(VaBillScraper, method_name, raise_boom)
    scraper = make_scraper()

    with pytest.raises(_Boom):
        list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))


def test_downstream_add_votes_failure_propagates_not_masked_as_empty_scrape(monkeypatch):
    # add_votes is consumed via `yield from` (it's a generator, unlike add_versions/
    # add_sponsors), so it needs its own generator-shaped failure rather than the
    # parametrized case above.
    rows = [_bill_row("HB1", legislation_id="1")]
    _mock_bill_list(monkeypatch, rows)
    _mock_downstream(monkeypatch, events_by_id={"1": [_event("2026-06-01T00:00:00")]})

    class _Boom(Exception):
        pass

    def raise_boom(self, bill, legislation_id):
        raise _Boom("simulated downstream failure")
        yield  # pragma: no cover -- unreachable, makes this a generator function

    monkeypatch.setattr(VaBillScraper, "add_votes", raise_boom)
    scraper = make_scraper()

    with pytest.raises(_Boom):
        list(scraper.scrape(session="2026", start="2026-01-01T00:00:00"))
