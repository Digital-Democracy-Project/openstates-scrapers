"""OPEN-714: Missouri counts only the final vote (Ramon 2026-11-20, "Final vote only").

When a chamber first takes the other chamber's version of a bill (or adopts a conference
report) and then holds a separate final passage roll call, only the final roll call is
passage. The first keeps a label that is not counted: a concurrence is "amendment" (as ia
labels it), a conference report vote is unlabelled. With no final roll call after it, the
concurrence or conference report vote stays passage (pa OPEN-617, la OPEN-583).

Fixtures are the legislature's own 2026 files:

* House roll-call PDFs (tests/fixtures/mo_open705/): 033.002 and 033.003 (HB 2014: "On
  motion of Representative Deaton, SS SCS HCS HB 2014 was adopted", then "was truly agreed
  to and finally passed", House journal day 33) and 060.002-060.004 (HBs 2637 & 3155: CCR
  adopted, CCS passed, emergency clause).
* Senate journals: day 68 (tests/fixtures/mo_open696/: SB 835's CCR on page 1868 and its
  passage on 1869; SB 1572's concurrence and passage on 1870), and in
  tests/fixtures/mo_open714/ day 58 (page 1249, HBs 2637 & 3155's CCR adopted; page 1250,
  "Was read the 3rd time and passed" after a title that names HBs 2273 ...) and day 64
  (page 1617, SB 973's CCR adopted on May 11; the final passage motion was withdrawn and
  the bill passed on May 15, day 68 page 1867).
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils import convert_pdf  # noqa: E402
from mo import Missouri  # noqa: E402
from mo.votes import (  # noqa: E402
    MOVoteScraper,
    final_vote_only,
    parse_house_rollcall,
    parse_senate_journal,
)

HERE = os.path.dirname(__file__)
FOLDERS = [
    os.path.join(HERE, "fixtures", name)
    for name in ("mo_open714", "mo_open705", "mo_open696")
]
DAY58 = "RDay5804291213-1257.pdf"
DAY64 = "Rday6405111615-1637.pdf"
DAY68 = "RDay6805151864-1889.pdf"


def fixture(name):
    for folder in FOLDERS:
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(name)


def text(name):
    return convert_pdf(fixture(name), type="text").decode("utf-8")


def house(number):
    return parse_house_rollcall(text(f"house_rollcall_{number}.pdf"))


def labelled(roll_calls):
    return [
        (rc["bill"], label)
        for rc, label in zip(roll_calls, final_vote_only(roll_calls))
    ]


# ── House ──────────────────────────────────────────────────────────────────


def test_house_concurrence_then_final_passage():
    adopted, passed = house("033.002"), house("033.003")
    # the two PDFs carry the same header: only the order tells them apart
    assert adopted["motion"] == passed["motion"]
    assert labelled([adopted, passed]) == [
        ("HB 2014", ["amendment"]),
        ("HB 2014", ["passage"]),
    ]


def test_house_conference_report_then_ccs():
    ccr, ccs = house("060.002"), house("060.003")
    assert labelled([ccr, ccs]) == [("HB 2637", []), ("HB 2637", ["passage"])]


def test_house_concurrence_or_ccr_with_no_final_vote_stays_passage():
    # none in 2026; the rule still holds when the final roll call is missing
    assert labelled([house("033.002")]) == [("HB 2014", ["passage"])]
    assert labelled([house("060.002")]) == [("HB 2637", ["passage"])]
    # a final vote on another bill does not count
    assert labelled([house("060.002"), house("033.003")]) == [
        ("HB 2637", ["passage"]),
        ("HB 2014", ["passage"]),
    ]


def test_third_reading_followed_by_a_later_vote_is_untouched():
    # a third reading (not a concurrence or CCR) stays passage whatever follows
    third = house("049.010")
    again = dict(third)
    assert labelled([third, again]) == [
        ("HB 2885", ["passage"]),
        ("HB 2885", ["passage"]),
    ]


# ── Senate ─────────────────────────────────────────────────────────────────


def senate(name):
    return parse_senate_journal(text(name))


def by_page(roll_calls):
    out = {}
    for rc, label in zip(roll_calls, final_vote_only(roll_calls)):
        out.setdefault((rc["page"], rc["bill"]), []).append(label)
    return out


def test_senate_conference_report_and_concurrence_then_final_passage():
    got = by_page(senate(DAY68))
    # "the above conference committee report be adopted", then "Was read the 3rd time"
    assert got[(1868, "SB 835")] == [[]]
    assert got[(1869, "SB 835")] == [["passage"]]
    rcs = [rc for rc in senate(DAY68) if rc["bill"] == "SB 1572"]
    assert [rc["motion"][:40] for rc in rcs] == [
        "Senator Henderson moved that HCS for SB ",
        "On motion of Senator Henderson, HCS for ",
    ]
    assert final_vote_only(rcs) == [["amendment"], ["passage"]]
    # only a passage vote after it makes the concurrence the first of a pair
    assert final_vote_only(rcs[::-1]) == [["passage"], ["passage"]]


def test_senate_final_passage_after_a_ccr_names_the_ccs_bill_not_one_in_its_title():
    rcs = senate(DAY58)
    ccr = next(rc for rc in rcs if rc["page"] == 1249)
    passed = next(rc for rc in rcs if rc["motion"].startswith("Was read the 3rd time"))
    assert "conference committee report be adopted" in ccr["motion"]
    # the title of CCS for ... HBs 2637 and 3155 names "house bills nos. 2273, 1946, ..."
    assert (ccr["bill"], passed["bill"], passed["page"]) == ("HB 2637", "HB 2637", 1250)
    assert by_page(rcs)[(1249, "HB 2637")] == [[]]
    # the passage, then "The emergency clause was adopted" (the bill voted on last)
    assert by_page(rcs)[(1250, "HB 2637")] == [["passage"], []]


def test_senate_ccr_on_one_day_final_passage_on_a_later_day():
    day64 = [rc for rc in senate(DAY64) if rc["bill"] == "SB 973"]
    day68 = [rc for rc in senate(DAY68) if rc["bill"] == "SB 973"]
    assert [rc["page"] for rc in day64 + day68] == [1617, 1867]
    # day 64 alone: the final passage motion was withdrawn, so the CCR stays passage
    assert final_vote_only(day64) == [["passage"]]
    assert final_vote_only(day64 + day68) == [[], ["passage"]]


def test_senate_walk_pairs_across_journals_listed_out_of_order(tmp_path):
    # journallist puts RDay21.pdf first; the walk sorts by date and page
    list_url = "https://www.senate.mo.gov/journallist/?SelectedYear=2026"
    base = "https://www.senate.mo.gov/26info/Journals/"
    files = {base + DAY68: DAY68, base + DAY64: DAY64}
    scraper = MOVoteScraper(Missouri(), str(tmp_path))

    def urlretrieve(url, *args, **kwargs):
        copy = str(tmp_path / f"dl{len(os.listdir(tmp_path))}")
        shutil.copy(fixture(files[url]), copy)
        return copy, None

    class Page:
        content = "".join(
            f'<a href="/26info/Journals/{name}">x</a>' for name in (DAY68, DAY64)
        ).encode()

    scraper.urlretrieve = urlretrieve
    scraper.get = lambda url: Page()
    votes = list(scraper._scrape_upper_chamber("2026"))
    sb973 = [
        (v.dedupe_key, v.motion_classification)
        for v in votes
        if v.bill_identifier == "SB 973"
    ]
    assert sb973 == [("mo-2026-S-1617-1", []), ("mo-2026-S-1867-1", ["passage"])]
    assert all(list_url in [s["url"] for s in v.sources] for v in votes)
