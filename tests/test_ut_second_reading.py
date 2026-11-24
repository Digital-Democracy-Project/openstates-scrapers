"""OPEN-875: Utah's 2nd-reading roll call is passage unless a later passage roll call of its chamber follows.

The fixtures are le.utah.gov's own action lists (HB 14 saved 2026-11-24; HB 209, HB 136 and SB 98 are the OPEN-622
ones, 2026GS) cut to the action fields, and the real Senate roll-call page of HB 14's 2nd reading (voteID 205). Every
roll call is read from that one page, so a vote's motion, chamber and date come from the action list, not the page.
"""
import datetime
import json
import os
import sys

import pytest
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from openstates.scrape import VoteEvent  # noqa: E402
from ut import Utah  # noqa: E402
from ut.bills import UTBillScraper, drain, settle_second_readings  # noqa: E402

HERE = os.path.dirname(__file__)
VOTE_PAGE = os.path.join(HERE, "fixtures", "ut_open875", "svote_HB0014_205S.html")


class _Response:
    def __init__(self, content):
        self.content = content
        self.text = content.decode("utf-8") if isinstance(content, bytes) else content


def scraped_votes(fixture_dir, filename):
    """(motion, chamber, classification) of every roll call the scraper stores for the bill, oldest first."""
    scraper = UTBillScraper(Utah(), "/tmp/")
    scraper._start = None
    with open(os.path.join(HERE, "fixtures", fixture_dir, filename), "rb") as f:
        api = f.read()
    with open(VOTE_PAGE, "rb") as f:
        vote_page = f.read()
    scraper.get = lambda url, verify=None: _Response(
        vote_page if "svotes.jsp" in url else api
    )
    bill = Bill("HB 1", legislative_session="2026", chamber="lower", title="t")
    items, _ = drain(
        scraper.scrape_bill_details_from_api(
            bill, "https://le.utah.gov/~2026/bills/static/X.html", "2026GS"
        )
    )
    votes = [item for item in items if isinstance(item, VoteEvent)]
    settle_second_readings(votes)
    votes.sort(key=lambda v: str(v.start_date))
    return [
        (
            v.motion_text,
            json.loads(v.organization[1:])["classification"],
            v.motion_classification,
        )
        for v in votes
    ]


def test_a_second_reading_with_nothing_after_it_counts():
    # HB 14: the Senate passed it on 2nd reading (22-0); its 3rd reading was tabled, so no later Senate roll call.
    votes = scraped_votes("ut_open875", "HB0014-2026GS.json")
    assert ("Senate/ passed 2nd reading", "upper", ["passage"]) in votes


def test_a_second_reading_followed_by_a_third_reading_is_replaced():
    # SB 98: Senate 2nd reading (02-13) then Senate 3rd reading (02-17); the House's 3rd reading is its own chamber's.
    votes = scraped_votes("ut_open622", "SB0098-2026GS.json")
    assert ("Senate/ passed 2nd reading", "upper", []) in votes
    assert ("Senate/ passed 3rd reading", "upper", ["passage"]) in votes
    assert ("House/ passed 3rd reading", "lower", ["passage"]) in votes


def test_a_second_reading_followed_by_a_combined_2nd_and_3rd_is_replaced_and_others_keep_their_typing():
    # HB 209: Senate 2nd reading (02-12), Senate "2nd & 3rd readings/ suspension" (03-04), House concurrence (03-05)
    votes = scraped_votes("ut_open622", "HB0209-2026GS.json")
    assert ("Senate/ passed 2nd reading", "upper", []) in votes
    assert (
        "Senate/ passed 2nd & 3rd readings/ suspension",
        "upper",
        ["passage"],
    ) in votes
    assert ("House/ concurs with Senate amendment", "lower", ["passage"]) in votes
    assert ("House/ passed 3rd reading", "lower", ["passage"]) in votes


def _vote(motion, chamber, date):
    return VoteEvent(
        motion_text=motion,
        start_date=date,
        classification=[] if "amendment" in motion and "concurs" not in motion else ["passage"],
        result="pass",
        legislative_session="2026",
        chamber=chamber,
    )


@pytest.mark.parametrize(
    "later_motion,later_chamber,later_date,second_reading_stays",
    [
        ("Senate/ passed 3rd reading", "upper", "2026-02-17", False),
        ("Senate/ concurs with House amendment", "upper", "2026-03-01", False),
        ("Senate/ failed", "upper", "2026-02-17", False),
        # the other chamber's vote never replaces it
        ("House/ passed 3rd reading", "lower", "2026-02-17", True),
        # an earlier passage vote does not replace it, and a later vote that is not passage does not either
        ("Senate/ passed 3rd reading", "upper", "2026-02-01", True),
        ("Senate/ floor amendment", "upper", "2026-02-17", True),
    ],
)
def test_what_replaces_a_second_reading(
    later_motion, later_chamber, later_date, second_reading_stays
):
    # dates are the older HTML path's "YYYY-MM-DD"
    second = _vote("Senate/ passed 2nd reading", "upper", "2026-02-13")
    later = _vote(later_motion, later_chamber, later_date)
    second.motion_classification = ["passage"]
    settle_second_readings([later, second])
    assert (second.motion_classification == ["passage"]) is second_reading_stays
    assert later.motion_classification == ([] if "floor amendment" in later_motion else ["passage"])


def test_a_house_second_reading_follows_the_same_rule():
    second = _vote("House/ passed 2nd reading", "lower", "2026-02-13")
    settle_second_readings([second])
    assert second.motion_classification == ["passage"]


def test_scrape_bill_yields_the_settled_votes_before_the_bill():
    # the wiring: scrape_bill holds the votes back, settles them, then yields them and the bill
    scraper = UTBillScraper(Utah(), "/tmp/")
    scraper._start = None
    page = (
        '<html><body><ul id="breadcrumb"><li>Home</li><li>S.B. 98</li></ul>'
        '<h3 class="heading">S.B. 98 Test Bill</h3></body></html>'
    )
    with open(os.path.join(HERE, "fixtures", "ut_open622", "SB0098-2026GS.json"), "rb") as f:
        api = f.read()
    with open(VOTE_PAGE, "rb") as f:
        vote_page = f.read()

    def get(url, verify=None):
        if "svotes.jsp" in url:
            return _Response(vote_page)
        return _Response(api if "/data/" in url else page)

    scraper.get = get
    out = list(
        scraper.scrape_bill(
            "upper", "2026", "https://le.utah.gov/~2026/bills/static/SB0098.html", "2026GS"
        )
    )
    assert isinstance(out[-1], Bill)
    by_motion = {v.motion_text: v.motion_classification for v in out if isinstance(v, VoteEvent)}
    assert by_motion["Senate/ passed 2nd reading"] == []
    assert by_motion["Senate/ passed 3rd reading"] == ["passage"]


def test_votes_of_one_day_are_ordered_by_time_and_a_date_only_vote_can_mix_in():
    # le.utah.gov gives most actions a time of day (a Utah-time datetime here) and some only a date (a string)
    tz = pytz.timezone("America/Denver")
    second = _vote("Senate/ passed 2nd reading", "upper", tz.localize(datetime.datetime(2026, 3, 4, 10, 31)))
    third = _vote("Senate/ passed 3rd reading", "upper", tz.localize(datetime.datetime(2026, 3, 4, 14, 5)))
    settle_second_readings([third, second])
    assert second.motion_classification == []
    # the other way round (3rd reading first in the morning): the 2nd reading is the later vote and stays
    early = _vote("Senate/ passed 3rd reading", "upper", tz.localize(datetime.datetime(2026, 3, 4, 8, 0)))
    second = _vote("Senate/ passed 2nd reading", "upper", tz.localize(datetime.datetime(2026, 3, 4, 10, 31)))
    settle_second_readings([early, second])
    assert second.motion_classification == ["passage"]
    # a date-only vote of a later day against a timed 2nd reading does not raise
    second = _vote("Senate/ passed 2nd reading", "upper", tz.localize(datetime.datetime(2026, 3, 4, 10, 31)))
    settle_second_readings([second, _vote("Senate/ passed 3rd reading", "upper", "2026-03-05")])
    assert second.motion_classification == []
