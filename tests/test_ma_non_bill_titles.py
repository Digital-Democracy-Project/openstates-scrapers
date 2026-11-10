"""OPEN-518 (replaces OPEN-508's skip): the Massachusetts scraper saves a report, order or communication
labelled as what it is, instead of skipping it or calling it a bill.

malegislature.gov files agency reports, communications, legislative orders, study orders, precepts and
rules under H/S/HD/SD numbers in the same Documents list as real bills. Ramon (2026-11-09): nothing is
removed from our data. The rule that names the kind is openstates-core's `non_bill_kind` (OPEN-517), the
same one `os-text-extract relabel-non-bills ma` uses; these tests prove the scraper asks it with the PAGE's
title and the actions, keeps a blank title an ordinary bill, and leaves amendment papers (OPEN-509) alone.
Titles are real ones from the 194th session.

The Documents list's own `Title` is deliberately NOT used: checked on the live list (2026-11-08) it differs
from the page title (19 real bills lack "An Act" there, amendment papers show a subject), so a list-stage
check would mislabel real bills. `test_the_list_title_is_never_used` pins that.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

version_ordering = pytest.importorskip(
    "openstates.utils.version_ordering"
)  # DDP's core fork, as in the image
if not hasattr(version_ordering, "non_bill_kind"):
    pytest.skip(
        "needs openstates-core at or after OPEN-517 (dab94675)", allow_module_level=True
    )

from ma import Massachusetts  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402

SESSION = "194th"

# (page title, the label it is saved with)
NOT_BILLS = [
    (
        "A communication from the Executive Office of Public Safety and Security (see Section 2B(f) of Chapter 6A)",
        "communication",
    ),
    ("Governor's Message H.5680", "communication"),
    (
        "An annual report of the Public Employee Retirement Administration Commission",
        "report",
    ),
    ("Emergency Housing Assistance Program Bi-weekly Report", "report"),
    ("Study Order", "study request"),
    (
        "Order relative to extending until Friday, February 27, 2026 the time in which the committee shall report",
        "order",
    ),
    ("Proposed House Rules Amendment Order", "order"),
    (
        "Precept setting forth the Special Election to fill the vacancy of the First Middlesex Senatorial District",
        "order",
    ),
    # rules items with recorded votes are labelled too (Ramon, 2026-11-10: none of the eight voted papers is a bill)
    ("Proposed Senate Rules for the 2025-2026 Legislative Session", "report"),
    (
        "Order relative to the adoption of permanent Rules of the House of Representatives for the 194th General Court governing the 2025-2026 legislative sessions",
        "order",
    ),
]
MEASURES = [
    "An Act relative to golf carts",
    "Resolve establishing a coastal waters wastewater financing commission",
    "Resolutions rescinding previous Article V Convention applications",
    "Joint Resolution urging the United States Congress to act",
    "Proposal for a legislative amendment to the Constitution relative to voting rights",
]
AMENDMENT_PAPERS = [
    "Amendment H.5665",
    "Amendment S.3290",
    "  amendment H.4265",
    # a notice, but it opens with "Amendment": the core rule (and so relabel-non-bills) leaves it as filed;
    # OPEN-508 used to skip it, and it is now kept unchanged rather than lost
    "Amendment Filing Deadline for House No. 5151",
]


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
    (
        "H5174",
        "to increase student access to career technical education schools and programs",
    ),  # a real bill
    (
        "S2630",
        "promoting economic development with emerging artificial intelligence models",
    ),  # a real bill
    ("S3207", "Rural Jobs"),  # page says "Amendment S.3207"
    (
        "S2618",
        "Establishing privacy standards for student and educator data",
    ),  # page: "Amendment S.2618"
    (
        "H1",
        "Study Order",
    ),  # a genuine non-bill: still queued here, labelled later by its page title
]


@pytest.mark.parametrize("number, list_title", LIST_TITLES_THAT_ARE_NOT_THE_PAGE_TITLE)
def test_the_list_title_is_never_used(number, list_title):
    s = scraper([row(number, list_title)])
    s.scrape_bill_list(SESSION)
    assert queued(s) == [number]


def test_a_mixed_list_is_queued_whole():
    s = scraper(
        [
            row("H1", "An Act relative to golf carts"),
            row("H2", "Study Order"),
            row("S3", "Amendment S.3290"),
        ]
    )
    s.scrape_bill_list(SESSION)
    assert queued(s) == ["H1", "H2", "S3"]


# --- the page title in scrape_bill: the only title the label reads ---
PAGE = """<html><body>
<div class="followable"><h1>Bill H.{n}</h1></div>
<div id="contentContainer"><div><div>{h2}</div></div></div>
</body></html>"""


def fetch_page(s, h2, n="1", actions=()):
    resp = mock.Mock()
    resp.text = PAGE.format(n=n, h2=f"<h2>{h2}</h2>" if h2 else "")
    s.get = mock.Mock(return_value=resp)

    def scrape_actions(bill, url, session):
        for description in actions:
            bill.add_action(description, "2025-03-01", chamber="lower")
        return iter(())

    s.scrape_actions = scrape_actions
    s.scrape_cosponsors = mock.Mock()
    return s


def run_scrape_bill(h2, actions=(), docket="HD1"):
    s = fetch_page(scraper([]), h2, actions=actions)
    out = list(
        s.scrape_bill(SESSION, {"BillNumber": "H1", "DocketNumber": docket}, "lower")
    )
    return s, out


def labels(out):
    return [(b.identifier, b.classification) for b in out]


@pytest.mark.parametrize("title, kind", NOT_BILLS)
def test_a_paper_that_is_not_a_bill_is_saved_with_its_label(title, kind):
    s, out = run_scrape_bill(title)
    assert labels(out) == [("H1", [kind])]
    assert out[0].title == title
    out[0].validate()  # the import accepts the label (openstates-core's bill schema)


def test_a_committee_study_order_titled_by_its_subject_is_known_by_its_action():
    actions = [
        "Reported from the committee on Transportation",
        "Order reported favorably by committee and referred to the committee on Joint Rules",
    ]
    assert labels(run_scrape_bill("Golf Carts", actions)[1]) == [
        ("H1", ["study request"])
    ]
    # without that action the same title is a filed paper
    assert labels(run_scrape_bill("Golf Carts", actions[:1])[1]) == [("H1", ["report"])]


@pytest.mark.parametrize("title", MEASURES)
def test_a_measure_is_still_a_bill(title):
    s, out = run_scrape_bill(title)
    assert labels(out) == [("H1", ["bill"])]


@pytest.mark.parametrize("title", AMENDMENT_PAPERS)
def test_an_amendment_paper_comes_through_unchanged(title):
    s, out = run_scrape_bill(title)
    assert labels(out) == [("H1", ["bill"])]


def test_a_paper_keeps_its_links_to_other_bills():
    # nothing about a labelled paper is dropped: here its docket link, as for any bill
    s, out = run_scrape_bill("Study Order")
    assert [(r["identifier"], r["relation_type"]) for r in out[0].related_bills] == [
        ("HD 1", "replaces")
    ]


def test_a_missing_title_never_gets_a_label_from_the_h1_placeholder():
    # The state site sometimes lacks a title for a few days; the scraper then falls back to the h1
    # ("Bill H.1" -> "H.1"), which is a number, not a title, and must not be read as "not a measure".
    s, out = run_scrape_bill("")
    assert labels(out) == [("H1", ["bill"])]
    assert out[0].title == "H.1"


def test_a_blank_title_stays_an_ordinary_bill():
    s, out = run_scrape_bill("   ")
    assert labels(out) == [("H1", ["bill"])]


def test_the_scraper_uses_the_core_rule_not_its_own_copy(monkeypatch):
    import ma.bills as bills

    asked = []

    def core_rule(name, title, actions):
        asked.append((name, title, list(actions)))
        return "communication"

    monkeypatch.setattr(bills, "non_bill_kind", core_rule)
    s, out = run_scrape_bill("An Act relative to golf carts", ["Read second"])
    # whatever the core rule says wins, even for a title that opens like a measure
    assert labels(out) == [("H1", ["communication"])]
    assert asked == [
        ("Massachusetts", "An Act relative to golf carts", ["Read second"])
    ]


@pytest.mark.parametrize("title, kind", NOT_BILLS)
def test_the_scraper_and_relabel_non_bills_agree(title, kind):
    # the relabel command's answer for the same title, read from openstates-core directly
    assert version_ordering.non_bill_kind("Massachusetts", title) == kind
    assert labels(run_scrape_bill(title)[1]) == [("H1", [kind])]


def test_without_openstates_core_every_paper_is_a_bill_and_it_says_so_once(monkeypatch):
    import ma.bills as bills

    monkeypatch.setattr(bills, "non_bill_kind", None)
    s = fetch_page(scraper([]), "Study Order")
    out1 = list(
        s.scrape_bill(SESSION, {"BillNumber": "H1", "DocketNumber": "HD1"}, "lower")
    )
    out2 = list(
        s.scrape_bill(SESSION, {"BillNumber": "H1", "DocketNumber": "HD1"}, "lower")
    )
    assert labels(out1) == [("H1", ["bill"])] and labels(out2) == [("H1", ["bill"])]
    assert s.warning.call_count == 1
