"""OPEN-863: Alabama votes carry ALISON's roll-call number in extras.

ALISON gives a vote its day only. The roll-call number rises in the order a chamber took its votes,
so the broker (Motion.rollcall_num, OPEN-628 / OPEN-685) uses it to order two same-day votes in one
chamber. HB 460's House, 2026-02-24: Roll Call 520 lost, then 521 adopted. The billModal of HB 460
and its two roll calls are ALISON's own replies, saved on 2026-11-24. No test makes a live call.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from test_al_votes import (
    by_roll_call,
    chamber,
    load,
    make_bill,
    make_scraper,
)  # noqa: E402


def hb460_votes():
    scraper = make_scraper()
    rows = json.loads(load("modal_HB460.json"))["data"]["histories"]["data"][::-1]
    # only the two re-vote roll calls are saved
    rows = [r for r in rows if r["rollCallNbr"] in (520, 521)]
    assert len(rows) == 2
    return by_roll_call(scraper.scrape_votes(make_bill("HB460"), rows))


def test_hb460_re_vote_carries_both_roll_call_numbers():
    votes = hb460_votes()
    assert votes["520"].extras == {"house-rollcall-num": "520"}
    assert votes["521"].extras == {"house-rollcall-num": "521"}
    # same chamber, same day, the later number is the re-vote
    assert votes["520"].start_date == votes["521"].start_date
    assert votes["520"].result == "fail" and votes["521"].result == "pass"


def test_a_senate_vote_uses_the_senate_key():
    hb2 = json.loads(load("modal_HB2.json"))["data"]["histories"]["data"][::-1]
    votes = by_roll_call(make_scraper().scrape_votes(make_bill("HB2"), hb2))
    assert chamber(votes["1009"]) == "upper"
    assert votes["1009"].extras == {"senate-rollcall-num": "1009"}
    assert chamber(votes["536"]) == "lower"
    assert votes["536"].extras == {"house-rollcall-num": "536"}
