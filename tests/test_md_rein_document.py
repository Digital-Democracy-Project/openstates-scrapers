"""OPEN-814: Maryland's Racial Equity Impact Note is a document of the bill, not a version.

The Department of Legislative Services' Racial Equity Impact Note (Pubs/BudgetFiscal/<session>-<bill>-REIN.pdf) is an
analysis of a bill, listed on the bill page under "Analysis" beside the Fiscal and Policy Note. The history table
also lists it, as "Text - Racial Equity Impact Note", and every "Text - " history link was stored as a version: 69
versions of Maryland's first scrape (Mac replica). It is now a document, once; every other version and the fiscal
notes stay as they were (scrapers/md/bills.py, ANALYSES).

The fixtures (tests/fixtures/md_open814/) are real bill pages, mgaleg.maryland.gov/mgawebsite/Legislation/Details/
<bill>?ys=2026RS, saved 2026-11-24 and trimmed to the page's main body (div#mainBody, without scripts and the mobile
copy of the history table): HB 81 (House) and SB 854 (Senate) have a Racial Equity Impact Note; HB 998 (House) and
SB 982 (Senate) do not.
"""
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from md.bills import MDBillScraper  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "md_open814")
SITE = "http://mgaleg.maryland.gov/"
REIN = "Racial Equity Impact Note"
ANALYSIS_LINKS = '//dt[contains(text(), "Analysis")]/following-sibling::dd[1]/a'
REIN_HISTORY_ROW = (
    '//table[@id="detailsHistory"]/tbody/tr[td[4]/a[contains(., "Racial Equity")]]'
)


class FakeResponse:
    def __init__(self, content):
        self.content = content


class OfflineMD(MDBillScraper):
    """Serves one saved bill page (optionally edited) through the real scrape_bill()."""

    def __init__(self, page, edit=None):
        self.page = page
        self.edit = edit

    def get(self, url, **kwargs):
        with open(os.path.join(FIX, self.page), "rb") as f:
            content = f.read()
        if self.edit:
            doc = lxml.html.fromstring(content)
            for el in doc.xpath(self.edit):
                el.getparent().remove(el)
            content = lxml.html.tostring(doc)
        return FakeResponse(content)

    def warning(self, *args, **kwargs):
        pass


def scrape(page, edit=None):
    chamber = "lower" if page.startswith("h") else "upper"
    url = "https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/" + page[:6]
    (bill,) = OfflineMD(page, edit).scrape_bill(chamber, "2026", url)
    return bill


def urls(items):
    return {item["note"]: [link["url"] for link in item["links"]] for item in items}


def version_urls(bill):
    return sorted(link["url"] for v in bill.versions for link in v["links"])


EXPECTED = {
    # page: (version files, documents)
    "hb0081_2026RS.html": (
        ["2026RS/bills/hb/hb0081f.pdf"],
        {
            "Fiscal and Policy Note": [SITE + "2026RS/fnotes/bil_0001/hb0081.pdf"],
            REIN: [SITE + "Pubs/BudgetFiscal/2026RS-HB0081-REIN.pdf"],
        },
    ),
    "sb0854_2026RS.html": (
        ["2026RS/bills/sb/sb0854f.pdf"],
        {
            "Fiscal and Policy Note": [SITE + "2026RS/fnotes/bil_0004/sb0854.pdf"],
            REIN: [SITE + "Pubs/BudgetFiscal/2026RS-SB0854-REIN.pdf"],
        },
    ),
    "hb0998_2026RS.html": (
        [
            "2026RS/Chapters_noln/CH_844_hb0998e.pdf",
            "2026RS/bills/hb/hb0998e.pdf",
            "2026RS/bills/hb/hb0998f.pdf",
            "2026RS/bills/hb/hb0998t.pdf",
        ],
        {
            "Fiscal and Policy Note (Revised)": [
                SITE + "2026RS/fnotes/bil_0008/hb0998.pdf"
            ]
        },
    ),
    "sb0982_2026RS.html": (
        [
            "2026RS/Chapters_noln/CH_687_sb0982t.pdf",
            "2026RS/bills/sb/sb0982f.pdf",
            "2026RS/bills/sb/sb0982t.pdf",
        ],
        {"Fiscal and Policy Note": [SITE + "2026RS/fnotes/bil_0002/sb0982.pdf"]},
    ),
}


@pytest.mark.parametrize("page", sorted(EXPECTED))
def test_saved_pages(page):
    bill = scrape(page)
    versions, documents = EXPECTED[page]
    assert version_urls(bill) == sorted(SITE + v for v in versions)
    assert urls(bill.documents) == documents
    assert not [v for v in bill.versions if "REIN" in str(v) or REIN in v["note"]]


@pytest.mark.parametrize("page", ["hb0081_2026RS.html", "sb0854_2026RS.html"])
@pytest.mark.parametrize(
    "edit",
    [
        REIN_HISTORY_ROW,  # listed under Analysis only
        ANALYSIS_LINKS + '[contains(., "Racial Equity")]',  # in the history only
    ],
)
def test_either_listing_alone_makes_one_document(page, edit):
    bill = scrape(page, edit)
    assert urls(bill.documents) == EXPECTED[page][1]
    assert version_urls(bill) == [SITE + EXPECTED[page][0][0]]


def test_other_analyses_after_the_first_stay_out():
    # unchanged: of the other analyses only those in ANALYSES are added ("Attorney General's Review Letter" is a
    # real Analysis link name on the replica; added here after HB 998's fiscal note)
    class WithLetter(OfflineMD):
        def get(self, url, **kwargs):
            doc = lxml.html.fromstring(super().get(url).content)
            dd = doc.xpath(ANALYSIS_LINKS)[0].getparent()
            dd.append(
                lxml.html.fragment_fromstring(
                    '<a href="/2026RS/misc/hb0998_ag.pdf">Attorney General\'s Review Letter</a>'
                )
            )
            return FakeResponse(lxml.html.tostring(doc))

    url = "https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/hb0998"
    (bill,) = WithLetter("hb0998_2026RS.html").scrape_bill("lower", "2026", url)
    assert urls(bill.documents) == EXPECTED["hb0998_2026RS.html"][1]
