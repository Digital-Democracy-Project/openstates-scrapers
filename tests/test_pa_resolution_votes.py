"""OPEN-582: a Pennsylvania resolution's floor adoption vote is passage.

palegis.us leaves the Action of that roll call blank, and the pa scraper stores the measure's
name as its motion text ("House Resolution 401"). Before this ticket the scraper classified the
blank text before filling the name in, so every such vote was stored unlabelled.

Fixtures (pa_open582/), all real and unchanged, as palegis.us served them on 2026-11-17:
- House roll call 835 (2025): HR 401, 2026-02-04, 194-4. The bill history says "Adopted,
  Feb. 4, 2026 (194-4)".
- Senate roll call 69 (2025): SR 94, 2025-05-12, 50-0. The bill history says "Adopted,
  May 12, 2025 (50-0)".
- House committee roll call 1615: HR 401 in Tourism, Recreation & Economic Development.
- House roll calls 765 and 794 (2025): HB 1663. 765 has a blank Action too (2025-12-16, 102-101,
  the day of "Second consideration, with amendments"); 794 is "FINAL PASSAGE" (2025-12-17).
No request leaves the test.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from pa.bills import PABillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pa_open582")
BASE = "https://www.palegis.us"


def scraped_vote(fixture, url, identifier, chamber, committee=False):
    with open(os.path.join(FIXTURES, fixture), encoding="utf-8") as f:
        page = lxml.html.fromstring(f.read())
    page.make_links_absolute(BASE + url)
    scraper = PABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.get_page = lambda u: page
    classification = "resolution" if identifier[1] == "R" else "bill"
    bill = Bill(
        identifier, "2025-2026", "x", chamber=chamber, classification=classification
    )
    parse = scraper.parse_committee_votes if committee else scraper.parse_chamber_votes
    (vote,) = list(parse(bill, BASE + url))
    return vote


@pytest.mark.parametrize(
    "fixture,url,identifier,chamber,motion,counts",
    [
        (
            "house_rc835_hr401.html",
            "/house/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=835",
            "HR 401",
            "lower",
            "House Resolution 401",
            (194, 4),
        ),
        (
            "senate_rc69_sr94.html",
            "/senate/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=69",
            "SR 94",
            "upper",
            "Senate Resolution 94",
            (50, 0),
        ),
    ],
)
def test_resolution_floor_adoption_is_passage(
    fixture, url, identifier, chamber, motion, counts
):
    vote = scraped_vote(fixture, url, identifier, chamber)
    assert vote.motion_text == motion
    assert vote.motion_classification == ["passage"]
    assert vote.result == "pass"
    assert {c["option"]: c["value"] for c in vote.counts}["yes"] == counts[0]
    assert {c["option"]: c["value"] for c in vote.counts}["no"] == counts[1]


def test_resolution_committee_vote_stays_committee_passage():
    vote = scraped_vote(
        "house_committee_1615_hr401.html",
        "/house/committees/roll-call-votes/vote-list/vote-summary"
        "?committeecode=65&rollcallid=1615&sessYr=2025&sessInd=0",
        "HR 401",
        "lower",
        committee=True,
    )
    assert vote.motion_text.startswith("Committee vote (")
    assert vote.motion_classification == ["committee-passage"]


def test_blank_action_on_a_bill_stays_unlabelled():
    # HB 1663's blank-Action roll call of 2025-12-16 is not its final passage (that is RC 794,
    # the next day), so only a resolution's name counts as an adoption vote
    vote = scraped_vote(
        "house_rc765_hb1663.html",
        "/house/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=765",
        "HB 1663",
        "lower",
    )
    assert vote.motion_text == "House Bill 1663"
    assert vote.motion_classification == []


def test_bill_final_passage_unchanged():
    vote = scraped_vote(
        "house_rc794_hb1663.html",
        "/house/roll-calls/summary?sessYr=2025&sessInd=0&rcNum=794",
        "HB 1663",
        "lower",
    )
    assert vote.motion_text == "FINAL PASSAGE"
    assert vote.motion_classification == ["passage"]
