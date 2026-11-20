"""OPEN-696: Missouri member-level floor roll calls.

Missouri's bills scraper only made totals-only votes, so no Missouri legislator could be
scored. scrapers/mo/votes.py now reads the House's one-PDF-per-roll-call files and the
Senate's daily journals. The fixtures are the legislature's own 2026 files:

* House roll calls 049.010 (HB 2885, third reading), 065.004 and 065.006 (SB 835: an
  amendment and the third reading), 065.001 (approving the journal, no bill), and the HTML
  error page documents.house.mo.gov answers for a roll call that does not exist.
* Senate journals for day 20 (a NAYS list on the line below its label, and a page break
  inside a YEAS list), day 23 (SB 835 third reading, page 416), day 55 (an emergency clause
  vote and "Excused from voting") and day 68 (SB 835's conference report and final passage
  on pages 1868-1869, HB 2885's Senate passage on page 1879).

The Senate page numbers are checked against the page references the Senate prints in its
own bill actions (SB 835: "S Third Read and Passed | S416-417", "CCS S Third Read and Passed
| S1869"; HB 2885's House XML: SenateJournalStartPage 1879).
"""
import json
import os
import shutil
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils import convert_pdf  # noqa: E402
from mo import Missouri  # noqa: E402
from mo.votes import (  # noqa: E402
    MOVoteScraper,
    bill_from_text,
    parse_house_rollcall,
    parse_senate_journal,
    vote_result,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mo_open696")


def fixture(name):
    return os.path.join(FIXTURES, name)


def text(name):
    return convert_pdf(fixture(name), type="text").decode("utf-8")


def by_option(votes):
    out = {}
    for option, name in votes:
        out.setdefault(option, []).append(name)
    return out


def senate(name):
    return parse_senate_journal(text(name))


# ── House roll-call PDFs ────────────────────────────────────────────────────


def test_house_third_reading_of_a_house_bill():
    rc = parse_house_rollcall(text("house_rollcall_049.010.pdf"))
    assert rc["bill"] == "HB 2885"
    assert rc["date"].strftime("%Y-%m-%d") == "2026-04-09"
    # the PDF's own totals: Yes 112, No 27, Present 0, Absent 19
    assert Counter(o for o, _ in rc["votes"]) == {"yes": 112, "no": 27, "absent": 19}
    assert rc["totals"] == {"yes": 112, "no": 27, "other": 0, "absent": 19}
    votes = by_option(rc["votes"])
    assert "ALLEN" in votes["yes"] and "DURNELL" in votes["no"]
    assert "EALY" in votes["absent"]
    # a district number tells same-surname members apart
    assert "SMITH (46)" in votes["yes"] and "TAYLOR (48)" in votes["no"]
    assert "MR SPEAKER" in votes["yes"]


def test_house_votes_on_a_senate_bill():
    passage = parse_house_rollcall(text("house_rollcall_065.006.pdf"))
    assert passage["bill"] == "SB 835"
    assert Counter(o for o, _ in passage["votes"]) == {
        "yes": 133,
        "no": 7,
        "other": 1,
        "absent": 17,
    }
    amendment = parse_house_rollcall(text("house_rollcall_065.004.pdf"))
    assert amendment["bill"] == "SB 835"
    assert " - HA 3 - " in amendment["motion"]
    assert Counter(o for o, _ in amendment["votes"])["no"] == 89


def test_house_roll_call_without_a_bill_is_skipped():
    assert parse_house_rollcall(text("house_rollcall_065.001.pdf")) is None


# ── Senate journals ─────────────────────────────────────────────────────────


def test_senate_third_reading_of_sb_835():
    rcs = senate("RDay230219410-420.pdf")
    sb835 = [rc for rc in rcs if rc["bill"] == "SB 835"]
    assert len(sb835) == 1
    rc = sb835[0]
    assert rc["page"] == 416
    assert rc["date"].strftime("%Y-%m-%d") == "2026-02-19"
    votes = by_option(rc["votes"])
    assert len(votes["yes"]) == 32 and rc["totals"]["yes"] == 32
    assert "no" not in votes
    assert votes["absent"] == ["Brattin", "Williams"]
    # names with a district number and an apostrophe stay whole
    assert {"Brown (16)", "Brown (26)", "Gregory (15)", "O'Laughlin"} <= set(
        votes["yes"]
    )


def test_senate_conference_report_and_final_passage_name_the_bill_above():
    rcs = {(rc["page"], rc["bill"]): rc for rc in senate("RDay6805151864-1889.pdf")}
    # "Senator Crawford moved that the above conference committee report be adopted"
    # and "Was read the 3rd time and passed" name no bill themselves
    ccr, passage = rcs[(1868, "SB 835")], rcs[(1869, "SB 835")]
    assert "conference committee report" in ccr["motion"]
    assert passage["motion"].startswith("Was read the 3rd time and passed")
    assert by_option(passage["votes"])["no"] == ["Moon"]
    assert by_option(passage["votes"])["excused"] == ["Black", "Brown (16)", "Schroer"]
    assert len(by_option(passage["votes"])["yes"]) == 26
    # HB 2885's Senate passage, 27 to 0 as its House XML says
    hb2885 = rcs[(1879, "HB 2885")]
    assert Counter(o for o, _ in hb2885["votes"])["yes"] == 27
    assert "no" not in by_option(hb2885["votes"])


def test_senate_page_break_inside_a_list_and_count_on_the_label_line():
    rc = next(r for r in senate("RDay200212377-386.pdf") if r["bill"] == "SB 994")
    votes = by_option(rc["votes"])
    # "Williams—28" ends page 381; the running header "382 Journal of the Senate" is
    # not a senator, and "NAYS—Senators—2" puts its names on the next line
    assert len(votes["yes"]) == 28
    assert votes["no"] == ["Nicola", "Moon"]
    assert not any(name.isdigit() or "Journal" in name for _, name in rc["votes"])


def test_senate_emergency_clause_and_excused_from_voting():
    rcs = senate("RDay5504231120-1141.pdf")
    passage, clause = rcs[0], rcs[1]
    assert passage["bill"] == clause["bill"] == "HB 2637"
    assert clause["motion"] == "The emergency clause was adopted by the following vote:"
    assert ("not voting", "Luetkemeyer") in passage["votes"]
    # every roll call's names add up to the counts the journal prints
    for rc in rcs:
        counts = Counter(o for o, _ in rc["votes"])
        assert {o: counts[o] for o in rc["totals"]} == rc["totals"]


@pytest.mark.parametrize(
    "line,bill",
    [
        ("SS No. 2 for SCS for HCS for HB 2292, as amended", "HB 2292"),
        ("HCS SS SCS SBS 835 & 1111, A.A.", "SB 835"),
        ("SS for SCS for HCS for HJRs 173 and 174", "HJR 173"),
        ("Senate Committee Substitute for House Bill No. 2474", "HB 2474"),
        ("SENATE BILLS NOS. 835 and 1111", "SB 835"),
        ("SENATE JOINT RESOLUTION NO. 87", "SJR 87"),
        ("SA 3 failed of adoption by the following vote:", None),
        ("APPROVE JOURNAL", None),
    ],
)
def test_bill_from_text(line, bill):
    assert bill_from_text(line) == bill


@pytest.mark.parametrize(
    "motion,yes,no,result",
    [
        # the Senate journal's own words decide, not the tally (2026 journal, day 22)
        ("SA 3 failed of adoption by the following vote:", 20, 12, "fail"),
        ("which motion prevailed by the following vote:", 10, 20, "pass"),
        ("Was read the 3rd time and passed by the following vote:", 18, 14, "pass"),
        ("The emergency clause was by the following vote:", 10, 20, "fail"),
        (
            "Senator Trent moved that the vote by which SA 1 failed be reconsidered, "
            "which motion prevailed by the following vote:",
            10,
            20,
            "pass",
        ),
    ],
)
def test_senate_vote_result(motion, yes, no, result):
    assert vote_result(motion, yes, no) == result


# ── the scraper: chambers, keys, the walk ───────────────────────────────────


def make_scraper(tmp_path, files):
    """files maps a URL to a fixture; any other URL answers like a missing roll call."""
    scraper = MOVoteScraper(Missouri(), str(tmp_path))

    def urlretrieve(url, *args, **kwargs):
        copy = str(tmp_path / f"dl{len(os.listdir(tmp_path))}")
        shutil.copy(fixture(files.get(url, "house_rollcall_missing.html")), copy)
        return copy, None

    scraper.urlretrieve = urlretrieve
    return scraper


def org(vote):
    return json.loads(vote.organization[1:])["classification"]


def test_house_walk_keys_and_chamber(tmp_path):
    base = "https://documents.house.mo.gov/billtracking/bills261/rollcalls/"
    scraper = make_scraper(
        tmp_path,
        {
            base + "001.001.pdf": "house_rollcall_065.001.pdf",
            base + "001.002.pdf": "house_rollcall_049.010.pdf",
            # day 2 has none; day 3 does
            base + "003.001.pdf": "house_rollcall_065.006.pdf",
        },
    )
    votes = list(scraper._scrape_lower_chamber("2026"))
    assert [v.dedupe_key for v in votes] == ["mo-2026-H-001.002", "mo-2026-H-003.001"]
    for v in votes:
        v.validate()
        assert org(v) == "lower"
    hb, sb = votes
    assert hb.bill_identifier == "HB 2885"
    assert json.loads(hb.bill[1:])["from_organization__classification"] == "lower"
    # the House voting on a Senate bill: the vote is the House's, the bill the Senate's
    assert sb.bill_identifier == "SB 835"
    assert json.loads(sb.bill[1:])["from_organization__classification"] == "upper"
    assert {c["option"]: c["value"] for c in sb.counts} == {
        "yes": 133,
        "no": 7,
        "other": 1,
        "absent": 17,
    }
    assert sb.result == "pass"


def test_senate_keys_hold_session_and_skip_a_journal_listed_twice(tmp_path):
    list_url = "https://www.senate.mo.gov/journallist/?SelectedYear=2026"
    day23 = "https://www.senate.mo.gov/26info/Journals/RDay230219410-420.pdf"
    again = "https://www.senate.mo.gov/26info/Journals/RDay23.pdf"
    special = "https://www.senate.mo.gov/26info/Journals/T1Day0109161-2.pdf"
    scraper = make_scraper(
        tmp_path,
        {
            day23: "RDay230219410-420.pdf",
            again: "RDay230219410-420.pdf",
            # an extraordinary session's journal belongs to 2026S1, not 2026
            special: "RDay5504231120-1141.pdf",
        },
    )

    class Page:
        content = (
            '<a href="/26info/Journals/RDay230219410-420.pdf">23</a>'
            '<a href="/26info/Journals/RDay23.pdf">23</a>'
            '<a href="/26info/Journals/T1Day0109161-2.pdf">special</a>'
        ).encode()

    fetched = []
    scraper.get = lambda url: fetched.append(url) or Page()
    votes = list(scraper._scrape_upper_chamber("2026"))
    assert fetched == [list_url]
    assert special not in [s["url"] for v in votes for s in v.sources]
    keys = [v.dedupe_key for v in votes]
    assert len(keys) == len(set(keys)) == len(senate("RDay230219410-420.pdf"))
    sb835 = next(v for v in votes if v.bill_identifier == "SB 835")
    assert sb835.dedupe_key == "mo-2026-S-416-2"
    assert org(sb835) == "upper"
    assert sb835.start_date == "2026-02-19"
    assert sb835.result == "pass"
    sb835.validate()


def test_house_result_ignores_words_in_the_bill_title(tmp_path):
    # a House header carries the bill's short title; "LOST" there is not the outcome
    rc = parse_house_rollcall(text("house_rollcall_049.010.pdf"))
    rc["motion"] = rc["motion"].replace("VESSEL REGISTRATION FEES", "LOST PROPERTY")
    vote = make_scraper(tmp_path, {})._make_vote("2026", "lower", rc, "k", [])
    assert vote.result == "pass"
