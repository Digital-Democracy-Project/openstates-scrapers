"""OPEN-583: Louisiana concurrences, conference reports and resolution adoptions are passage.

Fixtures (la_open583/), real and unchanged: the "Votes" lists (BillDocs.aspx?t=votes) of three
2026 Regular Session bills as legis.la.gov served them on 2026-11-17. The scraper reads each
vote's motion from its link text there. The tally comes from the vote's PDF, which is not under
test, so the PDF reader is replaced by a fixed body. No request leaves the test.
- HB 313: House "CONCUR IN SENATE AMENDMENTS (#1674)" (history 2026-05-29: "Senate amendments
  concurred in"), Senate and House "FINAL PASSAGE".
- SB 149: House "ADOPT CONFERENCE REPORT (#1794)", Senate "ADOPT (#1563)" (history 2026-05-31:
  "Conference Committee Report read; adopted by a vote of ..."), Senate "REJECT (#535)" (the
  Senate refused the House's amendments), two "FINAL PASSAGE".
- HB 675: House "CONCUR IN SENATE AMENDMENTS (#1224)", Senate "CO-AUTHORS (#673)", two
  "FINAL PASSAGE".
"""
import json
import os
import sys
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from la.bills import LABillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "la_open583")
PDF_BODY = lxml.html.fromstring(
    "<html><body>Date: 5/29/2026\nYEAS\nSmith\nJones\nNAYS\nDoe\nTotal\n</body></html>"
)


def scraped_votes(bill_id):
    with open(
        os.path.join(FIXTURES, bill_id.replace(" ", "") + "_votes.html"),
        encoding="utf-8",
    ) as f:
        text = f.read()
    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.get = mock.Mock(return_value=mock.Mock(text=text))
    scraper.urlretrieve = mock.Mock()
    scraper.pdf_to_lxml = mock.Mock(return_value=PDF_BODY)
    chamber = "lower" if bill_id.startswith("H") else "upper"
    bill = Bill(bill_id, "2026", "x", chamber=chamber)
    url = "https://legis.la.gov/legis/BillDocs.aspx?i=1&t=votes"
    # the chamber is stored as a pseudo id: ~{"classification": "upper"}
    return {
        (
            json.loads(v.organization[1:])["classification"],
            v.motion_text,
        ): v.motion_classification
        for v in scraper.scrape_votes(bill, url)
    }


@pytest.mark.parametrize(
    "bill_id,expected",
    [
        (
            "HB 313",
            {
                ("lower", "CONCUR IN SENATE AMENDMENTS (#1674)"): ["passage"],
                ("upper", "FINAL PASSAGE (#1383)"): ["passage"],
                ("lower", "FINAL PASSAGE (#568)"): ["passage"],
            },
        ),
        (
            "SB 149",
            {
                ("lower", "ADOPT CONFERENCE REPORT (#1794)"): ["passage"],
                ("upper", "ADOPT (#1563)"): ["passage"],
                ("upper", "REJECT (#535)"): [],
                ("lower", "FINAL PASSAGE (#799)"): ["passage"],
                ("upper", "FINAL PASSAGE (#71)"): ["passage"],
            },
        ),
        (
            "HB 675",
            {
                ("lower", "CONCUR IN SENATE AMENDMENTS (#1224)"): ["passage"],
                ("upper", "CO-AUTHORS (#673)"): [],
                ("upper", "FINAL PASSAGE (#672)"): ["passage"],
                ("lower", "FINAL PASSAGE (#18)"): ["passage"],
            },
        ),
    ],
)
def test_la_vote_types(bill_id, expected):
    assert scraped_votes(bill_id) == expected
