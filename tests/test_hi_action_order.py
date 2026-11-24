"""OPEN-823: Hawaii's bill actions are stored oldest first (Wyoming's OPEN-780, Alabama's OPEN-528).

The measure status page (data.capitol.hawaii.gov session/measure_indiv.aspx) prints its status table newest first, and
6,395 of Hawaii's 6,728 bills of 2025-26 were stored in that order. The scraper reads the table backwards: a sort by
date would scramble same-day actions, and reversing keeps the page's own sequence within a day. The votes are still
yielded in the table's order, and each vote's dedupe_key (it holds the row's index in the table) is what it was before
(the "Reconsider: " prefix moved with OPEN-856, test_hi_reconsider_prefix).

Every page here is a real saved status page already used by other tests (read 2026-11-20): HB 1800, HB 1628 and SR 10
(hi_open691), SB 2387, SB 2135, SR 20, HB 1705 and HB 862 of 2021 (hi_open709), HR 50 (hi_open710), GM 1101 and
HB 1180 (hi_open805). The expected order is read from the page's own table, not from the scraper. hi_open823 holds
the dedupe_keys stored for HB 1800's roll calls on the Mac replica (openstates_rds_repl_20260911, read 2026-11-23),
written by the scraper before this change.
"""
import collections
import json
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

PAGES = [
    "hi_open691/HB1800.html",  # House bill, 2026, signed into law
    "hi_open691/HB1628.html",
    "hi_open709/SB2387.html",  # Senate bills
    "hi_open709/SB2135.html",
    "hi_open709/HB1705.html",
    "hi_open709/HB862-2021.html",
    "hi_open709/SR20.html",  # resolutions
    "hi_open710/HR50.html",
    "hi_open691/SR10.html",
    "hi_open805/GM1101-2026.html",  # a governor's message
    "hi_open805/HB1180-2026.html",
]


def page_rows(name):
    """The status table's rows as the page prints them: (date, chamber code, text)."""
    page = lxml.html.fromstring(open(os.path.join(FIXTURES, name), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    rows = []
    for tr in table.cssselect("tr")[1:]:
        date, actor, text = [td.text_content() for td in tr.cssselect("td")[:3]]
        month, day, year = date.split("/")
        rows.append((f"{year}-{int(month):02}-{int(day):02}", actor.upper(), text))
    return table, rows


def scraped(name, short_ids=None):
    """parse_bill_actions_table() over one saved page: the stored actions and the votes it yields."""
    table, _ = page_rows(name)
    bill_id = os.path.basename(name)[:-5].split("-")[0]
    chamber = "upper" if bill_id.startswith(("S", "G")) else "lower"
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = short_ids or {}
    scraper.members = None
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber=chamber)
    votes = list(
        scraper.parse_bill_actions_table(
            bill, table, bill_id, "2026 Regular Session", "https://example/", chamber
        )
    )
    return bill.actions, votes


CHAMBER_OF = {
    '~{"classification": "lower"}': "H",
    '~{"classification": "upper"}': "S",
    '~{"classification": "legislature"}': "D",
}


def described(actions):
    """Each stored action as (date, chamber code, text), the form page_rows() reads."""
    return [
        (a["date"], CHAMBER_OF[a["organization_id"]], a["description"]) for a in actions
    ]


@pytest.mark.parametrize("name", PAGES)
def test_actions_are_the_page_read_backwards(name):
    _, rows = page_rows(name)
    actions, _ = scraped(name)
    assert described(actions) == rows[::-1]


@pytest.mark.parametrize("name", PAGES)
def test_only_the_order_changes(name):
    # the same texts, dates and chambers as the page, each once, and each keeps the labels of its own text
    _, rows = page_rows(name)
    actions, _ = scraped(name)
    assert collections.Counter(described(actions)) == collections.Counter(rows)
    categorizer = HIBillScraper.categorizer
    for a in actions:
        expected = categorizer.categorize(a["description"])["classification"]
        assert sorted(a["classification"]) == sorted(expected or [])


def test_hb1800_runs_from_introduction_to_act():
    actions, _ = scraped("hi_open691/HB1800.html")
    assert actions[0]["description"] == "Pending introduction."
    assert actions[0]["date"] == "2026-01-22"
    assert actions[-1]["description"].startswith("Act 175, on 06/26/2026")
    assert actions[-1]["date"] == "2026-06-26"


def test_referrals_keep_their_committees():
    # each referral carries the committees its own text names (codes as the scraper's committee list maps them)
    short_ids = {"FIN": {"name": "Finance"}, "WAM": {"name": "Ways and Means"}}
    actions, _ = scraped("hi_open691/HB1800.html", short_ids)
    related = [
        (a["description"], [e["name"] for e in a["related_entities"]])
        for a in actions
        if a["related_entities"]
    ]
    assert related == [
        ("Referred to FIN, referral sheet 1", ["Finance"]),
        ("Referred to WAM.", ["Ways and Means"]),
    ]


def test_same_day_actions_happen_in_order():
    # GM 1101: the Senate received the message, then filed it, both 03/23/2026 (the page prints "Filed." first)
    actions, _ = scraped("hi_open805/GM1101-2026.html")
    assert [a["description"] for a in actions] == ["Received.", "Filed."]
    # HB 1800 in the Senate on 03/19/2026: received from the House, passed First Reading, referred to WAM
    texts = [
        a["description"]
        for a in scraped("hi_open691/HB1800.html")[0]
        if a["date"] == "2026-03-19"
    ]
    assert texts == [
        "Received from House (Hse. Com. No. 446).",
        "Passed First Reading.",
        "Referred to WAM.",
    ]


@pytest.mark.parametrize("name", PAGES)
def test_dates_run_forwards(name):
    # the page itself prints a few rows a day out of date order (a notice received the day after the bill went
    # to the Governor), so at most one step back, where before there were up to 30
    actions, _ = scraped(name)
    dates = [a["date"] for a in actions]
    assert sum(1 for x, y in zip(dates, dates[1:]) if y < x) <= 1


@pytest.mark.parametrize("name", PAGES)
def test_vote_keys_keep_the_page_row_index(name):
    # dedupe_key = "<row index in the page's table>#<bill>#<date>#<text>", as stored before OPEN-823
    _, rows = page_rows(name)
    _, votes = scraped(name)
    for vote in votes:
        index, _, date, text = vote.dedupe_key.split("#", 3)
        assert rows[int(index)][0] == date
        assert rows[int(index)][2][:300] == text


def test_hb1800_vote_keys_are_the_stored_ones():
    # the roll calls read without people data are exactly the ones stored before, key for key (the House floor
    # tallies need people data, OPEN-709, and are covered by test_hi_seated_ayes)
    with open(
        os.path.join(FIXTURES, "hi_open823", "HB1800-2026-stored-vote-keys.json"),
        encoding="utf-8",
    ) as f:
        stored = json.load(f)
    _, votes = scraped("hi_open691/HB1800.html")
    # the scraper's save strips each string field's outer whitespace (openstates.scrape.base.clean_whitespace)
    assert sorted(v.dedupe_key.strip() for v in votes) == sorted(stored)
