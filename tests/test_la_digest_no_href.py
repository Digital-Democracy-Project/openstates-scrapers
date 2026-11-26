"""OPEN-902: a Louisiana documents link with no href must not fail the run.

On 2026-11-26 the 12:00 UTC nightly died with KeyError: 'href' at `digest.attrib["href"]` in scrape_bill_page, after 3.5
hours, and loaded nothing. A link with no href is now skipped and logged (never a guessed URL); the rest of the bill goes on.

Fixtures (tests/fixtures/la_open902/), all from legis.la.gov, fetched 2026-11-26: bill_HR171.html is the real BillInfo page
of HR171 (2026 Regular Session) and text_HR171.html its real Text subpage, both unchanged. digests_HR171_href_removed.html is
the real Digests subpage of HR171 with the href removed from ONE link ("Digest of HR171 Engrossed") by hand. The exact page
that failed in production was not found (HR171 and HR172 and five more neighbours had all their hrefs), so this is a minimal
real fragment with the attribute removed, not a copy of the failing page. No test makes a live call.
"""
import logging
import os
import sys

import lxml.html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from la.bills import LABillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "la_open902")
BILL_URL = "https://www.legis.la.gov/Legis/BillInfo.aspx?i=251738"
EMPTY = "<html><body></body></html>"


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def scrape(digests_page, text_page, caplog):
    pages = {
        BILL_URL: load("bill_HR171.html"),
        "t=digests": digests_page,
        "t=text": text_page,
    }

    def lxmlize(url, *args, **kwargs):
        for key, html in pages.items():
            if key in url:
                page = lxml.html.fromstring(html)
                page.make_links_absolute(url)
                return page
        return lxml.html.fromstring(EMPTY)  # amendments: no such page for HR171

    scraper = LABillScraper(jurisdiction="x", datadir="/tmp")
    scraper.start_year = "2026"
    scraper.lxmlize = lxmlize
    with caplog.at_level(logging.WARNING):
        out = list(scraper.scrape_bill_page("lower", "2026", BILL_URL, "HR"))
    bills = [o for o in out if isinstance(o, Bill)]
    assert len(bills) == 1
    return bills[0]


def test_digest_link_without_href_is_skipped_and_logged(caplog):
    bill = scrape(
        load("digests_HR171_href_removed.html"), load("text_HR171.html"), caplog
    )
    notes = [d["note"] for d in bill.documents]
    # the two links that still have an href are kept, the one without is not
    assert notes == [
        "Resume Digest for HR171",
        "Digest of HR171 Original",
    ]
    assert all(link["url"] for d in bill.documents for link in d["links"])
    # the rest of the bill is still built
    assert [v["note"] for v in bill.versions] == [
        "HR171 Enrolled",
        "HR171 Engrossed",
        "HR171 Original",
    ]
    # and the skip is named in the log: the bill and the link text
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "skipping digest link with no href" in logged
    assert "HR171" in logged and "Digest of HR171 Engrossed" in logged


def test_text_link_without_href_is_skipped_and_logged(caplog):
    # same crash, one line below: a Text link with no href (the digests page is the unchanged real one)
    text = load("text_HR171.html").replace(
        '<a href="ViewDocument.aspx?d=1466861"  target="_blank">HR171 Engrossed</a>',
        '<a target="_blank">HR171 Engrossed</a>',
    )
    assert text != load("text_HR171.html")
    bill = scrape(
        load("digests_HR171_href_removed.html").replace(
            '<a target="_blank">Digest of HR171 Engrossed</a>',
            '<a href="ViewDocument.aspx?d=1467198" target="_blank">Digest of HR171 Engrossed</a>',
        ),
        text,
        caplog,
    )
    assert [v["note"] for v in bill.versions] == ["HR171 Enrolled", "HR171 Original"]
    assert len(bill.documents) == 3
    assert "skipping text link with no href" in " ".join(
        r.getMessage() for r in caplog.records
    )


def test_all_links_with_href_are_unchanged(caplog):
    digests = load("digests_HR171_href_removed.html").replace(
        '<a target="_blank">Digest of HR171 Engrossed</a>',
        '<a href="ViewDocument.aspx?d=1467198"  target="_blank">Digest of HR171 Engrossed</a>',
    )
    bill = scrape(digests, load("text_HR171.html"), caplog)
    assert len(bill.documents) == 3
    assert len(bill.versions) == 3
    assert not [r for r in caplog.records if "OPEN-902" in r.getMessage()]
