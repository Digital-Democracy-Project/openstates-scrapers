"""Tests for OPEN-851: a Montana action keeps its status row's outcome ("(H) 3rd Reading Passed" / "Failed").

api.legmt.gov's status names carry no outcome; the row's `result` field does. The fixtures are the bills API's own
2025 rows (bills/v1/bills/search, sessionIds [2], read 2026-11-24): status-rows-2025.json holds one real row for each
(result, status name) pair of the session (98 pairs, 21 result values), and SB 158 and HB 500 (both lost on third
reading, HB 500 twice) with their floor and committee roll calls. OPEN-694's eight bills (mt_open694) are reused.
"""
import json
import os
import sys
from collections import defaultdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from mt.bills import MTBillScraper, OUTCOME_WORDS, action_outcome  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
STATUS_ROWS = json.load(
    open(os.path.join(FIXTURES, "mt_open851", "status-rows-2025.json"))
)
# (fixture folder, bill) with a real bill row and its roll calls
BILLS = [("mt_open851", b) for b in ("SB158", "HB500")] + [
    ("mt_open694", b)
    for b in ("HB228", "HB316", "HB451", "HB639", "SB285", "SB307", "SB40", "SR33")
]


def load(folder, name):
    return json.load(open(os.path.join(FIXTURES, folder, name)))


def bill_row(folder, bill):
    row = load(folder, f"{bill}-bill.json")
    return row["content"][0] if "content" in row else row


class OfflineScraper(MTBillScraper):
    """The scraper with its lookups filled from fixtures and its HTTP calls read from files."""

    def __init__(self, folder=None, bill=None):
        self.folder, self.bill = folder, bill
        self.actions_by_id = {}
        self.legislators_by_id = defaultdict(lambda: "member")
        self.standing_committees = [{"id": 5, "name": "(H) Judiciary"}]
        self.warnings = []

    def get(self, url):
        kind = "cmte" if "executiveActions" in url else "floor"
        data = load(self.folder, f"{self.bill}-{kind}.json")

        class Response:
            def json(_):
                return data

        return Response()

    def warning(self, message, *args):
        self.warnings.append(message)

    def info(self, *args):
        pass


def scraped_actions(row):
    bill = Bill("HB 1", legislative_session="2025", chamber="lower", title="t")
    OfflineScraper().scrape_actions(bill, row)
    return [(a["description"], a["classification"]) for a in bill.actions]


# Hand-written from the legislature's archive-API wording; each is a real 2025 status name with its result.
P, F, CP, CF = ["passage"], ["failure"], ["committee-passage"], ["committee-failure"]
CASES = [
    ("(H) 3rd Reading", "BILL_PASSED", "(H) 3rd Reading Passed", P),
    ("(S) 3rd Reading", "BILL_CONCURRED", "(S) 3rd Reading Concurred", P),
    ("(H) 3rd Reading", "BILL_NOT_PASSED", "(H) 3rd Reading Failed", F),
    ("(S) 3rd Reading", "BILL_NOT_PASSED", "(S) 3rd Reading Failed", F),
    (
        "(H) 3rd Reading Senate Amendments",
        "BILL_CONCURRED_AS_AMENDED",
        "(H) 3rd Reading Senate Amendments Concurred as Amended",
        P,
    ),
    # rejecting the other chamber's amendments sends the bill to conference; the bill is not lost
    (
        "(H) 3rd Reading Senate Amendments",
        "BILL_NOT_CONCURRED_AS_AMENDED",
        "(H) 3rd Reading Senate Amendments Not Concurred as Amended",
        [],
    ),
    (
        "(S) 3rd Reading Conference Committee Report",
        "REPORT_ADOPTED",
        "(S) 3rd Reading Conference Committee Report Adopted",
        P,
    ),
    (
        "(S) 3rd Reading Conference Committee Report",
        "REPORT_REJECTED",
        "(S) 3rd Reading Conference Committee Report Rejected",
        [],
    ),
    # the governor's amendments are not passage (OPEN-694)
    (
        "(H) 3rd Reading Governor's Amendments",
        "BILL_CONCURRED_AS_AMENDED",
        "(H) 3rd Reading Governor's Amendments Concurred as Amended",
        [],
    ),
    # second reading is not passage, and losing it is not yet the bill's loss
    ("(H) 2nd Reading", "BILL_PASSED", "(H) 2nd Reading Passed", []),
    ("(H) 2nd Reading", "BILL_NOT_PASSED", "(H) 2nd Reading Not Passed", []),
    ("(S) 2nd Reading", "BILL_NOT_CONCURRED", "(S) 2nd Reading Not Concurred", []),
    # a simple resolution is adopted on second reading
    ("(S) 2nd Reading", "RESOLUTION_ADOPTED", "(S) 2nd Reading Adopted", P),
    ("(S) 2nd Reading", "RESOLUTION_FAILED", "(S) 2nd Reading Not Adopted", F),
    (
        "(H) Committee Executive Action",
        "BILL_PASSED_AS_AMENDED",
        "(H) Committee Executive Action--Bill Passed as Amended",
        CP,
    ),
    (
        "(S) Committee Executive Action",
        "BILL_NOT_PASSED",
        "(S) Committee Executive Action--Bill Not Passed",
        CF,
    ),
    (
        "(S) Committee Executive Action",
        "BILL_NOT_CONCURRED",
        "(S) Committee Executive Action--Bill Not Concurred",
        CF,
    ),
    (
        "(S) Committee Executive Action",
        "RESOLUTION_ADOPTED",
        "(S) Committee Executive Action--Resolution Adopted",
        CP,
    ),
    ("(H) Committee Report", "BILL_PASSED", "(H) Committee Report--Bill Passed", CP),
    # the API files a report's "concurred in as amended" as BILL_NOT_CONCURRED_AS_AMENDED
    (
        "(S) Committee Report",
        "BILL_NOT_CONCURRED_AS_AMENDED",
        "(S) Committee Report--Bill Concurred as Amended",
        CP,
    ),
    (
        "(S) Committee Report",
        "RESOLUTION_FAILED",
        "(S) Committee Report--Resolution Not Adopted",
        CF,
    ),
    (
        "(H) Veto Override",
        "VETO_OVERRIDDEN",
        "(H) Veto Override Passed",
        ["veto-override-passage"],
    ),
    (
        "(S) Veto Override",
        "VETO_NOT_OVERRIDDEN",
        "(S) Veto Override Failed",
        ["veto-override-failure"],
    ),
    (
        "(H) 2nd Reading Motion to Amend",
        "MOTION_FAILED",
        "(H) 2nd Reading Motion to Amend Failed",
        [],
    ),
    ("(S) Motion", "MOTION_CARRIED", "(S) Motion Carried", []),
    (
        "(H) Reconsidered Previous Action",
        "REVOTE_ON_PREVIOUS_ACTION",
        "(H) Reconsidered Previous Action Carried",
        [],
    ),
    ("(H) Tabled in Committee", "BILL_TABLED", "(H) Tabled in Committee", []),
    ("(H) Introduced", None, "(H) Introduced", []),
]


@pytest.mark.parametrize("name,result,text,labels", CASES)
def test_outcome_words_and_labels(name, result, text, labels):
    words, outcome_labels = action_outcome(name, result, committee_passed=True)
    assert name + words == text
    assert outcome_labels == labels


def test_report_not_concurred_kept_without_a_passing_executive_action():
    assert action_outcome("(S) Committee Report", "BILL_NOT_CONCURRED_AS_AMENDED") == (
        "--Bill Not Concurred as Amended",
        ["committee-failure"],
    )


def test_report_follows_its_own_committee_in_scrape_actions():
    # SB 40: the House committee concurred as amended, and its report is filed BILL_NOT_CONCURRED_AS_AMENDED
    actions = [d for d, _ in scraped_actions(bill_row("mt_open694", "SB40"))]
    assert "(H) Committee Report--Bill Concurred as Amended" in actions
    row = json.loads(json.dumps(bill_row("mt_open694", "SB40")))
    for status in row["draft"]["billStatuses"]:
        if status["billStatusCode"]["name"] == "(H) Committee Executive Action":
            status["result"] = "BILL_NOT_CONCURRED"
    actions = [d for d, _ in scraped_actions(row)]
    assert "(H) Committee Report--Bill Not Concurred as Amended" in actions
    # a later executive action of the same committee without a result does not count as passing
    row = json.loads(json.dumps(bill_row("mt_open694", "SB40")))
    statuses = row["draft"]["billStatuses"]
    i = next(
        n
        for n, s in enumerate(statuses)
        if s["billStatusCode"]["name"] == "(H) Committee Report"
    )
    statuses.insert(i, dict(statuses[i - 1], result=None))
    assert statuses[i]["billStatusCode"]["name"] == "(H) Committee Executive Action"
    actions = [d for d, _ in scraped_actions(row)]
    assert "(H) Committee Report--Bill Not Concurred as Amended" in actions


def test_every_2025_pair_is_a_real_row_and_covered():
    # 21 result values over 98 (result, status name) pairs, every value in the word table
    assert len(STATUS_ROWS) == 98
    assert {r["status"]["result"] for r in STATUS_ROWS} == set(OUTCOME_WORDS)
    for r in STATUS_ROWS:
        status = r["status"]
        words, _ = action_outcome(status["billStatusCode"]["name"], status["result"])
        # only a tabling and a removal from the table say it in the name already
        assert words or status["result"] in ("BILL_TABLED", "BILL_REMOVED_FROM_TABLE")


def test_unknown_result_keeps_its_own_words():
    assert action_outcome("(H) 3rd Reading", "BILL_SOMETHING_NEW") == (
        " Bill Something New",
        [],
    )
    assert action_outcome("(H) Committee Report", "BILL_SOMETHING_NEW") == (
        "--Bill Something New",
        [],
    )


def test_scrape_actions_text_and_labels_on_real_rows():
    actions = scraped_actions(bill_row("mt_open694", "HB639"))
    assert ("(H) 3rd Reading Failed", ["failure"]) in actions
    assert ("(H) 2nd Reading Passed", ["reading-2"]) in actions
    # committee rows: the outcome, then the committee
    assert (
        "(H) Committee Executive Action--Bill Passed - (H) Judiciary",
        ["committee-passage"],
    ) in [(d, c) for d, c in actions if "(H) Judiciary" in d]
    # rows without a result are unchanged
    assert ("(H) Introduced", []) in actions

    passed = scraped_actions(bill_row("mt_open694", "HB228"))
    assert ("(H) 3rd Reading Passed", ["passage"]) in passed
    assert ("(S) 3rd Reading Concurred", ["passage"]) in passed


def test_scrape_actions_warns_on_unknown_result():
    row = json.loads(json.dumps(bill_row("mt_open851", "SB158")))
    row["draft"]["billStatuses"][-1]["result"] = "BILL_SOMETHING_NEW"
    scraper = OfflineScraper()
    bill = Bill("SB 158", legislative_session="2025", chamber="upper", title="t")
    scraper.scrape_actions(bill, row)
    assert scraper.warnings and "BILL_SOMETHING_NEW" in scraper.warnings[0]
    assert bill.actions[-1]["description"].endswith(" Bill Something New")


def test_actions_by_id_keeps_the_bare_name_for_vote_rules():
    # OPEN-694's vote rules read the bill action's status name; the outcome words must not reach them
    scraper = OfflineScraper()
    bill = Bill("HB 639", legislative_session="2025", chamber="lower", title="t")
    row = bill_row("mt_open694", "HB639")
    scraper.scrape_actions(bill, row)
    assert set(scraper.actions_by_id.values()) == {
        s["billStatusCode"]["name"] for s in row["draft"]["billStatuses"]
    }


@pytest.mark.parametrize("folder,bill", BILLS)
def test_outcome_agrees_with_the_roll_call(folder, bill):
    """Every status row with a roll call: the outcome the action states agrees with the vote's own tally
    (the scraper's result, yes > no), which is read from a different endpoint."""
    row = bill_row(folder, bill)
    scraper = OfflineScraper(folder, bill)
    b = Bill(bill, legislative_session="2025", chamber="lower", title="t")
    b.add_source("https://bills.legmt.gov/")
    scraper.scrape_actions(b, row)
    floor = {
        v.dedupe_key.rsplit("#", 1)[1]: v
        for v in scraper.scrape_votes(b, str(row["id"]))
    }
    cmte = {
        v.dedupe_key.rsplit("#", 1)[1]: v
        for v in scraper.scrape_committee_votes(b, str(row["id"]))
    }
    checked = 0
    for status, action in zip(row["draft"]["billStatuses"], b.actions):
        vote = None
        if status["vote"]:
            vote = floor.get(str(status["vote"]["id"]))
        elif status["executiveActionId"]:
            vote = cmte.get(str(status["executiveActionId"]))
        if vote is None or not status["result"]:
            continue
        # a carried "Do Not Concur" (the other chamber's amendments) is a "Not Concurred" outcome
        yes, no = (
            ("fail", "pass")
            if vote.motion_text.startswith("Do Not")
            else ("pass", "fail")
        )
        labels = set(action["classification"])
        if labels & {"passage", "committee-passage", "veto-override-passage"}:
            assert vote.result == yes, action["description"]
        if labels & {"failure", "committee-failure", "veto-override-failure"}:
            assert vote.result == no, action["description"]
        # the words after the status name
        words = action["description"].split(" - (")[0][
            len(status["billStatusCode"]["name"]) :
        ]
        if any(w in words for w in (" Failed", " Not ", " Rejected")):
            assert vote.result == no, action["description"]
        elif words:
            assert vote.result == yes, action["description"]
        checked += 1
    assert checked


def test_failed_third_readings_are_failures():
    for bill, expected in (("SB158", 1), ("HB500", 2)):
        actions = scraped_actions(bill_row("mt_open851", bill))
        failed = [d for d, c in actions if "failure" in c and "3rd Reading" in d]
        assert len(failed) == expected and all(
            d.endswith("3rd Reading Failed") for d in failed
        )
        assert not [d for d, c in actions if "passage" in c and "3rd Reading" in d]
