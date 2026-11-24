"""OPEN-872: Oklahoma votes carry the page's roll-call number (RCS#) in extras.

oklegislature.gov gives a roll call its day only. The RCS# rises in the order a chamber took its votes,
so the broker (Motion.rollcall_num, OPEN-628 / OPEN-685 / OPEN-863) uses it to order two same-day votes in
one chamber. The fixtures are the real _VOTES.HTM pages of tests/fixtures/ok_open687 (read 2026-11-20):
HB 1003's House voted Third Reading twice on 2025-03-26 (RCS 432, then 446 on the stored votes).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from openstates.scrape import Bill  # noqa: E402

from test_ok_votes import FIXTURES, OKBillScraper, _Resp  # noqa: E402


def scrape(fname):
    text = open(os.path.join(FIXTURES, fname), "rb").read().decode("cp1252")
    scraper = OKBillScraper.__new__(OKBillScraper)
    scraper.warning = lambda *a, **k: None
    scraper.get = lambda url, verify=False: _Resp(text)
    chamber, bill_file = fname.split("_", 1)
    bill = Bill(
        bill_file.split("_")[0], legislative_session="2025", chamber="lower", title="t"
    )
    url = "https://www.oklegislature.gov/cf/votes/%s/%s" % (chamber, bill_file)
    return list(scraper.scrape_votes(bill, url))


def test_house_same_day_third_readings_come_out_in_voting_order():
    votes = [
        v
        for v in scrape("House_HB1003_VOTES.HTM")
        if v.start_date == "2025-03-26" and v.motion_text == "Third Reading"
    ]
    assert len(votes) == 2
    numbers = sorted(int(v.extras["house-rollcall-num"]) for v in votes)
    assert numbers[0] < numbers[1]
    # the key follows the dedupe key's own roll call, which the page prints per vote
    for v in votes:
        assert v.dedupe_key.endswith("#" + v.extras["house-rollcall-num"])


def test_every_vote_on_a_page_has_one_number_under_its_chambers_key():
    for fname, key, other in (
        ("House_SB2_VOTES.HTM", "house-rollcall-num", "senate-rollcall-num"),
        ("Senate_SB6_VOTES.HTM", "senate-rollcall-num", "house-rollcall-num"),
    ):
        votes = scrape(fname)
        assert votes
        for v in votes:
            assert set(v.extras) == {key}, (fname, v.extras)
            assert other not in v.extras
            assert v.extras[key].isdigit()


def test_known_numbers_on_real_pages():
    # House SB 2's Energy Committee vote is RCS 23
    by_motion = {
        v.motion_text: v.extras["house-rollcall-num"]
        for v in scrape("House_SB2_VOTES.HTM")
    }
    assert by_motion["Energy Committee: Do Pass"] == "23"
