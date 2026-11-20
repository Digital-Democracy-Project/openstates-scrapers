"""Tests for OPEN-694: Montana's roll calls get a type from the bill action they belong to and their motion.

A Montana floor motion ("Do Pass", "Do Concur") is the same on second and third reading, so the scraper
classifies "<bill action>: <motion>" (bills API, 2025 on) or the bill action alone (archive API, 2023 and
before). Only the third reading is passage; committee motions are committee-passage; amendment votes are
"amendment".

The fixtures are the bills API's own answers for eight 2025 bills (read 2026-11-20): the bill's search row
(bills/v1/bills/search, sessionIds [2]), its floor votes (bills/v1/votes/findByBillId) and its committee
votes (committees/v1/executiveActions/findByBillId), run through the scraper's own scrape_votes_page().
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from classify_motion import classify_motion  # noqa: E402
from mt.bills import MTBillScraper, vote_classification  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mt_open694")

P, C, A, N = ["passage"], ["committee-passage"], ["amendment"], []

# Every (bill action, motion) of 2025 that reaches a VoteEvent, with its count among the 5,570 floor and
# 3,147 committee roll calls the scraper emits (motions carrying a member's or amendment's name trimmed to one).
REAL_2025 = [
    # third reading: the final vote, passage (a lost one too)
    ("(H) 3rd Reading", "Do Pass", P),  # 700
    ("(S) 3rd Reading", "Do Pass", P),  # 406
    (
        "(S) 3rd Reading",
        "Do Concur",
        P,
    ),  # 595 (the second chamber passing the other's bill)
    ("(H) 3rd Reading", "Do Concur", P),  # 307
    (
        "(H) 3rd Reading",
        "Unknown",
        P,
    ),  # 5: the API's motion is null (2025 HB 639, lost)
    ("(H) 3rd Reading; 2nd Chamber Vote Required", "Do Concur", P),  # 2
    ("(S) 3rd Reading; 2nd Chamber Vote Required", "Do Concur", P),  # 3 (2025 HB 316)
    # concurrence in the other chamber's amendments, conference reports: third reading is passage
    ("(H) 3rd Reading Senate Amendments", "Do Concur", P),  # 149
    ("(S) 3rd Reading House Amendments", "Do Pass", P),  # 86
    ("(S) 3rd Reading Conference Committee Report", "Do Adopt", P),  # 10
    ("(H) 3rd Reading Conference Committee Report", "Do Adopt", P),  # 9
    ("(H) 3rd Reading Free Conference Committee Report", "Do Adopt", P),  # 6
    ("(S) 3rd Reading Free Conference Committee Report", "Do Adopt", P),  # 6
    # a simple resolution's adoption (SR, HR): one floor vote, on second reading
    ("(S) 2nd Reading", "Do Adopt", P),  # 105 (2025 SR 33)
    ("(H) 2nd Reading", "Do Adopt", P),  # 6
    # second reading: not passage (Utah precedent), whatever it votes on
    ("(H) 2nd Reading", "Do Pass", N),  # 753
    ("(S) 2nd Reading", "Do Concur", N),  # 600
    ("(S) 2nd Reading", "Do Pass", N),  # 428
    ("(H) 2nd Reading", "Do Concur", N),  # 336
    ("(H) 2nd Reading Senate Amendments", "Do Concur", N),  # 153
    ("(S) 2nd Reading House Amendments", "Do Pass", N),  # 86
    ("(H) 2nd Reading", "Do Pass As Amended", N),  # 57
    ("(S) 2nd Reading", "Do Pass As Amended", N),  # 52
    ("(S) 2nd Reading", "Do Concur As Amended", N),  # 27
    ("(H) 2nd Reading", "Do Concur As Amended", N),  # 9
    ("(S) 2nd Reading Conference Committee Report", "Do Adopt", N),  # 10
    ("(H) 2nd Reading Conference Committee Report", "Do Adopt", N),  # 8
    ("(H) 2nd Reading Conference Committee Report", "Do Concur", N),  # 1
    ("(S) 2nd Reading Free Conference Committee Report", "Do Adopt", N),  # 6
    ("(H) 2nd Reading Free Conference Committee Report", "Do Adopt", N),  # 6
    ("(S) 2nd Reading House Amendments", "Do Not Concur", N),  # 8
    ("(H) 2nd Reading Senate Amendments", "Do Not Concur", N),  # 6
    ("(S) 2nd Reading House Amendments", "Do Pass As Amended", N),  # 1
    ("(H) 2nd Reading", "Do Not Pass", N),  # 2
    # the governor's amendments (amendatory veto): rejecting them does not kill the bill
    ("(H) 3rd Reading Governor's Amendments", "Do Concur", N),  # 8
    ("(S) 3rd Reading Governor's Amendments", "Do Concur", N),  # 9
    ("(H) 2nd Reading Governor's Amendments", "Do Concur", N),  # 9
    ("(S) 2nd Reading Governor's Amendments", "Do Concur", N),  # 9
    # procedure
    (
        "(S) 2nd Reading Indefinitely Postponed",
        "Indefinitely Postpone -McGillvray",
        N,
    ),  # 75
    (
        "(S) Take from Committee; Place on 2nd Reading",
        "Take HB 129 from Comm-Kassmier",
        N,
    ),  # 36
    (
        "(H) Take from Committee; Place on 2nd Reading",
        "Take HB 478 from JUH - Nicol",
        N,
    ),  # 21
    ("(S) Motion", "Take SB 432 from Comm-Noland", N),  # 29
    ("(H) Motion", "Take HB 552 From APH to 3rd Reading - Lee", N),  # 7
    ("(S) Motion", "Place on Third Reading-Kassmier", N),  # 3
    ("(H) Motion", "Rerefer -to APH - Zolnikov", N),  # 1
    ("(H) Reconsidered Previous Action", "ReconsAction - Maness", N),  # 26
    ("(S) Reconsidered Previous Action", "ReconsAction -Flowers", N),  # 24
    ("(S) Motion", "ReconsAction -Dunwell", N),  # 5
    # no bill action on the vote: the stage is unknown, so never passage
    (None, "Do Concur", N),  # 10
    (None, "Do Pass", N),  # 5
    (None, "Do Pass As Amended", N),  # 1
    (None, "Rerefer to Senate Transportation-Tempel", N),  # 21
    (None, "Cloture-Duram", N),  # 19
    (None, "ReconsAction -Usher", N),  # 6
    (None, "Take from STH to Second Reading", N),  # 5
    (None, "Indefinitely Postpone -McGillvray", N),  # 3
    # amendments
    (
        "(S) 2nd Reading Motion to Amend",
        "AMD-SB0307.002.005 McGillvray D/PASS",
        A,
    ),  # 151
    ("(H) 2nd Reading Motion to Amend", "AMD-HB0038.002.001 Baum DO PASS", A),  # 140
    ("(H) 2nd Reading Motion to Amend", "HB0623.002.002 - Sooktis DO PASS", A),
    ("(S) 2nd Reading Motion to Amend", "SB0114.001.001", A),
    ("(S) 2nd Reading Motion to Amend", "AMD- HB0231.004.008Dunwell D/PASS", A),
    (None, "AMD-HB0015.001.003 Romano DO PASS", A),  # 2
    # committee (executiveActions): the motion is a key
    ("(H) Committee Executive Action", "do_pass", C),  # 529
    ("(S) Committee Executive Action", "be_concurred_in", C),  # 467
    ("(S) Committee Executive Action", "do_pass", C),  # 315
    ("(H) Committee Executive Action", "do_pass_as_amended", C),  # 314
    ("(H) Committee Executive Action", "be_concurred_in", C),  # 259
    ("(S) Committee Executive Action", "be_concurred_in_as_amended", C),  # 158
    ("(S) Committee Executive Action", "do_pass_as_amended", C),  # 154
    ("(S) Committee Executive Action", "resolution_adopted", C),  # 149
    ("(H) Committee Executive Action", "be_concurred_in_as_amended", C),  # 116
    ("(H) Committee Executive Action", "resolution_adopted", C),  # 29
    ("(S) Committee Executive Action", "resolution_adopted_as_amended", C),  # 10
    ("(H) Committee Executive Action", "resolution_adopted_as_amended", C),  # 3
    ("(H) Tabled in Committee", "to_table", N),  # 335
    ("(S) Tabled in Committee", "to_table", N),  # 279
    ("(H) Taken from Table in Committee", "to_take_from_the_table", N),  # 16
    ("(S) Taken from Table in Committee", "to_take_from_the_table", N),  # 14
    # committee amendment motions (today the scraper drops these: they carry no billStatusId)
    (None, "be_amended", A),
    (None, "bill_is_amended_as_follows", A),
    (None, "further_amend_the_disputed_amendement", A),
]


@pytest.mark.parametrize("bill_action,motion,expected", REAL_2025)
def test_real_2025_texts(bill_action, motion, expected):
    assert vote_classification(bill_action, motion) == expected


# Archive API (sessions up to 2023): the bill action is the whole text. Every action with a tally of 2023.
REAL_ARCHIVE = [
    ("(H) 3rd Reading Passed", P),  # 655
    ("(S) 3rd Reading Concurred", P),  # 531
    ("(S) 3rd Reading Passed", P),  # 404
    ("(H) 3rd Reading Concurred", P),  # 318
    ("(H) 3rd Reading Passed as Amended by Senate", P),  # 163 (concurrence)
    ("(S) 3rd Reading Passed as Amended by House", P),  # 92
    ("(S) 3rd Reading Failed", P),  # 22
    ("(H) 3rd Reading Failed", P),  # 20
    ("(H) 3rd Reading Conference Committee Report Adopted", P),  # 20
    ("(S) 3rd Reading Conference Committee Report Adopted", P),  # 19
    ("(H) 3rd Reading Free Conference Committee Report Adopted", P),  # 9
    ("(S) 3rd Reading Free Conference Committee Report Adopted", P),  # 8
    ("(S) 3rd Reading Not Passed as Amended by House", P),  # 2
    ("(S) 3rd Reading Failed; 2nd House Vote Required", P),  # 1
    ("(H) 3rd Reading Not Passed as Amended by Senate", P),  # 1
    (
        "(H) 3rd Reading Conference Committee Report Rejected",
        P,
    ),  # 1 (a lost adoption vote)
    ("(S) 3rd Reading Conference Committee Report Rejected", P),  # 1
    ("(S) Resolution Adopted", P),  # 70
    ("(H) Resolution Adopted", P),  # 8
    ("(H) Veto Override Failed in Legislature", P),  # 14 (whole-bill veto override)
    ("(H) Veto Overridden by Legislature", P),  # 4
    ("(H) Committee Executive Action--Bill Passed", C),  # 465
    ("(S) Committee Executive Action--Bill Concurred", C),  # 466
    ("(H) Committee Executive Action--Bill Passed as Amended", C),  # 379
    ("(S) Committee Executive Action--Bill Concurred as Amended", C),  # 194
    ("(S) Committee Executive Action--Resolution Adopted", C),  # 63
    ("(S) Committee Executive Action--Resolution Adopted as Amended", C),  # 8
    ("(S) Committee Executive Action--Bill Not Passed", C),  # 1
    ("(H) 2nd Reading Passed", N),  # 686
    ("(S) 2nd Reading Concurred", N),  # 513
    ("(H) 2nd Reading Senate Amendments Concurred", N),  # 165
    ("(S) 2nd Reading House Amendments Concurred", N),  # 94
    ("(H) 2nd Reading Conference Committee Report Adopted", N),  # 20
    ("(H) 2nd Reading Not Passed", N),  # 36
    ("(S) 2nd Reading Pass Motion Failed; 3rd Reading Vote Required", N),  # 1
    ("(H) 3rd Reading Governor's Proposed Amendments Adopted", N),  # 8
    ("(S) 2nd Reading Governor's Proposed Amendments Adopted", N),  # 5
    ("(H) Tabled in Committee", N),  # 373
    ("(S) Taken from Table in Committee", N),  # 20
    ("(S) 2nd Reading Indefinitely Postponed", N),  # 56
    ("(S) Motion Failed", N),  # 30
    ("(H) Motion Carried", N),  # 17
    ("(S) Reconsidered Previous Action; Remains in 3rd Reading Process", N),  # 6
    ("(S) On Motion Rules Suspended", N),  # 4
    ("(S) Conference Committee Report Received", N),  # 20
    ("(S) 2nd Reading Motion to Amend Carried", A),  # 97
    ("(H) 2nd Reading Motion to Amend Failed", A),  # 57
]


@pytest.mark.parametrize("bill_action,expected", REAL_ARCHIVE)
def test_real_archive_texts(bill_action, expected):
    assert vote_classification(bill_action) == expected


@pytest.mark.parametrize(
    "text",
    [
        "(H) 2nd Reading: Do Pass",  # the motion alone never decides
        "Do Pass",
        "do_pass",  # a committee key without its ": " join
        "(H) Line-item Veto Override Failed",  # a 2023 archive action (no tally there): a line-item override is not passage
        "(S) 2nd Reading: Do Adopt Something",
        "",
    ],
)
def test_shared_rules_never_give_passage_for_these(text):
    assert classify_motion("mt", text) == []


class _Names(dict):
    def __missing__(self, key):
        return "member %s" % key


class _Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def _scrape(slug):
    scraper = MTBillScraper.__new__(MTBillScraper)
    scraper.info = lambda *a, **k: None
    scraper.warning = lambda *a, **k: None
    scraper.legislators_by_id = _Names()
    # what scrape_actions() fills from the bill's search row before the votes are read
    scraper.actions_by_id = {}
    with open(os.path.join(FIXTURES, "%s-bill.json" % slug)) as f:
        for action in json.load(f)["draft"]["billStatuses"]:
            scraper.actions_by_id[str(action["id"])] = action["billStatusCode"]["name"]

    def get(url):
        kind = "floor" if "/bills/v1/votes/" in url else "cmte"
        with open(os.path.join(FIXTURES, "%s-%s.json" % (slug, kind))) as f:
            return _Resp(json.load(f))

    scraper.get = get
    bill = Bill(slug, legislative_session="2025", chamber="lower", title="t")
    bill.add_source("https://bills.legmt.gov/")
    votes = list(scraper.scrape_votes(bill, "1")) + list(
        scraper.scrape_committee_votes(bill, "1")
    )
    return [
        (v.bill_action, v.motion_text, v.motion_classification, v.result) for v in votes
    ]


# The scraper's output for each fixture bill: floor roll calls in the API's order, then committee ones.
REAL_BILLS = {
    # free conference committee report: its third readings are passage, its second readings are not
    "SB40": [
        ("(S) 2nd Reading", "Do Pass", N, "pass"),
        ("(S) 3rd Reading", "Do Pass", P, "pass"),
        ("(H) 2nd Reading", "Do Concur", N, "pass"),
        ("(H) 3rd Reading", "Do Concur", P, "pass"),
        ("(S) 2nd Reading House Amendments", "Do Not Concur", N, "pass"),
        ("(S) 2nd Reading Free Conference Committee Report", "Do Adopt", N, "pass"),
        ("(H) 2nd Reading Free Conference Committee Report", "Do Adopt", N, "pass"),
        ("(H) 3rd Reading Free Conference Committee Report", "Do Adopt", P, "pass"),
        ("(S) 3rd Reading Free Conference Committee Report", "Do Adopt", P, "pass"),
        ("(S) Committee Executive Action", "do_pass_as_amended", C, "pass"),
        ("(H) Committee Executive Action", "be_concurred_in_as_amended", C, "pass"),
    ],
    # the governor's amendments, voted on second and third reading in both chambers: not passage
    "HB228": [
        ("(H) 2nd Reading", "Do Pass", N, "pass"),
        ("(H) 3rd Reading", "Do Pass", P, "pass"),
        ("(S) 2nd Reading", "Do Concur", N, "pass"),
        ("(S) 3rd Reading", "Do Concur", P, "pass"),
        ("(S) 2nd Reading Governor's Amendments", "Do Concur", N, "pass"),
        ("(H) 2nd Reading Governor's Amendments", "Do Concur", N, "pass"),
        ("(H) 3rd Reading Governor's Amendments", "Do Concur", N, "pass"),
        ("(S) 3rd Reading Governor's Amendments", "Do Concur", N, "pass"),
        ("(H) Committee Executive Action", "do_pass", C, "pass"),
        ("(S) Committee Executive Action", "be_concurred_in", C, "pass"),
    ],
    # a Senate resolution: adopted on second reading, its only floor vote
    "SR33": [
        ("(S) 2nd Reading", "Do Adopt", P, "pass"),
        ("(S) Committee Executive Action", "resolution_adopted", C, "pass"),
    ],
    # a floor amendment, and a lost committee vote (still a committee vote on the bill)
    "SB307": [
        (
            "(S) 2nd Reading Motion to Amend",
            "AMD-SB0307.002.005 McGillvray D/PASS",
            A,
            "pass",
        ),
        ("(S) 2nd Reading", "Do Pass As Amended", N, "pass"),
        ("(S) Committee Executive Action", "do_pass_as_amended", C, "pass"),
        ("(S) Committee Executive Action", "do_pass", C, "fail"),
    ],
    # a lost third reading whose motion the API leaves null
    "HB639": [
        ("(H) 2nd Reading", "Do Pass", N, "pass"),
        ("(H) 3rd Reading", "Unknown", P, "fail"),
        ("(H) Committee Executive Action", "do_pass", C, "pass"),
    ],
    # the House refuses the Senate's amendments
    "HB451": [
        ("(H) 2nd Reading", "Do Pass", N, "pass"),
        ("(H) 3rd Reading", "Do Pass", P, "pass"),
        (
            "(S) 2nd Reading Motion to Amend",
            "AMD-HB0451.001.003 Hertz D/PASS",
            A,
            "pass",
        ),
        ("(S) 2nd Reading", "Do Concur As Amended", N, "pass"),
        ("(S) 3rd Reading", "Do Concur", P, "pass"),
        ("(H) 2nd Reading Senate Amendments", "Do Not Concur", N, "pass"),
        ("(H) Committee Executive Action", "do_pass", C, "pass"),
        ("(S) Committee Executive Action", "be_concurred_in", C, "pass"),
    ],
    "HB316": [
        ("(H) 2nd Reading", "Do Pass", N, "pass"),
        ("(H) 3rd Reading", "Do Pass", P, "pass"),
        ("(S) 2nd Reading", "Do Concur", N, "pass"),
        ("(S) 3rd Reading; 2nd Chamber Vote Required", "Do Concur", P, "pass"),
        ("(H) Committee Executive Action", "do_pass", C, "pass"),
        ("(S) Committee Executive Action", "be_concurred_in", C, "pass"),
    ],
    # killed on the Senate floor: the lost second reading and the indefinite postponement are not passage
    "SB285": [
        ("(S) 2nd Reading", "Do Pass", N, "fail"),
        (
            "(S) 2nd Reading Indefinitely Postponed",
            "Indefinitely Postpone -McGillvray",
            N,
            "pass",
        ),
        ("(S) Committee Executive Action", "do_pass_as_amended", C, "pass"),
    ],
}


@pytest.mark.parametrize("slug", sorted(REAL_BILLS))
def test_real_bills_through_the_scraper(slug):
    assert _scrape(slug) == REAL_BILLS[slug]


def test_fixtures_cover_both_chambers_and_thirty_roll_calls():
    rows = [row for slug in REAL_BILLS for row in REAL_BILLS[slug]]
    assert len(rows) >= 30
    passage = [row[0] for row in rows if row[2] == P]
    assert any(a.startswith("(H)") for a in passage)
    assert any(a.startswith("(S)") for a in passage)


def test_real_archive_bill_through_the_scraper():
    # 2023 HB 95 as the archive API returns it (archive/v1/bills/search, sessionId 20231, read 2026-11-20)
    with open(os.path.join(FIXTURES, "archive-2023-HB95.json")) as f:
        row = json.load(f)
    scraper = MTBillScraper.__new__(MTBillScraper)
    bill = Bill("HB 95", legislative_session="2023", chamber="lower", title="t")
    bill.add_source("https://bills.legmt.gov/")
    votes = [
        (v.motion_text, v.motion_classification, v.result)
        for v in scraper.scrape_archive_actions(bill, row)
    ]
    assert votes == [
        ("(H) 3rd Reading Passed as Amended by Senate", P, "pass"),
        ("(H) 2nd Reading Senate Amendments Concurred", N, "pass"),
        ("(S) 3rd Reading Concurred", P, "pass"),
        ("(S) 2nd Reading Concurred as Amended", N, "pass"),
        ("(S) 2nd Reading Motion to Amend Carried", A, "pass"),
        ("(S) Committee Executive Action--Bill Concurred as Amended", C, "pass"),
        ("(H) 3rd Reading Passed", P, "pass"),
        ("(H) 2nd Reading Passed", N, "pass"),
        ("(H) Committee Executive Action--Bill Passed as Amended", C, "pass"),
    ]
