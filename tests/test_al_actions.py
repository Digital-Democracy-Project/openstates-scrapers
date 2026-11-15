"""OPEN-566: Alabama action tags.

Every line below is a real Alabama 2026RS history text stored on the Mac replica (2026-11-15).
The amdSub values and the billModal replies of SR 99 and HB 2 are ALISON's own, saved in
tests/fixtures/al_2026rs/ (see test_al_votes.py). No test makes a live call.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from al import Alabama  # noqa: E402
from al.bills import ALBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "al_2026rs")


def make_scraper():
    scraper = ALBillScraper(Alabama(), "/tmp/")

    def fake_post(url, headers=None, json=None, **kwargs):
        name = f"modal_{json['variables']['instrumentNbr']}.json"
        with open(os.path.join(FIXTURES, name), "rb") as f:
            return mock.Mock(content=f.read())

    scraper.post = fake_post
    return scraper


def tags(matter, resolution, amd_sub=None):
    row = {"matter": matter, "amdSub": amd_sub}
    return sorted(make_scraper().classify_action(row, resolution))


def scraped_actions(bill_id, chamber, classification):
    bill = Bill(
        bill_id, "2026rs", "A title", chamber=chamber, classification=classification
    )
    bill_row = {"instrumentNbr": bill_id, "sessionAbbreviation": "2026RS"}
    bill_row.update(prefiledDate=None, body="House")
    make_scraper().scrape_rest(bill, bill_row)
    return [(a["description"], a["classification"]) for a in bill.actions]


@pytest.mark.parametrize(
    "bill_id,matter",
    [
        ("HJR 89", "Lovvorn motion to Adopt - Adopted Voice Vote"),
        ("HJR 89", "Gudger motion to Adopt - Adopted Voice Vote"),
        ("SJR 10", "Motion to Adopt - Adopted Voice Vote"),
        ("SJR 100", "Waggoner motion to Adopt - Adopted Voice Vote"),
        ("SR 99", "Waggoner motion to Adopt - Adopted Roll Call 976"),
    ],
)
def test_resolution_adoption_is_passage(bill_id, matter):
    assert tags(matter, resolution=True) == ["passage"]


def test_adoption_naming_an_amendment_stays_an_amendment():
    # HB 2 roll call 535 adopts the committee substitute XDPUG7Z-1; on a resolution too, a
    # "Motion to Adopt" with an amdSub adopts that amendment, not the resolution
    matter = "Motion to Adopt - Adopted Roll Call 535"
    assert tags(matter, resolution=False, amd_sub="XDPUG7Z-1") == ["amendment-passage"]
    assert tags(matter, resolution=True, amd_sub="XDPUG7Z-1") == ["amendment-passage"]
    # a bill's adoption keeps today's tag
    assert tags(matter, resolution=False) == ["amendment-passage"]


@pytest.mark.parametrize(
    "matter",
    [
        "Elliott motion to Table - Adopted Voice Vote",  # HB 138
        "Garrett motion to Table - Adopted Roll Call 875",  # HB 238
    ],
)
def test_table_motion_is_not_an_amendment_adoption(matter):
    assert tags(matter, resolution=False) == []
    assert tags(matter, resolution=True) == []


@pytest.mark.parametrize(
    "matter",
    [
        # SB 303, which then died in the House
        "Motion to Read a Third Time and Pass - Lost Roll Call 1225",
        # HB 460, which passed later on reconsideration
        "Motion to Read a Third Time and Pass - Lost Roll Call 520",
    ],
)
def test_lost_third_reading_is_failure(matter):
    assert tags(matter, resolution=False) == ["failure"]


@pytest.mark.parametrize(
    "matter",
    [
        "Motion to Read a Third Time and Pass - Adopted Roll Call 1009",
        "Motion to Read a Third Time and Pass as Amended - Adopted Roll Call 536",
    ],
)
def test_adopted_third_reading_stays_passage(matter):
    assert tags(matter, resolution=False) == ["passage"]


def test_sr99_adoption_scraped_as_passage():
    # the saved billModal of SR 99: its adoption row has no amdSub
    assert scraped_actions("SR99", "upper", "resolution") == [
        ("Introduced", ["introduction"]),
        ("Waggoner motion to Adopt - Adopted Roll Call 976", ["passage"]),
    ]


def test_hb2_substitute_adoption_scraped_as_amendment():
    adopt = [
        cls
        for desc, cls in scraped_actions("HB2", "lower", "bill")
        if desc.startswith("Motion to Adopt")
    ]
    assert adopt == [["amendment-passage"]]
