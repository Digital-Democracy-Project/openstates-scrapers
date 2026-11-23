"""Tests for OPEN-789: Rep. Denise Crosswhite Hader is one voter on an Oklahoma House roll call.

House vote pages print her as "Crosswhite Hader" in a column of names. The tokenizer split it in
two: "Crosswhite" (matched to her) and "Hader" (matched no one, 1,928 House votes of 2025-2026),
and the extra name used up the section's declared count, so the section's last real voter was
dropped (2026 HB 2973 RCS 1194: Hasenbeck's yea). The fixtures are the real House pages already
used by OPEN-687, OPEN-704 and OPEN-758.

OPEN-802: no member's name is written into the parser. Names are split on the column gaps (two or
more spaces), so any surname of several words stays one voter; the synthetic surnames below are
on no page and in no code. The expected voters are read independently of the scraper: from the
page's HTML structure, where each printed name is its own text run between the padding spans.
"""
import os
import re
import sys
import unicodedata

import pytest
from lxml import html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from ok.bills import OKBillScraper, extract_names  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
HOUSE_PAGES = [
    "ok_open687/House_HB1003_VOTES.HTM",
    "ok_open687/House_HB2785_VOTES.HTM",
    "ok_open687/House_SB2_VOTES.HTM",
    "ok_open687/House_SCR1_VOTES.HTM",
    "ok_open704/House_HB3005_VOTES.HTM",
    "ok_open758/votes_HB1002_House.htm",
    "ok_open758/votes_HB2929_House.htm",
]
SECTION = re.compile(
    r"(YEAS|NAYS|EXCUSED|CONSTITUTIONAL PRIVILEGE|VACANT|VACANCY)\s*:\s*\d+$"
)


class _Resp:
    def __init__(self, text):
        self.text = text


def _text(path):
    raw = open(os.path.join(FIXTURES, path), "rb").read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _scraped(path, text=None):
    """{roll call number: sorted voter names} from the scraper's own scrape_votes()."""
    text = _text(path) if text is None else text
    scraper = OKBillScraper.__new__(OKBillScraper)
    scraper.warning = lambda *a, **k: None
    scraper.get = lambda url, verify=False: _Resp(text)
    bill = Bill("HB 1", legislative_session="2025", chamber="lower", title="t")
    url = "https://www.oklegislature.gov/cf/votes/House/x_VOTES.HTM"
    rolls = {}
    for v in scraper.scrape_votes(bill, url):
        # every section lists as many voters as it declares
        for count in v.counts:
            listed = [x for x in v.votes if x["option"] == count["option"]]
            assert len(listed) == count["value"], (v.dedupe_key, count)
        rolls[v.dedupe_key.split("#")[1]] = sorted(x["voter_name"] for x in v.votes)
    return rolls


def _printed(path, text=None):
    """{roll call number: sorted names} read from the page's name lines, one name per text run
    between the HTML's padding spans."""
    text = _text(path) if text is None else text
    text = unicodedata.normalize("NFKD", text.replace("\r\n", " "))
    rolls, rcs, names, keep = {}, None, [], False
    for p in html.fromstring(text).xpath("//p"):
        line = p.xpath("string()").strip()
        number = re.search(r"RCS#\s+(\d+)", line)
        if number and line.startswith("YEAS"):
            rcs, names = number.group(1), []
        elif "*****" in line:
            if rcs and rcs not in rolls:
                rolls[rcs] = sorted(names)
            rcs, keep = None, False
        elif rcs and SECTION.match(line):
            keep = not line.startswith("VACAN")
        elif rcs and keep and line:
            names.extend(run.strip() for run in p.itertext() if run.strip())
    return rolls


def test_two_word_surname_is_one_name():
    line = "Crosswhite Hader   Marti              Shaw               Worthen"
    assert extract_names(line, 4) == ["Crosswhite Hader", "Marti", "Shaw", "Worthen"]


def test_one_word_names_beside_it_stay_apart():
    # a lone "Crosswhite" or "Hader" is still a name of its own
    line = "Crosswhite         Marti              Hader"
    assert extract_names(line, 3) == ["Crosswhite", "Marti", "Hader"]


# OPEN-802: surnames on no Oklahoma page and in no code, put into a real House page in place of
# Rep. May and Rep. Pae, keeping the page's own padding spans around them.
SYNTHETIC = {"May": "Vellacott Tamsweather", "Pae": "Dunmerrow Ash Quorrin"}


def _with_synthetic_surnames(path):
    text = _text(path)
    for printed, synthetic in SYNTHETIC.items():
        assert ">%s<span" % printed in text
        text = text.replace(">%s<span" % printed, ">%s<span" % synthetic)
    return text


def test_synthetic_multi_word_surnames_stay_one_voter():
    path = "ok_open687/House_HB1003_VOTES.HTM"
    text = _with_synthetic_surnames(path)
    scraped, printed = _scraped(path, text), _printed(path, text)
    assert scraped and scraped == printed
    voters = [n for names in scraped.values() for n in names]
    for synthetic in SYNTHETIC.values():
        assert synthetic in voters
        for word in synthetic.split():
            assert word not in voters
    for printed_name in SYNTHETIC:
        assert printed_name not in voters


@pytest.mark.parametrize("path", HOUSE_PAGES)
def test_house_roll_calls_list_every_printed_voter_once(path):
    scraped, printed = _scraped(path), _printed(path)
    assert scraped and set(scraped) == set(printed)
    for rcs, names in scraped.items():
        assert names == printed[rcs], rcs
        assert "Hader" not in names and "Crosswhite" not in names


def test_she_is_on_the_fixture_roll_calls():
    # every one of these pages has her on at least one roll call
    for path in HOUSE_PAGES:
        assert any("Crosswhite Hader" in n for n in _scraped(path).values()), path
