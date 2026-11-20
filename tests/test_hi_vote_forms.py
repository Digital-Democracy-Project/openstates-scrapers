"""Tests for OPEN-709: Hawaii tally forms parse_vote() in hi/bills.py used to miss.

Every text is real, from the status pages on data.capitol.hawaii.gov (session/measure_indiv.aspx,
read 2026-11-20): Senate Final Reading in the "0 No(es): none" form (HB 1642 of 2026, seven 2026
measures in all) and the same form with names (HB 862 of 2021). Not read here: the House floor form
("... voting no (3) ...", no aye count) and the Senate resolution adoption, whose ayes need the
roster on the vote's date, and the veto overrides, held until OPEN-710 stores their result (see the
ticket).
"""
import json
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open709")

FINAL_NONE = (
    "Passed Final Reading, as amended (CD 1). Ayes, 25; Aye(s) with reservations: none . "
    "0 No(es): none.  0 Excused: none. "
)
FINAL_NAMES = (
    "Passed Final Reading, as amended (CD 1). Ayes, 23; Aye(s) with reservations: Senator(s) "
    "Chang, Ihara, Taniguchi . 2 No(es): Senator(s) Acasio, Fevella.  0 Excused: none."
)


def _parse(text):
    scraper = object.__new__(HIBillScraper)
    return scraper.parse_vote(text)[0]


@pytest.mark.parametrize(
    "text,counts,resv,no,excused",
    [
        (FINAL_NONE, ("25", "0", "0"), "none", "none", "none"),
        (
            FINAL_NAMES,
            ("23", "2", "0"),
            "Senator(s) Chang, Ihara, Taniguchi",
            "Senator(s) Acasio, Fevella",
            "none",
        ),
    ],
)
def test_forms_are_read(text, counts, resv, no, excused):
    v = _parse(text)
    assert (v["n_yes"], v["n_no"], v["n_excused"]) == counts
    assert v["yes_resv"] == resv
    assert v["no"] == no
    assert v["excused"] == excused


def test_kept_senate_third_reading_still_read_by_its_old_pattern():
    # a real form the scraper already kept (HB 1642, 2026-04-14): the earlier pattern still
    # reads it, exactly as on main (the new pattern has no "yes" group)
    v = _parse(
        "Report adopted; Passed Third Reading.  Ayes, 25; Aye(s) with reservations: none .  "
        "Noes, 0 (none). Excused, 0 (none).  Transmitted to House."
    )
    assert v == {
        "n_yes": "25",
        "yes": "",
        "yes_resv": "none ",
        "n_no": "0",
        "no": "none",
        "n_excused": "0",
        "excused": "none",
    }


def _votes(name, bill_id):
    page = lxml.html.fromstring(open(os.path.join(FIXTURES, name), "rb").read())
    table = page.xpath('//div[contains(@id, "UpdatePanel1")]//table[1]')[0]
    scraper = object.__new__(HIBillScraper)
    scraper.short_ids = {}
    bill = Bill(bill_id, "2026 Regular Session", "title", chamber="lower")
    out = []
    for v in scraper.parse_bill_actions_table(
        bill, table, bill_id, "2026 Regular Session", "https://example/" + name, "lower"
    ):
        counts = {c["option"]: c["value"] for c in v.counts}
        named = {}
        for x in v.votes:
            named.setdefault(x["option"], []).append(x["voter_name"])
        out.append(
            (
                v.start_date,
                json.loads(v.organization[1:])["classification"],
                v.motion_text,
                v.motion_classification,
                counts,
                named,
            )
        )
    return out


def _floor(votes):
    return [v for v in votes if v[3] == ["passage"]]


def test_hb1642_senate_final_reading_becomes_a_roll_call():
    floor = _floor(_votes("HB1642.html", "HB1642"))
    assert (
        "2026-05-06",
        "upper",
        "Passed Final Reading, as amended (CD 1).",
        ["passage"],
        {"yes": 25, "no": 0, "not voting": 0},
        {},
    ) in floor


def test_hb862_2021_final_reading_with_names():
    floor = _floor(_votes("HB862-2021.html", "HB862"))
    final = [v for v in floor if v[2] == "Passed Final Reading, as amended (CD 1)."]
    assert [(v[0], v[1], v[4], v[5]) for v in final] == [
        (
            "2021-04-27",
            "upper",
            {"yes": 23, "no": 2, "not voting": 0},
            {"yes": ["Chang", "Ihara", "Taniguchi"], "no": ["Acasio", "Fevella"]},
        )
    ]
    # the veto overrides on this page are not read yet (OPEN-710 first)
    assert not [v for v in floor if v[2].startswith("Veto overridden")]


def test_named_voters_match_their_counts():
    # each named no / excused list has as many names as its count says
    for name, bill_id in (("HB862-2021.html", "HB862"), ("HB1642.html", "HB1642")):
        for v in _votes(name, bill_id):
            counts, named = v[4], v[5]
            for option in ("no", "not voting"):
                if option in named:
                    assert len(named[option]) == counts[option], v[2]
