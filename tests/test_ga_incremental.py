"""OPEN-604: Georgia's catch-up bill scrape, from the search service's status-date filter
and the session's roll-call list.

The fixtures are Georgia's own answers (webservices.legis.ga.gov, read 2026-11-16), saved as
JSON and cut, unchanged, to thirteen 2025_26 bills: their GetLegislationForSession entries,
their rows from a whole-session GetLegislationSearchResultsPaged read, and their GetVotes
listings (for HB 307 only House Vote #113), plus each chamber's vote #1 (a roll call on no
bill) and Senate Vote #134 (SB 56), which Georgia published before HB 307's #113.

The search rows hold each bill's current status as of 2026-11-16, so the run dates below are
chosen where that is also the status a run on that date would have seen.

The fake search answers as the real one was measured to: it matches a bill's current status
only (the ExistingStatusConstraint fails on the service), and compares dates by calendar day
with both ends inclusive (03-06 15:00 to 03-06 15:00 returned all 140 bills of 03-06). It
pages by row offset, as the service does. No request leaves the test.
"""
import datetime
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

# the scraper builds its SOAP clients (a WSDL fetch) when the module loads
with mock.patch("suds.client.Client"):
    from ga import bills as ga_bills  # noqa: E402

from openstates.exceptions import EmptyScrape  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ga_open604")
SESSION_ID = 1033


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def _dt(value):
    return datetime.datetime.fromisoformat(value)


INDEX = load("index_2025_26.json")
SEARCH_ROWS = load("search_2025_26.json")
for row in SEARCH_ROWS:
    row["Status"]["Date"] = _dt(row["Status"]["Date"])
VOTES = load("votes_2025_26.json")
for listing in VOTES.values():
    for vote in listing:
        vote["Date"] = _dt(vote["Date"])

NAMES = {leg["Id"]: leg["Description"] for leg in INDEX}
ALL_BILLS = [leg["Description"] for leg in INDEX]


class FakeFactory:
    def create(self, name):
        if name == "ns2:LegislationSearchConstraints":
            return SimpleNamespace(
                Session=SimpleNamespace(Id=None),
                StatusConstraints=SimpleNamespace(StatusConstraint=[]),
            )
        return SimpleNamespace(kind=name, Status=None, DateStart=None, DateEnd=None)


class FakeLegislation:
    """GetLegislationForSession, the paged search and GetLegislationDetail."""

    def __init__(self, rows=SEARCH_ROWS, short_read=False, overlap=False):
        self.rows = rows
        self.short_read = short_read
        self.overlap = overlap
        self.searches = []
        self.details = []

    def GetLegislationForSession(self, session_id):
        assert session_id == SESSION_ID
        return {"LegislationIndex": INDEX}

    def GetLegislationSearchResultsPaged(self, constraints, page_size, start_index):
        assert page_size <= 250  # the service refuses more
        (status,) = constraints.StatusConstraints.StatusConstraint
        self.searches.append((constraints.Session.Id, status, page_size, start_index))
        assert status.kind == "ns2:CurrentStatusConstraint"
        first, last = status.DateStart.date(), status.DateEnd.date()
        matched = [r for r in self.rows if first <= r["Status"]["Date"].date() <= last]
        page = matched[start_index : start_index + page_size]
        if self.short_read and start_index:
            page = []
        if self.overlap and start_index:
            # the next page repeats the first row: as many rows as Total, fewer bills
            page = matched[:1] + page[1:]
        return {
            "Total": len(matched),
            "Page": {"LegislationSearchResult": page} if page else None,
        }

    def GetLegislationDetail(self, lid):
        self.details.append(NAMES[lid])
        # no caption: scrape() skips the bill right after reading it
        return {
            "StatusHistory": [[]],
            "Id": lid,
            "DocumentType": "HB",
            "Number": 1,
            "Suffix": None,
            "Caption": None,
            "Summary": None,
        }


class FakeVotes:
    def __init__(self, fail=False, empty=False):
        self.fail = fail
        self.empty = empty
        self.calls = []

    def GetVotes(self, branch, session_id):
        self.calls.append((branch, session_id))
        if self.fail:
            raise ValueError("The server's not playing nice.")
        if self.empty:
            return None
        return {"VoteListing": VOTES[branch]}


def make_scraper(legislation=None, votes=None):
    scraper = ga_bills.GABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.lclient = SimpleNamespace(factory=FakeFactory())
    scraper.lservice = legislation or FakeLegislation()
    scraper.vservice = votes or FakeVotes()
    scraper._subjects = {}
    scraper.scrape_subjects = mock.Mock()
    return scraper


def run(scraper, **kwargs):
    # backoff() waits a second before each call; the fakes need no courtesy
    with mock.patch.object(ga_bills, "backoff", lambda f, *a, **k: f(*a, **k)):
        return list(scraper.scrape(session="2025_26", **kwargs))


# --- which bills are read ---------------------------------------------------------


def test_without_start_every_bill_is_read():
    scraper = make_scraper()
    run(scraper)
    assert scraper.lservice.details == ALL_BILLS
    assert scraper.lservice.searches == []
    assert scraper.vservice.calls == []


def test_with_start_only_bills_whose_status_is_in_range_are_read():
    # 04:00 UTC on 05-19 is midnight Eastern: the cutoff is 05-12 (seven days of lookback).
    # HB 14 and HB 295 were signed on 05-12; HB 115 on 05-11 is out of range.
    scraper = make_scraper()
    run(scraper, start="2026-05-19T04:00:00")
    assert sorted(scraper.lservice.details) == ["HB 14", "HB 295"]
    scraper.scrape_subjects.assert_called_once_with(SESSION_ID)


def test_the_search_asks_for_the_current_status_from_the_cutoff_day_onward():
    scraper = make_scraper()
    run(scraper, start="2026-05-19T04:00:00")
    session_id, status, page_size, start_index = scraper.lservice.searches[0]
    assert session_id == SESSION_ID
    assert status.kind == "ns2:CurrentStatusConstraint"
    assert status.Status == "Any"
    assert status.DateStart == datetime.datetime(2026, 5, 12)
    # open-ended, so a later status cannot hide one in range
    assert status.DateEnd > datetime.datetime(2030, 1, 1)
    assert (page_size, start_index) == (250, 0)


def test_the_cutoff_is_the_eastern_day_not_the_utc_day():
    # 03:59 UTC on 05-19 is still 05-18 (23:59 EDT) in Georgia, so the cutoff is 05-11 and
    # HB 115 (signed 05-11) is read; a UTC-day cutoff (05-12) would drop it.
    scraper = make_scraper()
    run(scraper, start="2026-05-19T03:59:00")
    assert sorted(scraper.lservice.details) == ["HB 115", "HB 14", "HB 295"]


def test_a_new_roll_call_without_a_status_change_is_still_read():
    # SB 8's last status is 03-27 (House Passed/Adopted), but the Senate voted 26-26 on
    # agreeing to the House substitute on 04-02 (Senate Vote #964) and no status followed.
    # Measured on the whole session: 2 of 1,599 bill roll calls have no status on or after
    # their day (SB 8 #964 and HB 127 #443, a midnight reconsideration).
    scraper = make_scraper()
    run(scraper, start="2026-04-09T06:00:00")  # cutoff 04-02
    assert sorted(scraper.lservice.details) == [
        "HB 115",
        "HB 14",
        "HB 239",
        "HB 295",
        "HB 52",
        "SB 8",
    ]
    assert scraper.vservice.calls == [("House", SESSION_ID), ("Senate", SESSION_ID)]


def test_sb8_is_not_in_the_status_search_alone():
    scraper = make_scraper()
    with mock.patch.object(ga_bills, "backoff", lambda f, *a, **k: f(*a, **k)):
        ids = scraper.search_current_status(SESSION_ID, datetime.date(2026, 4, 2))
    assert "SB 8" not in {NAMES[i] for i in ids}


def test_votes_on_no_bill_are_ignored():
    cutoff = datetime.date(2025, 1, 1)
    votes = [v for v in VOTES["House"] + VOTES["Senate"] if not v["Legislation"]]
    assert votes  # vote #1 of each chamber
    assert ga_bills.bills_voted_since(cutoff, votes, INDEX) == set()


def test_search_pages_by_row_offset():
    scraper = make_scraper()
    with mock.patch.object(ga_bills, "SEARCH_PAGE_SIZE", 2):
        run(scraper, start="2026-04-09T06:00:00")
    # five bills have a current status on or after 04-02
    assert [s[3] for s in scraper.lservice.searches] == [0, 2, 4]
    assert "HB 239" in scraper.lservice.details


# --- records Georgia publishes after the date they carry ------------------------------


def test_a_roll_call_published_days_late_is_still_read():
    # House Vote #113 on HB 307 is dated 2025-02-28 10:11, but Georgia published it after
    # Senate Vote #134, dated 2025-03-03 20:37: at least 3 days 10 h late. A run whose
    # start is just before it appeared (as early as 03-03 20:37 EST, 03-04 01:37 UTC) must
    # still reach back to 02-28.
    votes = {v["Description"]: v for v in VOTES["House"] + VOTES["Senate"]}
    late, earlier = votes["House Vote #113"], votes["Senate Vote #134"]
    assert late["Legislation"] == "HB 307"
    assert late["VoteId"] > earlier["VoteId"] and late["Date"] < earlier["Date"]

    cutoff = ga_bills.changed_cutoff("2025-03-04T01:37:00")
    assert cutoff <= late["Date"].date()
    ids = ga_bills.bills_voted_since(cutoff, VOTES["House"] + VOTES["Senate"], INDEX)
    assert "HB 307" in {NAMES[i] for i in ids}


def test_a_status_entered_with_an_older_date_is_still_read():
    # SB 201's "Senate Date Signed by Governor" is dated 2025-05-08 11:28, but its status id
    # (333276) follows HB 782's signing, dated 2025-05-09 16:13 (333273): it was entered at
    # least 28 h 45 m after its date. (SB 201's signing is still its current status, so the
    # recorded row is what a run then would have seen.)
    rows = {f"{r['DocumentType']} {r['Number']}": r["Status"] for r in SEARCH_ROWS}
    late, earlier = rows["SB 201"], rows["HB 782"]
    assert late["StatusListingId"] > earlier["StatusListingId"]
    assert late["Date"] < earlier["Date"]
    assert late["Date"] + datetime.timedelta(hours=28, minutes=45) <= earlier["Date"]

    # Worst case for the next run: the run before listed its bills at 05-09 16:12 EDT, just
    # before the signing appeared, then ran its 12 h and wrote its watermark at about
    # 05-10 04:12 EDT; this run starts an hour before that, 05-10 03:12 EDT (07:12 UTC). Its
    # Eastern day is 05-10, so only a lookback of two days or more reaches 05-08: with one
    # day the cutoff is 05-09 and SB 201 is never read again.
    scraper = make_scraper()
    run(scraper, start="2025-05-10T07:12:00")
    assert ga_bills.changed_cutoff("2025-05-10T07:12:00") <= late["Date"].date()
    assert "SB 201" in scraper.lservice.details


# --- falling back to a full walk -----------------------------------------------------


def test_a_short_search_listing_means_a_full_walk():
    scraper = make_scraper(legislation=FakeLegislation(short_read=True))
    with mock.patch.object(ga_bills, "SEARCH_PAGE_SIZE", 2):
        run(scraper, start="2026-04-09T06:00:00")
    assert scraper.lservice.details == ALL_BILLS


def test_an_overlapping_search_listing_means_a_full_walk():
    scraper = make_scraper(legislation=FakeLegislation(overlap=True))
    with mock.patch.object(ga_bills, "SEARCH_PAGE_SIZE", 2):
        run(scraper, start="2026-04-09T06:00:00")
    assert scraper.lservice.details == ALL_BILLS


@pytest.mark.parametrize("votes", [{"fail": True}, {"empty": True}], ids=str)
def test_a_failed_or_empty_vote_listing_means_a_full_walk(votes):
    scraper = make_scraper(votes=FakeVotes(**votes))
    run(scraper, start="2026-05-19T04:00:00")
    assert scraper.lservice.details == ALL_BILLS


def test_invalid_start_means_a_full_walk():
    scraper = make_scraper()
    run(scraper, start="last tuesday")
    assert scraper.lservice.details == ALL_BILLS
    assert scraper.lservice.searches == []


def test_nothing_changed_is_an_empty_scrape_not_a_failure():
    scraper = make_scraper()
    with pytest.raises(EmptyScrape):
        run(scraper, start="2026-11-16T05:00:00")
    assert scraper.lservice.details == []
    scraper.scrape_subjects.assert_not_called()
