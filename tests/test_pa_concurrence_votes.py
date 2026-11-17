"""OPEN-617: a Pennsylvania chamber's vote to concur in the other chamber's amendments is passage.

Before this ticket the House's bare "CONCURRENCE" was stored unlabelled and the Senate's
"CONCUR IN ... AMENDMENTS" was labelled "amendment" by the pa scraper's own branch, so a bill
whose last vote in a chamber was a concurrence had no passage vote there.

Fixtures (pa_open617/), all real and unchanged, as palegis.us served them on 2026-11-17:
- House roll call 526 (2025): HB 103, 2025-06-30, 201-2, "CONCURRENCE". History: "House
  concurred in Senate amendments" that day.
- Senate roll call 603 (2025): SB 1014, 2026-10-21, 47-3, "CONCUR IN HOUSE AMENDMENTS". History:
  "Senate concurred in House amendments" that day.
- Senate roll call 268 (2025): SB 315, 2025-11-12, 44-5, "CONCURRENCE IN HOUSE AMENDMENTS AS
  AMENDED". History: "Senate concurred in House amendments, as amended by the Senate" that day.
Committee and amendment votes keeping their labels are covered on recorded pages by
test_pa_resolution_votes.py (OPEN-582 fixtures), re-run here against the same scraper.
No request leaves the test.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from pa.bills import PABillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BASE = "https://www.palegis.us"


def scraped_vote(fixture, url, identifier, chamber, committee=False):
    with open(os.path.join(FIXTURES, fixture), encoding="utf-8") as f:
        page = lxml.html.fromstring(f.read())
    page.make_links_absolute(BASE + url)
    scraper = PABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.get_page = lambda u: page
    bill = Bill(identifier, "2025-2026", "x", chamber=chamber, classification="bill")
    parse = scraper.parse_committee_votes if committee else scraper.parse_chamber_votes
    (vote,) = list(parse(bill, BASE + url))
    return vote


@pytest.mark.parametrize(
    "fixture,url,identifier,chamber,motion,counts",
    [
        (
            "pa_open617/house_rc526_hb103.html",
            "/house/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=526",
            "HB 103",
            "lower",
            "CONCURRENCE",
            (201, 2),
        ),
        (
            "pa_open617/senate_rc603_sb1014.html",
            "/senate/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=603",
            "SB 1014",
            "upper",
            "CONCUR IN HOUSE AMENDMENTS",
            (47, 3),
        ),
        (
            "pa_open617/senate_rc268_sb315.html",
            "/senate/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=268",
            "SB 315",
            "upper",
            "CONCURRENCE IN HOUSE AMENDMENTS AS AMENDED",
            (44, 5),
        ),
    ],
)
def test_concurrence_is_passage(fixture, url, identifier, chamber, motion, counts):
    vote = scraped_vote(fixture, url, identifier, chamber)
    assert vote.motion_text == motion
    assert vote.motion_classification == ["passage"]
    assert vote.result == "pass"
    assert {c["option"]: c["value"] for c in vote.counts}["yes"] == counts[0]
    assert {c["option"]: c["value"] for c in vote.counts}["no"] == counts[1]


def test_committee_report_keeps_committee_passage():
    vote = scraped_vote(
        "pa_open582/house_committee_1615_hr401.html",
        "/house/committees/roll-call-votes/vote-list/vote-summary"
        "?committeecode=65&rollcallid=1615&sessYr=2025&sessInd=0",
        "HR 401",
        "lower",
        committee=True,
    )
    assert vote.motion_classification == ["committee-passage"]


def test_committee_amendment_vote_stays_unlabelled():
    vote = scraped_vote(
        "pa_open582/house_committee_3136_sb1431.html",
        "/house/committees/roll-call-votes/vote-list/vote-summary"
        "?committeecode=62&rollcallid=3136&sessYr=2025&sessInd=0",
        "SB 1431",
        "lower",
        committee=True,
    )
    assert vote.motion_text == "Committee vote (Appropriations): Adopt Amendment A04721"
    assert vote.motion_classification == []


def test_final_passage_unchanged():
    vote = scraped_vote(
        "pa_open582/house_rc794_hb1663.html",
        "/house/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=794",
        "HB 1663",
        "lower",
    )
    assert vote.motion_text == "FINAL PASSAGE"
    assert vote.motion_classification == ["passage"]
