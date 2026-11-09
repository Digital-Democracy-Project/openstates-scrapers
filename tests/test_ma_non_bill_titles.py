"""OPEN-508: the Massachusetts scraper no longer makes a bill out of a report, order or communication.

malegislature.gov files agency reports, communications, legislative orders, study orders, precepts and
rules under H/S/HD/SD numbers in the same Documents list as real bills. The rule that says what opens
like a measure is openstates-core's `is_bill_version` (OPEN-498); these tests prove the scraper asks it
with the PAGE's title, never skips on a blank title, and leaves amendment papers (OPEN-509) alone. Titles
are real ones from the 194th session.

The Documents list's own `Title` is deliberately NOT used: checked on the live list (2026-11-08) it differs
from the page title (19 real bills lack "An Act" there, amendment papers show a subject), so a list-stage
skip would drop real bills. `test_the_list_title_is_never_used` pins that.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

pytest.importorskip("openstates.utils.version_ordering")  # DDP's openstates-core fork, as in the image

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

SESSION = "194th"

NOT_BILLS = [
    "A communication from the Executive Office of Public Safety and Security (see Section 2B(f) of Chapter 6A)",
    "An annual report of the Public Employee Retirement Administration Commission",
    "Emergency Housing Assistance Program Bi-weekly Report",
    "Study Order",
    "Golf Carts",
    "Order relative to extending until Friday, February 27, 2026 the time in which the committee shall report",
    "Governor's Message H.5680",
    "Proposed House Rules Amendment Order",
    "Amendment Filing Deadline for House No. 5151",  # starts with "Amendment" but is a notice, not an amendment paper
    "Precept setting forth the Special Election to fill the vacancy of the First Middlesex Senatorial District",
]
MEASURES = [
    "An Act relative to golf carts",
    "Resolve establishing a coastal waters wastewater financing commission",
    "Resolutions rescinding previous Article V Convention applications",
    "Joint Resolution urging the United States Congress to act",
    "Proposal for a legislative amendment to the Constitution relative to voting rights",
]
AMENDMENT_PAPERS = ["Amendment H.5665", "Amendment S.3290", "  amendment H.4265"]


def row(number, title):
    return {"BillNumber": number, "DocketNumber": None, "Title": title}


def scraper(rows):
    s = MABillScraper(Massachusetts(), "/tmp/")
    s.bill_list = []
    resp = mock.Mock()
    resp.content = __import__("json").dumps(rows).encode()
    s.get = mock.Mock(return_value=resp)
    s.info = mock.Mock()
    s.warning = mock.Mock()
    s.error = mock.Mock()
    return s


def queued(s):
    return [m["BillNumber"] for m in s.bill_list]


# Real rows of the live Documents list (2026-11-08): the list's Title is not the page's title.
LIST_TITLES_THAT_ARE_NOT_THE_PAGE_TITLE = [
    ("H5174", "to increase student access to career technical education schools and programs"),  # a real bill
    ("S2630", "promoting economic development with emerging artificial intelligence models"),  # a real bill
    ("S3207", "Rural Jobs"),  # page says "Amendment S.3207"
    ("S2618", "Establishing privacy standards for student and educator data"),  # page: "Amendment S.2618"
    ("H1", "Study Order"),  # a genuine non-bill: still queued here, skipped later by its page title
]


@pytest.mark.parametrize("number, list_title", LIST_TITLES_THAT_ARE_NOT_THE_PAGE_TITLE)
def test_the_list_title_is_never_used(number, list_title):
    s = scraper([row(number, list_title)])
    s.scrape_bill_list(SESSION)
    assert queued(s) == [number]


def test_a_mixed_list_is_queued_whole():
    s = scraper([row("H1", "An Act relative to golf carts"), row("H2", "Study Order"), row("S3", "Amendment S.3290")])
    s.scrape_bill_list(SESSION)
    assert queued(s) == ["H1", "H2", "S3"]


# --- the page title in scrape_bill: the only title the skip reads ---
PAGE = """<html><body>
<div class="followable"><h1>Bill H.{n}</h1></div>
<div id="contentContainer"><div><div>{h2}</div></div></div>
</body></html>"""


def fetch_page(s, h2, n="1"):
    resp = mock.Mock()
    resp.text = PAGE.format(n=n, h2=f"<h2>{h2}</h2>" if h2 else "")
    s.get = mock.Mock(return_value=resp)
    s.scrape_actions = mock.Mock(return_value=iter(()))
    s.scrape_cosponsors = mock.Mock()
    return s


def run_scrape_bill(h2):
    s = fetch_page(scraper([]), h2)
    out = list(s.scrape_bill(SESSION, {"BillNumber": "H1", "DocketNumber": "HD1"}, "lower"))
    return s, out


@pytest.mark.parametrize("title", NOT_BILLS)
def test_scrape_bill_skips_a_page_whose_real_title_is_not_a_measure(title):
    s, out = run_scrape_bill(title)
    assert out == []


@pytest.mark.parametrize("title", MEASURES)
def test_scrape_bill_keeps_a_measure(title):
    s, out = run_scrape_bill(title)
    assert [b.identifier for b in out] == ["H1"]


@pytest.mark.parametrize("title", AMENDMENT_PAPERS)
def test_scrape_bill_keeps_an_amendment_paper(title):
    s, out = run_scrape_bill(title)
    assert [b.identifier for b in out] == ["H1"]


def test_scrape_bill_never_skips_on_the_h1_placeholder_when_the_page_has_no_title():
    # The state site sometimes lacks a title for a few days; the scraper then falls back to the h1
    # ("Bill H.1" -> "H.1"), which is a number, not a title, and must not be read as "not a measure".
    s, out = run_scrape_bill("")
    assert [b.identifier for b in out] == ["H1"]


def test_without_openstates_core_nothing_is_skipped_and_it_says_so_once(monkeypatch):
    import ma.bills as bills

    monkeypatch.setattr(bills, "is_bill_version", None)
    s = fetch_page(scraper([]), "Study Order")
    out1 = list(s.scrape_bill(SESSION, {"BillNumber": "H1", "DocketNumber": "HD1"}, "lower"))
    out2 = list(s.scrape_bill(SESSION, {"BillNumber": "H1", "DocketNumber": "HD1"}, "lower"))
    assert [b.identifier for b in out1] == ["H1"] and [b.identifier for b in out2] == ["H1"]
    assert s.warning.call_count == 1
