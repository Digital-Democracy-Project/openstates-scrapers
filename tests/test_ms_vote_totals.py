"""OPEN-733: a Mississippi roll call that prints a list's total with one dash ("Total-51")
keeps the name before the total, as one printed with two ("Total--122") always did.

The fixtures are the text (pdftotext -layout, as the scraper's convert_pdf runs it) of real
roll-call PDFs from billstatus.ls.state.ms.us, run through the scraper's own scrape_votes()
with no network:

* one dash: 2026 SB 2096 and the roll call after it, Senate concurrences (2026/pdf/votes/
  senate/0650012.pdf, 0660007.pdf, saved for OPEN-693): "... Williams, Younger. Total-51.";
* two dashes: 2024 HB 74, House (2024/pdf/votes/house/0660006.pdf, saved 2026-11-21), whose
  "Mr. Speaker. Total--" breaks onto a new line before "122.", and 2026 HB 1, House
  (2026/pdf/votes/house/0030003.pdf, saved for OPEN-693).

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
OPTIONS = {"Yeas": "yes", "Nays": "no", "Absent": "not voting"}


def printed_lists(text):
    """{option: (names, printed total)} for every list that prints a total ("Nays--None."
    prints none and is left out)."""
    flat = " ".join(text.split())
    found = re.findall(
        r"(Yeas|Nays|Absent)[a-z ]*--((?:(?!--).)*?)\. Total-+ ?(\d+)", flat
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
        assert len(names) == total, (option, fixture)
        assert got == sorted(names), (option, fixture)
        counts = {c["option"]: c["value"] for c in vote.counts}
        assert counts[option] == total, (option, fixture)
    assert last_yea in [v["voter_name"] for v in vote.votes if v["option"] == "yes"]


def test_one_and_two_dash_totals_both_covered():
    assert {dashes for _, _, dashes, _ in ROLL_CALLS} == {"-", "--"}
