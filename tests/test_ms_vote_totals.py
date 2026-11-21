"""OPEN-733: a Mississippi roll call that prints a list's total with one dash ("Total-51")
keeps the name before the total, as one printed with two ("Total--122") always did.

OPEN-735: a total printed without its closing period ("Total--110", "Nays-0") ends its list
too, instead of running the next list into it.

The fixtures are the text (pdftotext -layout, as the scraper's convert_pdf runs it) of real
roll-call PDFs from billstatus.ls.state.ms.us, run through the scraper's own scrape_votes()
with no network:

* one dash: 2026 SB 2096 and the roll call after it, Senate concurrences (2026/pdf/votes/
  senate/0650012.pdf, 0660007.pdf, saved for OPEN-693): "... Williams, Younger. Total-51.";
* two dashes: 2024 HB 74, House (2024/pdf/votes/house/0660006.pdf, saved 2026-11-21), whose
  "Mr. Speaker. Total--" breaks onto a new line before "122.", and 2026 HB 1, House
  (2026/pdf/votes/house/0030003.pdf, saved for OPEN-693);
* no closing period: 2026 HB 1924, the House veto override (2026/pdf/votes/house/
  1000005.pdf, saved for OPEN-693, re-fetched 2026-11-21 and byte-identical), which prints
  "Mr. Speaker.", then "Total--110", "Nays-0", "... Karriem. Total--5" and the absent list
  with its "Total--5" on the next line.

The expected names and totals are read straight from the printed text, not from the scraper.
"""
import os
import re
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

import ms.bills  # noqa: E402
from ms.bills import MSBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ms_open693")

# the option the scraper files each printed list under ("Absent or those not voting" goes
# to "not voting")
OPTIONS = {"Yeas": "yes", "Nays": "no", "Present": "other", "Absent": "not voting"}

# a printed total the legislature got wrong: (fixture, option) -> the real count of the
# printed names. 2026 HB 1924's absent list names 7 members but prints "Total--5"; the
# 110 yeas, 5 present and 7 absent make the House's 122 seats.
MISPRINTED = {("2026_house_1000005.txt", "not voting"): 7}


def printed_lists(text):
    """{option: (names, printed total)} for every list that prints a total ("Nays--None."
    and "Nays-0" print none and are left out). The total's closing period is optional."""
    flat = " ".join(text.split())
    found = re.findall(
        r"(Yeas|Nays|Present|Absent)[a-z ]*--((?:(?!--).)*?)\.? Total-+ ?(\d+)", flat
    )
    # every printed total belongs to a list found here, and no list is read twice
    assert len(found) == len(re.findall(r"Total-+ ?\d", flat))
    lists = {
        OPTIONS[label]: ([n.strip() for n in names.split(",")], int(total))
        for label, names, total in found
    }
    assert len(lists) == len(found)
    return lists


def recorded(monkeypatch, tmp_path, fixture, chamber):
    text = open(os.path.join(FIXTURES, fixture), "rb").read()
    scraper = MSBillScraper.__new__(MSBillScraper)

    def urlretrieve(url, verify=False):
        path = tmp_path / "vote.pdf"
        path.write_bytes(b"")
        return str(path), None

    monkeypatch.setattr(scraper, "urlretrieve", urlretrieve, raising=False)
    monkeypatch.setattr(ms.bills, "convert_pdf", lambda path, kind: text)
    # no Speaker in the manifest: names are kept as printed (OPEN-731)
    manifest = tmp_path / "jurisdictions.yaml"
    manifest.write_text("ms: {}\n")
    monkeypatch.setenv("DDP_JURISDICTIONS_MANIFEST", str(manifest))
    bill = Bill("HB 1", legislative_session="2026", chamber=chamber, title="t")
    (vote,) = scraper.scrape_votes(
        "http://billstatus.ls.state.ms.us/x.pdf",
        "Passed",
        datetime(2026, 1, 1),
        chamber,
        bill,
    )
    return vote, text.decode()


ROLL_CALLS = [
    # (fixture, chamber, dashes before the yeas total, last yea)
    ("2026_senate_0650012.txt", "upper", "-", "Younger"),
    ("2026_senate_0660007.txt", "upper", "-", "Younger"),
    ("2024_house_0660006.txt", "lower", "--", "Mr. Speaker"),
    ("2026_house_0030003.txt", "lower", "--", "Mr. Speaker"),
    ("2026_house_1000005.txt", "lower", "--", "Mr. Speaker"),
]


@pytest.mark.parametrize("fixture,chamber,dashes,last_yea", ROLL_CALLS)
def test_every_listed_member_is_recorded(
    monkeypatch, tmp_path, fixture, chamber, dashes, last_yea
):
    vote, text = recorded(monkeypatch, tmp_path, fixture, chamber)
    flat = " ".join(text.split())
    # the fixture really prints the yeas total the way the case says
    assert re.search(r"%s\. Total%s ?\d" % (re.escape(last_yea), dashes), flat)
    lists = printed_lists(text)
    assert "yes" in lists
    for option, (names, total) in lists.items():
        got = sorted(v["voter_name"] for v in vote.votes if v["option"] == option)
        # each list's name count equals its printed total, and they are the printed names
        total = MISPRINTED.get((fixture, option), total)
        assert len(names) == total, (option, fixture)
        assert got == sorted(names), (option, fixture)
        counts = {c["option"]: c["value"] for c in vote.counts}
        assert counts[option] == total, (option, fixture)
    assert last_yea in [v["voter_name"] for v in vote.votes if v["option"] == "yes"]


def test_totals_without_a_closing_period(monkeypatch, tmp_path):
    # 2026 HB 1924 House override: no list runs into the next, no name is lost or moved
    fixture = "2026_house_1000005.txt"
    vote, text = recorded(monkeypatch, tmp_path, fixture, "lower")
    flat = " ".join(text.split())
    for printed in ("Mr. Speaker. Total--110 Nays-0 Present--", "Yates. Total--5 Nec"):
        assert printed in flat
    by_option = {}
    for v in vote.votes:
        by_option.setdefault(v["option"], []).append(v["voter_name"])
    assert {o: len(n) for o, n in by_option.items()} == {
        "yes": 110,
        "other": 5,
        "not voting": 7,
    }
    assert "Crudup" in by_option["other"]
    assert by_option["not voting"][-1] == "Yates"
    assert sum(len(n) for n in by_option.values()) == 122
    # the misprint allowance is real: 7 names under a printed "Total--5"
    assert printed_lists(text)["not voting"][1] == 5
    assert len(printed_lists(text)["not voting"][0]) == 7


def test_one_and_two_dash_totals_both_covered():
    assert {dashes for _, _, dashes, _ in ROLL_CALLS} == {"-", "--"}
