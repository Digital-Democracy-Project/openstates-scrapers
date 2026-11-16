"""OPEN-509 and OPEN-512: Massachusetts amendment papers are labelled amendments and listed on their real bill.

malegislature.gov files a committee redraft, a reprint and a member's amendment as a paper of its own ("Amendment
S.3178"). Ramon (2026-11-15): every such paper is labelled "amendment" (so it leaves Explore and search, as the
reports and orders did in OPEN-518) and is listed on its real bill. Only a draft the chamber formally substituted
for the bill (its own history says "Substituted ... for H5576") becomes a new version of that bill; every other
paper is a supporting document. A paper whose history names no bill is labelled and linked nowhere.

The pages and bill-history rows are real (malegislature.gov, 194th session; fixtures in tests/fixtures/ma_open509,
trimmed to the bill's own content). S3178 is the Senate Ways and Means redraft of H5576, substituted on 7/24/2026;
S3208 is a floor amendment to S3178 ("See S3178"); H4819 is an extension order with no h2 title.
"""
import os
import sys
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

version_ordering = pytest.importorskip("openstates.utils.version_ordering")
if not hasattr(version_ordering, "non_bill_kind"):
    pytest.skip(
        "needs openstates-core at or after OPEN-517 (dab94675)", allow_module_level=True
    )

from ma import Massachusetts  # noqa: E402
import ma.bills as bills  # noqa: E402
from ma.bills import MABillScraper, page_titles, resolve_paper_parents  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ma_open509")
SESSION = "194th"
URL = "https://malegislature.gov/Bills/194/{}"

needs_amendment_label = pytest.mark.skipif(
    not bills.AMENDMENT_LABEL_OK,
    reason="needs openstates-core with the 'amendment' bill label (OPEN-509)",
)


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def bill_page(number, title):
    """A real bill's page in the shape the site serves it: the "Bill <n>" h1 and its title in the h2."""
    return (
        '<html><body><div class="followable"><h1>Bill {n}</h1></div>'
        '<div id="contentContainer"><div><div><h2>{t}</h2></div></div></div>'
        "<div class=\"modalBtnGroup\"><a href='/Bills/194/{p}.pdf'>Download PDF</a></div>"
        "</body></html>"
    ).format(n=number, t=title, p=number.replace(".", ""))


EMPTY_HISTORY = "<table><tbody></tbody></table>"

PAGES = {
    URL.format("S3178"): fixture("S3178.html"),
    URL.format("S3208"): fixture("S3208.html"),
    URL.format("H4819"): fixture("H4819.html"),
    URL.format("H5576"): bill_page(
        "H.5576", "An Act relative to economic development in the commonwealth"
    ),
    URL.format("H1"): bill_page("H.1", "An Act relative to golf carts"),
}
HISTORY = {
    (URL.format("S3178"), 1): fixture("S3178_history_1.html"),
    (URL.format("S3178"), 5): fixture("S3178_history_5.html"),
    (URL.format("S3208"), 1): fixture("S3208_history_1.html"),
}

# the Documents list: real bills carry a docket number; amendment papers and some orders do not
BILL_LIST = [
    {"BillNumber": "H1", "DocketNumber": "HD1"},
    {"BillNumber": "H5576", "DocketNumber": None},
    {"BillNumber": "S3178", "DocketNumber": None},
    {"BillNumber": "S3208", "DocketNumber": None},
    {"BillNumber": "H4819", "DocketNumber": None},
]


def make_scraper():
    s = MABillScraper(Massachusetts(), "/tmp/")
    s.bill_list = [dict(row) for row in BILL_LIST]
    s.fetched = []

    def fetch_bill_page(url):
        s.fetched.append(url)
        return PAGES[url]

    def get_action_page(url, number):
        return lxml.html.fromstring(HISTORY.get((url, number), EMPTY_HISTORY))

    s.fetch_bill_page = fetch_bill_page
    s.get_action_page = get_action_page
    s.scrape_cosponsors = mock.Mock()
    return s


def scrape(s, number, chamber):
    """scrape_bill for one list row; the bill's own history is not what is under test."""
    meta = next(row for row in s.bill_list if row["BillNumber"] == number)
    with mock.patch.object(s, "scrape_actions", return_value=iter(())):
        out = list(s.scrape_bill(SESSION, meta, chamber))
    return out[-1]


@pytest.fixture
def scraped():
    s = make_scraper()
    s.scrape_amendment_papers(SESSION)
    return s


# --- the page's own title ---


def test_an_amendment_paper_is_known_by_its_h1_when_it_has_no_h2():
    assert page_titles(lxml.html.fromstring(fixture("S2512.html"))) == (
        "Amendment S.2512",
        "Amendment S.2512",
    )


def test_an_order_with_no_h2_is_known_by_its_h1():
    # one of the four non-measures that stayed "bill" (H4819; also the three Governor's Messages)
    assert page_titles(lxml.html.fromstring(fixture("H4819.html")))[0] == (
        "Extension Order H.4819"
    )


def test_the_bill_placeholder_h1_is_still_not_a_title():
    page = lxml.html.fromstring(
        '<html><body><div class="followable"><h1>Bill H.1</h1></div></body></html>'
    )
    assert page_titles(page) == (None, "H.1")


def test_an_h1_that_only_starts_with_bill_is_a_title():
    page = lxml.html.fromstring(
        '<html><body><div class="followable"><h1>Bill of Address H.12</h1></div></body></html>'
    )
    assert page_titles(page)[0] == "Bill of Address H.12"


def test_an_h2_title_wins():
    page = lxml.html.fromstring(bill_page("H.5576", "An Act relative to golf carts"))
    assert page_titles(page) == (
        "An Act relative to golf carts",
        "An Act relative to golf carts",
    )


# --- which bill a paper belongs to ---

# S2512 / S2514 / S2618 are the real shapes of the budget redraft, its reprint, and a paper with no history
REAL_PAPERS = {
    "S 3178": {"refs": ["H 5576", "S 3228"], "substituted_for": "H 5576"},
    "S 3228": {"refs": ["S 3178", "H 5576"], "substituted_for": None},
    "S 3208": {"refs": ["S 3178"], "substituted_for": None},
    "S 2512": {"refs": ["H 4010", "S 2514"], "substituted_for": "H 4010"},
    "S 2514": {"refs": ["S 2512", "H 4010"], "substituted_for": None},
    "S 2618": {"refs": [], "substituted_for": None},
}


def test_each_paper_resolves_to_its_real_bill():
    assert resolve_paper_parents(REAL_PAPERS) == {
        "S 3178": "H 5576",
        "S 3228": "H 5576",  # a reprint, through the draft it reprints
        "S 3208": "H 5576",  # a floor amendment, through the redraft it amends
        "S 2512": "H 4010",
        "S 2514": "H 4010",
        "S 2618": None,  # no history: never guessed
    }


def test_a_paper_pointing_at_two_bills_is_not_linked():
    papers = {"S 9": {"refs": ["H 1", "H 2"], "substituted_for": None}}
    assert resolve_paper_parents(papers) == {"S 9": None}


def test_the_substitution_names_the_bill_even_when_other_links_do_not_agree():
    papers = {"S 9": {"refs": ["H 1", "H 2"], "substituted_for": "H 2"}}
    assert resolve_paper_parents(papers) == {"S 9": "H 2"}


def test_papers_that_only_point_at_each_other_are_not_linked():
    papers = {
        "S 8": {"refs": ["S 9"], "substituted_for": None},
        "S 9": {"refs": ["S 8"], "substituted_for": None},
    }
    assert resolve_paper_parents(papers) == {"S 8": None, "S 9": None}


# --- the pre-pass and the real bill ---


def test_the_pre_pass_reads_only_rows_without_a_docket_number(scraped):
    assert URL.format("H1") not in scraped.fetched
    assert scraped.amendment_papers == {"S 3178", "S 3208"}


def test_the_substituted_draft_becomes_a_version_of_the_real_bill(scraped):
    bill = scrape(scraped, "H5576", "lower")
    assert [(v["note"], v["date"], v["links"][0]["url"]) for v in bill.versions] == [
        ("Bill Text", "", "https://malegislature.gov/Bills/194/H5576.pdf"),
        (
            "Substituted text (S3178)",
            "2026-07-24",
            "https://malegislature.gov/Bills/194/S3178.pdf",
        ),
    ]


def test_a_floor_amendment_becomes_a_supporting_document_of_the_real_bill(scraped):
    bill = scrape(scraped, "H5576", "lower")
    assert [(d["note"], d["date"], d["links"][0]["url"]) for d in bill.documents] == [
        (
            "Amendment S.3208",
            "2026-07-23",
            "https://malegislature.gov/Bills/194/S3208.pdf",
        )
    ]
    bill.validate()


def test_a_draft_that_was_not_substituted_is_a_document_not_a_version():
    s = make_scraper()
    # the same redraft, had the Senate never substituted it: only the first history page
    s.get_action_page = lambda url, n: lxml.html.fromstring(
        HISTORY.get((url, n), EMPTY_HISTORY) if n == 1 else EMPTY_HISTORY
    )
    s.scrape_amendment_papers(SESSION)
    bill = scrape(s, "H5576", "lower")
    assert [v["note"] for v in bill.versions] == ["Bill Text"]
    assert [d["note"] for d in bill.documents] == [
        "Amendment S.3178",
        "Amendment S.3208",
    ]


def test_a_substituted_draft_without_a_pdf_is_a_document_not_a_version():
    s = make_scraper()
    pages = dict(PAGES)
    pages[URL.format("S3178")] = PAGES[URL.format("S3178")].replace(
        "Download PDF", "Download Word"
    )
    s.fetch_bill_page = lambda url: pages[url]
    s.scrape_amendment_papers(SESSION)
    bill = scrape(s, "H5576", "lower")
    assert [v["note"] for v in bill.versions] == ["Bill Text"]
    assert ("Amendment S.3178", URL.format("S3178")) in [
        (d["note"], d["links"][0]["url"]) for d in bill.documents
    ]


def test_a_paper_page_is_fetched_once(scraped):
    scrape(scraped, "S3178", "upper")
    assert scraped.fetched.count(URL.format("S3178")) == 1


@needs_amendment_label
@pytest.mark.parametrize("number", ["S3178", "S3208"])
def test_the_paper_itself_is_labelled_an_amendment_and_keeps_its_old_label(
    scraped, number
):
    bill = scrape(scraped, number, "upper")
    assert bill.classification == ["amendment"]
    assert bill.extras == {"ddp_open517_original_classification": ["bill"]}
    assert bill.versions[0]["note"] == "Bill Text"  # its own text stays on it
    bill.validate()


def test_the_extension_order_without_an_h2_is_labelled_an_order(scraped):
    bill = scrape(scraped, "H4819", "lower")
    assert bill.title == "Extension Order H.4819"
    assert bill.classification == ["order"]
    assert bill.extras == {"ddp_open517_original_classification": ["bill"]}


def test_a_paper_the_pre_pass_missed_is_still_labelled_and_says_so():
    s = make_scraper()  # no pre-pass
    with mock.patch.object(s, "warning") as warning:
        bill = scrape(s, "S3208", "upper")
    assert any("OPEN-509" in c.args[0] for c in warning.call_args_list)
    if bills.AMENDMENT_LABEL_OK:
        assert bill.classification == ["amendment"]


def test_with_an_older_core_the_paper_stays_a_bill_but_is_still_linked(
    scraped, monkeypatch
):
    monkeypatch.setattr(bills, "AMENDMENT_LABEL_OK", False)
    assert scrape(scraped, "S3208", "upper").classification == ["bill"]
    assert [d["note"] for d in scrape(scraped, "H5576", "lower").documents] == [
        "Amendment S.3208"
    ]


def test_the_version_note_ranks_between_the_bill_text_and_the_enacted_law():
    # openstates-core's version ordering, the one LegBot's changelogs and the archiver's diffs use
    notes = ["Chapter Law Text (Enacted)", "Substituted text (S3178)", "Bill Text"]
    ordered = sorted(notes, key=lambda n: version_ordering.version_sort_key(n, None))
    assert ordered == [
        "Bill Text",
        "Substituted text (S3178)",
        "Chapter Law Text (Enacted)",
    ]
    assert version_ordering.is_bill_version(
        "Massachusetts",
        "Substituted text (S3178)",
        "An Act relative to economic development in the commonwealth",
    )
