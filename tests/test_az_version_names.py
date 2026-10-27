"""Tests for AZ version names (OPEN-430): azleg's dated Engrossed names are stored undated.

scrape_versions_and_documents() makes one DocType request; the tests hand it a fake
response, so no real HTTP request is made.
"""
import json
import os
import sys
from unittest import mock

import pytest
from openstates.scrape import Bill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from az import Arizona  # noqa: E402
from az.bills import AZBillScraper, undated_version_name  # noqa: E402


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Senate Engrossed Version (02/26/2026)", "Senate Engrossed Version"),
        ("House Engrossed Version (06/02/2026)", "House Engrossed Version"),
        ("Conference Engrossed Version (5/9/2026)", "Conference Engrossed Version"),
        ("Senate Engrossed Version  (02/26/2026) ", "Senate Engrossed Version"),
        # already undated: unchanged
        ("Senate Engrossed Version", "Senate Engrossed Version"),
        ("Introduced Version", "Introduced Version"),
        # anything else, dated or not, is left exactly as azleg sends it
        ("Chaptered Version (02/26/2026)", "Chaptered Version (02/26/2026)"),
        (
            "HOUSE - Floor Amend to NREW - Griffin failed (543432)",
            "HOUSE - Floor Amend to NREW - Griffin failed (543432)",
        ),
        ("Senate Engrossed Version (draft 2)", "Senate Engrossed Version (draft 2)"),
        ("Strike Everything (02/26/2026)", "Strike Everything (02/26/2026)"),
    ],
)
def test_only_the_dated_engrossed_shape_is_rewritten(name, expected):
    assert undated_version_name(name) == expected


def doc(name, **links):
    return {"DocumentName": name, "HtmlPath": "", "PdfPath": links.get("pdf", "")}


def scrape_notes(groups):
    scraper = AZBillScraper(Arizona(), "/tmp/")
    response = mock.Mock()
    response.content = json.dumps(groups).encode("utf-8")
    scraper.get = mock.Mock(return_value=response)
    bill = Bill("HB 1", "57th-2nd-regular", "A bill", chamber="lower")
    scraper.scrape_versions_and_documents(bill, 123)
    return bill


def test_dated_engrossed_versions_are_stored_undated():
    bill = scrape_notes(
        [
            {
                "DocumentGroupName": "Bill Versions",
                "Documents": [
                    doc("Introduced Version", pdf="/a/intro.pdf"),
                    doc("Senate Engrossed Version (02/26/2026)", pdf="/a/senate.pdf"),
                    doc("House Engrossed Version (06/02/2026)", pdf="/a/house.pdf"),
                ],
            }
        ]
    )
    assert [v["note"] for v in bill.versions] == [
        "Introduced Version",
        "Senate Engrossed Version",
        "House Engrossed Version",
    ]


def test_documents_that_are_not_versions_keep_their_names():
    bill = scrape_notes(
        [
            {
                "DocumentGroupName": "Fiscal Notes",
                "Documents": [
                    doc("Senate Engrossed Version (02/26/2026)", pdf="/a/f.pdf")
                ],
            }
        ]
    )
    assert bill.versions == []
    assert [d["note"] for d in bill.documents] == [
        "Senate Engrossed Version (02/26/2026)"
    ]


def test_two_dated_copies_of_one_engrossed_version_stay_one_version_with_both_links():
    # same as the undated behaviour before OPEN-430: a repeated note is one version, two links
    bill = scrape_notes(
        [
            {
                "DocumentGroupName": "Bill Versions",
                "Documents": [
                    doc("Senate Engrossed Version (02/26/2026)", pdf="/a/one.pdf"),
                    doc("Senate Engrossed Version (03/05/2026)", pdf="/a/two.pdf"),
                ],
            }
        ]
    )
    assert [v["note"] for v in bill.versions] == ["Senate Engrossed Version"]
    assert len(bill.versions[0]["links"]) == 2
