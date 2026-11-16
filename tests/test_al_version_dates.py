"""OPEN-569: Alabama versions carry the date of the action that carries their file, and an
amendment or substitute paper is a version only if it became part of the bill.

modal_HB315.json and modal_SB146.json are ALISON's own billModal replies (2026RS), saved 2026-11-16; the other
history texts below are real Alabama 2026RS rows stored on the Mac replica. No test makes a live
call.
"""
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from al import Alabama  # noqa: E402
from al.bills import ALBillScraper, paper_is_version, version_dates  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from openstates.utils.version_ordering import version_sort_key  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "al_2026rs")
TILLMAN = "Tillman 1st Substitute Offered"
SENATE_COMMITTEE = "Jefferson County Legislation 1st Substitute"


def scraped(nbr="HB315"):
    with open(os.path.join(FIXTURES, f"modal_{nbr}.json"), "rb") as f:
        reply = f.read()
    scraper = ALBillScraper(Alabama(), "/tmp/")
    scraper.post = lambda url, headers=None, json=None, **kw: mock.Mock(content=reply)
    bill = Bill(nbr, "2026rs", "A title", chamber="lower", classification="bill")
    # the list row carries the same file addresses as the billModal's instrument
    row = dict(json.loads(reply)["data"]["instrument"])
    row.update(sessionAbbreviation="2026RS", prefiledDate=None, body="House")
    histories = scraper.scrape_rest(bill, row)
    scraper.scrape_versions(bill, row, histories)
    return bill


def by_note(items):
    return {item["note"]: item for item in items}


def test_hb315_versions_and_dates():
    bill = scraped()
    versions = {v["note"]: v["date"] for v in bill.versions}
    assert versions == {
        "Introduced": "2026-01-22",  # no prefiled date: the first reading
        TILLMAN: "2026-03-17",
        "Engrossed": "2026-03-17",
        SENATE_COMMITTEE: "2026-04-02",
        "Coleman 1st Amendment Offered": "2026-04-07",  # adopted, roll call 1160
        "Enrolled": "2026-04-08",
    }
    tillman = by_note(bill.versions)[TILLMAN]
    assert [link["url"].rsplit("/", 1)[1] for link in tillman["links"]] == [
        "2J5XRIS-1.pdf"
    ]


def test_hb315_tabled_committee_substitute_is_a_document():
    # CXUMVJW-1 was reported out of the House committee (2026-03-12), offered on the floor as the
    # "Engrossed Substitute" and tabled (Moore (M) motion to Table - Adopted Voice Vote)
    bill = scraped()
    paper = by_note(bill.documents)["Reported Out of Committee House of Origin"]
    assert paper["date"] == "2026-03-12"
    assert paper["links"][0]["url"].endswith("/CXUMVJW-1.pdf")
    urls = [link["url"] for v in bill.versions for link in v["links"]]
    assert not any(u.endswith("/CXUMVJW-1.pdf") for u in urls)


def test_hb315_tillman_orders_before_engrossed():
    # same day: openstates-core's stage rank puts the substitute before the engrossed bill
    versions = by_note(scraped().versions)
    assert version_sort_key(TILLMAN, versions[TILLMAN]["date"]) < version_sort_key(
        "Engrossed", versions["Engrossed"]["date"]
    )


def test_sb146_adoption_row_without_the_paper_still_adopts_it():
    # "Finance and Taxation General Fund 1st Substitute Offered" (XDPAW7E-1) is followed by
    # "Albritton motion to adopt- Adopted Roll Call 813", which names no paper
    versions = {v["note"]: v for v in scraped("SB146").versions}
    sub = versions["Finance and Taxation General Fund 1st Substitute"]
    assert sub["date"] == "2026-03-10"
    assert sub["links"][0]["url"].endswith("/XDPAW7E-1.pdf")
    documents = scraped("SB146").documents
    assert not [d for d in documents if d["links"][0]["url"].endswith("/XDPAW7E-1.pdf")]


def rows(*matters):
    return [{"matter": m} for m in matters]


@pytest.mark.parametrize(
    "matters",
    [
        # HB 315: offered, then adopted
        (TILLMAN, "Motion to Adopt - Adopted Roll Call 895"),
        # HB 315: reported by the Senate committee, offered, adopted by a named member's motion
        (
            SENATE_COMMITTEE,
            "Jefferson County Legislation 1st Substitute Offered",
            "Chambliss motion to Adopt - Adopted Roll Call 1159",
        ),
        # a committee report never taken to the floor: the bill as the committee reported it
        ("Reported Out of Committee Second House",),
        # SB 361: a failed motion to table, then adopted
        (
            "Brinyark 1st Amendment Offered",
            "Ensler motion to Table - Lost Roll Call 1269",
            "Motion to Adopt - Adopted Roll Call 1270",
        ),
    ],
)
def test_paper_is_version(matters):
    assert paper_is_version(rows(*matters))


@pytest.mark.parametrize(
    "matters",
    [
        # HB 315: reported out of committee, then tabled on the floor
        (
            "Reported Out of Committee House of Origin",
            "Jefferson County Legislation  Engrossed Substitute Offered",
            "Moore (M) motion to Table - Adopted Voice Vote",
        ),
        # HB 95: the adoption failed
        ("McCampbell 1st Amendment Offered", "Motion to Adopt - Lost Roll Call 3"),
        # SB 361: a failed motion to table, then a second one adopted
        (
            "Fidler 1st Amendment Offered",
            "Ensler motion to Table - Lost Roll Call 1277",
            "Ellis motion to Table - Adopted Roll Call 1278",
        ),
        # offered and never voted on (withdrawn, or still pending): not a real row, the rule's edge
        ("Fidler 1st Amendment Offered",),
    ],
)
def test_paper_not_adopted_is_not_a_version(matters):
    assert not paper_is_version(rows(*matters))


def history(date, matter):
    return {"calendarDate": f"{date}T00:00:00", "matter": matter}


def test_dates_from_prefiled_engrossed_and_enrolled_rows():
    histories = [
        history(
            "2026-01-13", "Read for the first time and referred to the House Committee"
        ),
        history(
            "2026-01-20", "Motion to Read a Third Time and Pass - Adopted Roll Call 39"
        ),
        history("2026-01-21", "Engrossed"),
        history("2026-02-03", "Enrolled"),
        history("2026-02-05", "Enrolled"),
    ]
    assert version_dates({"prefiledDate": "2025-12-17T00:00:00"}, histories) == {
        "Introduced": "2025-12-17",
        "Engrossed": "2026-01-21",
        "Enrolled": "2026-02-03",
    }


def test_dates_fall_back_to_passage_and_ready_to_enroll():
    # the shape of HB 84 and HB 140 (2026RS), which have no "Engrossed" or "Enrolled" history row
    histories = [
        history(
            "2026-01-13", "Read for the first time and referred to the House Committee"
        ),
        history(
            "2026-01-20",
            "Motion to Read a Third Time and Pass as Amended - Lost Roll Call 63",
        ),
        history(
            "2026-01-21",
            "Motion to Read a Third Time and Pass as Amended - Adopted Roll Call 64",
        ),
        history(
            "2026-01-22", "Motion to Read a Third Time and Pass - Adopted Roll Call 96"
        ),
        history("2026-01-22", "Ready to Enroll"),
        history("2026-01-27", "Ready to Enroll"),
    ]
    assert version_dates({"prefiledDate": None}, histories) == {
        "Introduced": "2026-01-13",
        "Engrossed": "2026-01-21",
        "Enrolled": "2026-01-27",
    }


def test_no_history_no_dates():
    assert version_dates({}, []) == {"Introduced": "", "Engrossed": "", "Enrolled": ""}
