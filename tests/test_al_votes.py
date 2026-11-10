"""OPEN-524: Alabama roll-call votes from ALISON's current GraphQL API.

Every response under tests/fixtures/al_2026rs/ is a real ALISON reply saved on 2026-11-10
(HB2 of the 2026 Regular Session, the "Gulf of America Act"): the bill list (trimmed to the
HB2 row), its billModal (actions, budget isolation resolutions) and the six rollCallVotes
replies for its six roll calls; and HB1's billModal and four roll calls (one with abstains).
No test makes a live call.
"""
import json
import os
import sys
from collections import Counter
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from al import Alabama  # noqa: E402
from al import bills as al_bills  # noqa: E402
from al.bills import ALBillScraper  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "al_2026rs")


def load(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def make_scraper():
    scraper = ALBillScraper(Alabama(), "/tmp/")
    scraper.vote_keys = set()
    scraper.bill_ids = set()
    scraper.count = 0
    scraper.session_identifier = "2026rs"
    scraper.posted = []

    def fake_post(url, headers=None, json=None, **kwargs):
        assert url == "https://alison.legislature.state.al.us/graphql"
        v = json["variables"]
        if "rollCallNbr" in v:
            # the query the ALISON site's roll-call window sends, with the fields read here
            query = " ".join(json["query"].split())
            assert "rollCallVotes( sessionAbbreviation: $sessionAbbreviation" in query
            for field in ("yeas", "nays", "abstains", "passes", "memberName", "vote"):
                assert f" {field} " in query
            scraper.posted.append((v["body"], v["rollCallNbr"]))
            name = f"rc_{v['sessionAbbreviation']}_{v['body']}_{v['rollCallNbr']}.json"
        else:
            name = f"modal_{v['instrumentNbr']}.json"
        return mock.Mock(content=load(name))

    scraper.post = fake_post
    return scraper


def make_bill(identifier="HB2"):
    return Bill(identifier, "2026rs", "A title", chamber="lower", classification="bill")


def histories(identifier):
    return json.loads(load(f"modal_{identifier}.json"))["data"]["histories"]["data"]


def hb2_histories():
    return histories("HB2")


def by_roll_call(votes):
    return {v.dedupe_key.split("#")[2]: v for v in votes}


def chamber(vote):
    # VoteEvent keeps the chamber as a pseudo-id of its organization
    return json.loads(vote.organization[1:])["classification"]


def counts(vote):
    return {c["option"]: c["value"] for c in vote.counts}


def test_roll_call_matches_alison():
    scraper = make_scraper()
    votes = list(scraper.scrape_votes(make_bill(), hb2_histories()))
    assert len(votes) == 6
    vote = by_roll_call(votes)["1009"]
    # ALISON: Senate roll call 1009 on HB2, 2026-03-31, 26 yeas, 5 nays, 4 passes
    assert vote.motion_text == (
        "Motion to Read a Third Time and Pass - Adopted Roll Call 1009"
    )
    assert vote.start_date == "2026-03-31"
    assert chamber(vote) == "upper"
    assert vote.result == "pass"
    assert vote.dedupe_key == "2026RS#Senate#1009#HB2"
    assert counts(vote) == {"yes": 26, "no": 5, "abstain": 0, "not voting": 4}
    # the counts equal the member rows, and "P" (pass) is not voting
    assert Counter(r["option"] for r in vote.votes) == Counter(
        {"yes": 26, "no": 5, "not voting": 4}
    )
    assert {"option": "not voting", "voter_name": "Sam Givhan"} in [
        {"option": r["option"], "voter_name": r["voter_name"]} for r in vote.votes
    ]


@pytest.mark.parametrize(
    "bill_id,roll_call,expected",
    [
        # as ALISON shows them: yeas, nays, abstains, passes
        ("HB2", "1009", {"yes": 26, "no": 5, "abstain": 0, "not voting": 4}),
        ("HB2", "1008", {"yes": 26, "no": 6, "abstain": 0, "not voting": 3}),
        ("HB2", "956", {"yes": 26, "no": 7, "abstain": 0, "not voting": 2}),
        ("HB1", "226", {"yes": 58, "no": 0, "abstain": 2, "not voting": 44}),
        ("HB1", "223", {"yes": 102, "no": 0, "abstain": 2, "not voting": 0}),
    ],
)
def test_named_roll_calls_counts_equal_member_rows(bill_id, roll_call, expected):
    scraper = make_scraper()
    votes = scraper.scrape_votes(make_bill(bill_id), histories(bill_id))
    vote = by_roll_call(votes)[roll_call]
    assert counts(vote) == expected
    rows = Counter(r["option"] for r in vote.votes)
    assert {k: rows.get(k, 0) for k in expected} == expected
    assert sum(rows.values()) == sum(expected.values())


def test_empty_roll_call_reply_does_not_block_a_later_duplicate():
    scraper = make_scraper()
    row = [r for r in hb2_histories() if r["rollCallNbr"] == 1009][0]
    good = scraper.post
    replies = iter([mock.Mock(content=b'{"data": {"rollCallVotes": null}}')])

    def first_empty(url, headers=None, json=None, **kwargs):
        reply = next(replies, None)
        return reply or good(url, headers=headers, json=json, **kwargs)

    scraper.post = first_empty
    with mock.patch.object(scraper, "warning"):
        votes = list(scraper.scrape_votes(make_bill(), [row, dict(row)]))
    assert len(votes) == 1


def test_counts_agree_with_bill_page_totals():
    # the yeas/nays printed beside each action on the bill page come from a different query
    # (billModal histories) than the roll call (rollCallVotes); they must agree
    scraper = make_scraper()
    votes = by_roll_call(scraper.scrape_votes(make_bill(), hb2_histories()))
    for row in hb2_histories():
        if row["rollCallNbr"]:
            c = counts(votes[str(row["rollCallNbr"])])
            assert (c["yes"], c["no"]) == (row["yeas"], row["nays"])
            assert (
                chamber(votes[str(row["rollCallNbr"])])
                == {
                    "House": "lower",
                    "Senate": "upper",
                }[row["body"]]
            )


def test_counts_are_alisons_totals_when_member_list_is_short():
    # House roll call 536 totals 74 yeas, but ALISON lists only 73 "Y" members
    scraper = make_scraper()
    with mock.patch.object(scraper, "warning") as warning:
        vote = by_roll_call(scraper.scrape_votes(make_bill(), hb2_histories()))["536"]
    assert counts(vote) == {"yes": 74, "no": 30, "abstain": 0, "not voting": 1}
    assert Counter(r["option"] for r in vote.votes)["yes"] == 73
    assert any("roll call 536" in str(c) for c in warning.call_args_list)


def test_voice_vote_yields_nothing_and_fetches_nothing():
    scraper = make_scraper()
    voice = [r for r in hb2_histories() if r["voteType"] == "V"]
    assert voice and voice[0]["matter"] == "Carried Over to the Call of the Chair"
    assert list(scraper.scrape_votes(make_bill(), voice)) == []
    assert scraper.posted == []


def test_duplicate_roll_call_yields_one_event():
    scraper = make_scraper()
    histories = hb2_histories()
    row = [r for r in histories if r["rollCallNbr"] == 1009][0]
    votes = list(scraper.scrape_votes(make_bill(), [row, dict(row)]))
    assert len(votes) == 1
    assert scraper.posted == [("Senate", 1009)]
    # and a second pass over the same bill (the scraper saw it twice) adds nothing
    assert list(scraper.scrape_votes(make_bill(), histories)) != []
    assert list(scraper.scrape_votes(make_bill(), histories)) == []
    assert len(scraper.posted) == 6


def test_budget_isolation_resolutions_add_no_second_vote():
    # HB2's BIRs reuse roll calls 534 and 956 of the history rows; only six roll calls exist
    scraper = make_scraper()
    birs = json.loads(load("modal_HB2.json"))["data"]["birs"]["data"]
    assert {b["voteTitle"] for b in birs} == {"R 534", "R 956"}
    keys = [v.dedupe_key for v in scraper.scrape_votes(make_bill(), hb2_histories())]
    assert sorted(keys) == sorted(
        f"2026RS#{b}#{n}#HB2"
        for b, n in [
            ("Senate", 1009),
            ("Senate", 1008),
            ("Senate", 956),
            ("House", 536),
            ("House", 535),
            ("House", 534),
        ]
    )


def test_bill_scrape_yields_votes_before_their_bill():
    scraper = make_scraper()
    pages = [
        mock.Mock(content=load("list_page0_B_HB2_only.json")),
        # the end of paging: an empty page, written here (not a saved response)
        mock.Mock(content=b'{"data": {"instruments": {"count": 0, "data": []}}}'),
    ]
    with mock.patch.object(al_bills.requests, "post", side_effect=pages):
        out = list(scraper.scrape_bill_type("2026rs", "B", 0, 50))
    kinds = [type(o) for o in out]
    assert kinds == [VoteEvent] * 6 + [Bill]
    assert all(v.bill == out[-1]._id for v in out[:-1])


# ---------------------------------------------------------------------------
# OPEN-527: motion classification (gate E). The rules are the al block of
# config/motion_classification.yaml; the scraper labels amendment adoptions itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bill_id,roll_call,expected",
    [
        ("HB2", "534", []),  # Third Reading in House of Origin: the BIR roll call
        ("HB2", "535", ["amendment"]),  # Motion to Adopt the committee substitute
        ("HB2", "536", ["passage"]),  # Read a Third Time and Pass as Amended
        ("HB2", "956", []),  # Third Reading in Second House: the BIR roll call
        ("HB2", "1008", []),  # Petition To Close Debate
        ("HB2", "1009", ["passage"]),  # Read a Third Time and Pass
        ("HB1", "223", []),
        ("HB1", "224", ["amendment"]),  # Motion to Adopt Tillman's 1st amendment
        ("HB1", "225", ["passage"]),
        ("HB1", "226", []),  # Motion to Add Cosponsor
    ],
)
def test_scraped_votes_are_classified(bill_id, roll_call, expected):
    scraper = make_scraper()
    votes = scraper.scrape_votes(make_bill(bill_id), histories(bill_id))
    assert by_roll_call(votes)[roll_call].motion_classification == expected


def saved_rows():
    # the roll-call history rows of four more bills, saved from ALISON's billModal on 2026-11-10
    return json.loads(load("rollcall_rows_SB57_HB95_SR96_HJR4.json"))


@pytest.mark.parametrize(
    "bill_id,roll_call,matter_start,expected",
    [
        # SB 57: amendments in both houses, a conference, both conference reports
        ("SB57", 694, "Orr motion to Adopt", ["amendment"]),
        ("SB57", 696, "Orr motion to Adopt", ["amendment"]),
        ("SB57", 697, "Motion to Read a Third Time and Pass as Amended", ["passage"]),
        ("SB57", 693, "Third Reading in House of Origin", []),
        ("SB57", 1282, "Motion to Adopt", ["amendment"]),  # an engrossed substitute
        ("SB57", 1285, "Motion to Read a Third Time and Pass as Amended", ["passage"]),
        ("SB57", 1262, "Gudger motion to Non-Concur", []),
        ("SB57", 1333, "In Conference Committee", []),
        ("SB57", 1333, "Lovvorn motion to Accede", []),
        ("SB57", 1310, "Gudger motion to Concur In and Adopt Conference", ["passage"]),
        ("SB57", 1355, "Ingram motion to Concur In and Adopt Conference", ["passage"]),
        # HB 95: a lost amendment is still an amendment vote; the governor's amendment
        ("HB95", 3, "Motion to Adopt - Lost", ["amendment"]),
        ("HB95", 999, "Petition To Close Debate", []),
        ("HB95", 1229, "Gudger Motion to Concur In and Adopt Executive", ["passage"]),
        # SR 96: a resolution's adoption has no amdSub, so it is passage
        ("SR96", 950, "Waggoner motion to Adopt", ["passage"]),
        ("HJR4", 147, "Gudger Concur In and Adopt", ["passage"]),
        ("HJR4", 159, "Reynolds Concur-In and Adopt Executive", ["passage"]),
    ],
)
def test_vote_classification_on_real_rows(bill_id, roll_call, matter_start, expected):
    rows = [
        r
        for r in saved_rows()[bill_id]
        if r["rollCallNbr"] == roll_call and r["matter"].startswith(matter_start)
    ]
    assert len(rows) == 1
    assert al_bills.vote_classification(rows[0]) == expected


def test_amendment_label_needs_the_amdsub():
    # the same "Motion to Adopt" text is an amendment with an amdSub and passage without one
    row = [r for r in saved_rows()["HB95"] if r["rollCallNbr"] == 2][0]
    assert row["amdSub"] and row["matter"].startswith("Motion to Adopt")
    assert al_bills.vote_classification(row) == ["amendment"]
    assert al_bills.vote_classification(dict(row, amdSub=None)) == ["passage"]
    # an amdSub on a row that is not an adoption motion does not make it an amendment vote
    tabled = dict(row, matter="Kiel motion to Table - Adopted Roll Call 559")
    assert al_bills.vote_classification(tabled) == []
