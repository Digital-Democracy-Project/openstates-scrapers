"""OPEN-590: Georgia vote labels, and House "Local Calendar" reconsiderations.

Fixtures are Georgia's own GetLegislationDetail answers (webservices.legis.ga.gov,
read 2026-11-16), saved as JSON: HB 1, HB 68 and HB 80 of the 2026 special session
(local bills voted as a calendar, lost, reconsidered, lost again) and SB 234 of 2025
(a local bill reconsidered under its own caption, then passed).

HB 1 is the probe sample's bill (10-31): its three House roll calls are all captioned
"Local Calendar" (#5 and #10 with a trailing space). #5 lost on 06-20 ("House Third
Reading Lost"), #9 on 06-22 is the vote to reconsider ("House Reconsidered"), #10 lost
again ("House Lost Reconsidered Bill/Resolution"). The probe stored #9 as a passed
passage vote.
"""
import datetime
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

# the scraper builds its SOAP clients (a WSDL fetch) when the module loads
with mock.patch("suds.client.Client"):
    from ga import bills as ga_bills  # noqa: E402
    from ga import Georgia  # noqa: E402

from openstates.scrape import Bill, VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ga_votes")


def _dt(value):
    return datetime.datetime.fromisoformat(value)


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        detail = json.load(f)
    for status in detail["StatusHistory"]["StatusListing"]:
        status["Date"] = _dt(status["Date"])
    for vote in detail["Votes"]["VoteListing"]:
        vote["Date"] = _dt(vote["Date"])
    return detail


def history(detail):
    return detail["StatusHistory"]["StatusListing"]


def votes_by_number(detail):
    return {v["Number"]: v for v in detail["Votes"]["VoteListing"]}


def labels(detail):
    """{roll call number: (classification, failed by the status history)}"""
    votes = detail["Votes"]["VoteListing"]
    lost, reconsidered = ga_bills.pair_outcomes(votes, history(detail))
    return {
        v["Number"]: (
            ga_bills.vote_classification(
                v["Caption"].strip(), v["VoteId"] in reconsidered
            ),
            v["VoteId"] in lost,
        )
        for v in votes
    }


def test_hb1_reconsideration_is_not_passage():
    assert labels(load("detail_2026_ss_HB1.json")) == {
        5: (["passage"], True),  # Third Reading Lost
        9: ([], False),  # House Reconsidered: the vote to reconsider
        10: (["passage"], True),  # House Lost Reconsidered Bill/Resolution
    }


def test_hb1_captions_are_the_same_calendar_caption():
    # the caption cannot tell #9 from #5 and #10, so the YAML alone labels all three passage
    captions = {
        n: v["Caption"]
        for n, v in votes_by_number(load("detail_2026_ss_HB1.json")).items()
    }
    assert captions == {
        5: "Local Calendar ",
        9: "Local Calendar",
        10: "Local Calendar ",
    }
    for caption in captions.values():
        assert ga_bills.vote_classification(caption) == ["passage"]


def test_hb68_previous_local_calendar_is_the_reconsideration():
    # 06-22 #8 lost; 06-23 #16 "Previous Local Calendar" reconsidered, #17 lost again
    assert labels(load("detail_2026_ss_HB68.json")) == {
        8: (["passage"], True),
        16: ([], False),
        17: (["passage"], True),
    }


def test_hb80_three_calendar_votes_one_morning():
    # 06-23 08:37 / 08:40 / 08:43, outcomes logged 09:57 / 10:08 / 11:38
    assert labels(load("detail_2026_ss_HB80.json")) == {
        13: (["passage"], True),
        14: ([], False),
        15: (["passage"], True),
    }


def test_sb234_reconsidered_status_does_not_take_the_revote():
    # 2025-04-04: #434 "Local Calendar " lost; #435 "Recon SB 234, 235, & 336" (own caption);
    # #436 "SBs 234, 235, & 336 Passage" 147-2, then "House Reconsidered" 19:18 and
    # "House Passed/Adopted" 19:22. The re-vote is passage and passed.
    detail = load("detail_2025_26_SB234.json")
    got = labels(detail)
    assert got[434] == (["passage"], True)
    assert got[435] == ([], False)
    assert got[436] == (["passage"], False)
    assert got[114] == (["passage"], False)  # Senate "LOCAL CONSENT CALENDAR", 52-0


def test_reconsidered_status_only_pairs_a_calendar_vote():
    # a re-vote under its own caption: "House Reconsidered" leaves it for the status after it,
    # and "House Lost Reconsidered Bill/Resolution" is a lost outcome, not a reconsideration
    day = datetime.datetime(2026, 3, 6)
    votes = [
        {
            "VoteId": 1,
            "Number": 655,
            "Branch": "House",
            "Caption": "PASSAGE",
            "Date": day.replace(hour=12),
        },
        {
            "VoteId": 2,
            "Number": 657,
            "Branch": "House",
            "Caption": "PASSAGE",
            "Date": day.replace(hour=13),
        },
    ]
    statuses = [
        {
            "Code": "HTRL",
            "Description": "House Third Reading Lost",
            "Date": day.replace(hour=12, minute=5),
        },
        {
            "Code": "HRECO",
            "Description": "House Reconsidered",
            "Date": day.replace(hour=14),
        },
        {
            "Code": "HRECL",
            "Description": "House Lost Reconsidered Bill/Resolution",
            "Date": day.replace(hour=14, minute=5),
        },
    ]
    lost, reconsidered = ga_bills.pair_outcomes(votes, statuses)
    assert lost == {1, 2}
    assert reconsidered == set()


def test_pairing_is_per_chamber():
    day = datetime.datetime(2026, 6, 22)
    votes = [
        {
            "VoteId": 1,
            "Branch": "Senate",
            "Caption": "LOCAL CONSENT CALENDAR",
            "Date": day.replace(hour=14),
        },
    ]
    statuses = [
        {
            "Code": "HRECO",
            "Description": "House Reconsidered",
            "Date": day.replace(hour=16),
        },
    ]
    assert ga_bills.pair_outcomes(votes, statuses) == (set(), set())


# ---------------------------------------------------------------------------
# the scraper itself, on HB 1 (services mocked, no network)
# ---------------------------------------------------------------------------


def _suds_like(detail):
    """The scraper indexes a few suds objects by position."""
    inst = dict(detail)
    inst["StatusHistory"] = [history(detail)]
    inst["Committees"] = [detail["Committees"]["CommitteeListing"]]
    return inst


def test_scrape_labels_hb1_votes():
    detail = load("detail_2026_ss_HB1.json")
    scraper = ga_bills.GABillScraper(Georgia(), "/tmp/")
    scraper._subjects = {}
    lservice = mock.Mock()
    lservice.GetLegislationForSession.return_value = {
        "LegislationIndex": [{"Id": 74753}]
    }
    lservice.GetLegislationDetail.return_value = _suds_like(detail)
    vservice = mock.Mock()
    by_id = {v["VoteId"]: dict(v, Votes=None) for v in detail["Votes"]["VoteListing"]}
    vservice.GetVote.side_effect = lambda vid: by_id[vid]
    mservice = mock.Mock()
    mservice.GetMember.return_value = {"Name": {"First": "Matt", "Last": "Hatchett"}}

    with mock.patch.object(
        ga_bills.GABillScraper, "lservice", lservice
    ), mock.patch.object(
        ga_bills.GABillScraper, "vservice", vservice
    ), mock.patch.object(
        ga_bills.GABillScraper, "mservice", mservice
    ), mock.patch.object(
        ga_bills.GABillScraper, "scrape_subjects"
    ), mock.patch.object(
        ga_bills, "backoff", lambda f, *a, **k: f(*a, **k)
    ), mock.patch.object(
        scraper, "warning"
    ):
        out = list(scraper.scrape(session="2026_ss"))

    assert [o.identifier for o in out if isinstance(o, Bill)] == ["HB 1"]
    got = {
        o.identifier: (o.motion_text, o.motion_classification, o.result)
        for o in out
        if isinstance(o, VoteEvent)
    }
    assert got == {
        "House Vote #5": ("Local Calendar", ["passage"], "fail"),
        "House Vote #9": ("Local Calendar", [], "pass"),
        "House Vote #10": ("Local Calendar", ["passage"], "fail"),
    }
