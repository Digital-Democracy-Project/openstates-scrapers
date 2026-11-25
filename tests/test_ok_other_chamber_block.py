"""OPEN-884: a roll call block that names the other chamber is not filed under the page's chamber.

The real House page of one 2025 bill (tests/fixtures/ok_open884, read 2026-11-24) carries, besides its
two House committee votes, a block headed "THE OKLAHOMA STATE SENATE" for another bill's Senate third
reading (RCS# 639, 21 ayes, 22 nays). The scraper filed it as a House roll call, so its 44 senators
found no House member. That Senate roll call is stored on its own bill's Senate page, so the block is
skipped here; every other block keeps its number and key.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from ok.bills import is_other_chambers_block  # noqa: E402
from test_ok_votes import OKBillScraper, _Resp  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "fixtures")


def scrape(path):
    text = open(path, "rb").read().decode("cp1252")
    scraper = OKBillScraper.__new__(OKBillScraper)
    warnings = []
    scraper.warning = lambda m, *a, **k: warnings.append(m)
    scraper.get = lambda url, verify=False: _Resp(text)
    chamber, bill_file = os.path.basename(path).split("_", 1)
    bill = Bill(
        bill_file.split("_")[0], legislative_session="2025", chamber="lower", title="t"
    )
    url = "https://www.oklegislature.gov/cf/votes/%s/%s" % (chamber, bill_file)
    return list(scraper.scrape_votes(bill, url)), warnings


def test_the_senate_block_on_a_house_page_is_not_a_house_roll_call():
    votes, warnings = scrape(os.path.join(HERE, "ok_open884", "House_SB920_VOTES.HTM"))
    assert sorted(v.dedupe_key.rsplit("#", 1)[1] for v in votes) == ["17", "66"]
    assert not any("639" in str(v.extras) for v in votes)
    assert any("RCS# 639" in w for w in warnings)


def test_no_block_of_the_other_pages_real_fixtures_is_skipped():
    # every House and Senate page already measured keeps all its roll calls
    paths = [
        p
        for p in glob.glob(os.path.join(HERE, "ok_open*", "*_VOTES.HTM"))
        if "ok_open884" not in p
    ]
    assert len(paths) >= 15
    for path in paths:
        _, warnings = scrape(path)
        assert not [w for w in warnings if "OPEN-884" in w], path


def test_the_rule_names_the_chamber_from_the_block_header():
    senate = "THE OKLAHOMA STATE SENATE 1st Session HOUSE BILL 2157 THIRD READING"
    senate_split = "THE OKLAHOMA / STATE SENATE 1st Regular Session Education"
    house = "OKLAHOMA HOUSE OF REPRESENTATIVES First Regular Session HB1003"
    committee = "Education Oversight Committee 2025-26 HB1491 Education; State Board"
    assert is_other_chambers_block(senate, "lower")
    assert is_other_chambers_block(senate_split.replace("/ ", ""), "lower")
    assert is_other_chambers_block(house, "upper")
    assert not is_other_chambers_block(senate, "upper")
    assert not is_other_chambers_block(house, "lower")
    assert not is_other_chambers_block(committee, "lower")  # no chamber named: stays
    assert not is_other_chambers_block("Joint Committee on Budget", "upper")
    both = "Oklahoma House of Representatives Joint Committee with the Oklahoma State Senate"
    assert not is_other_chambers_block(both, "lower")
    assert not is_other_chambers_block(both, "upper")
