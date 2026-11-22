"""OPEN-750: Montana's 2011 to 2021 regular sessions carry their Legislature's ordinal.

The document endpoints (getBillVersions, getBillAmendments, getBillOther, getBillFiscalNotes)
find a bill's folder by legislatureOrdinal and sessionOrdinal. Without the ordinal the scraper
asked for legislatureOrdinal=None and every answer was a 404, so the bills of those sessions got
no text and no fiscal notes.

The fixtures (mt_open750/) are the legislature's own answers, saved 2026-11-21:

* archive_bills_search_<sessionId>.json: api.legmt.gov/archive/v1/bills/search for each session
  (limit 10, offset 50). 20171 keeps the whole page of ten (seven numbered bills, three drafts);
  each other session keeps one numbered bill.
* document_responses.json: every document request the scraper makes for those bills, by URL,
  with its status and body. For 20171 it holds both the answers with ordinal 65 (200) and the
  answers with ordinal None (404, "No Folder found with the given path: None/20171/...").
* HB0090_1.pdf: the bill text getContent returned for 2017 HB 90's first version (documentId
  52172), and HB0090_1_first_lines.txt, the first lines of its text (pdftotext).

The expected ordinals come from the archive's own session list, saved by OPEN-749
(mt_open749/archive_sessions.json, api.legmt.gov/archive/v1/sessions), not from __init__.py.
"""
import json
import os
import sys
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import scrapelib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import mt  # noqa: E402
from mt.bills import MTBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures", "mt_open750")
ARCHIVE_SESSIONS = os.path.join(HERE, "fixtures", "mt_open749", "archive_sessions.json")

SESSIONS = ["2011", "2013", "2015", "2017", "2019", "2021"]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def archive_ordinals():
    return {str(r["sessionId"]): r["ordinal"] for r in load(ARCHIVE_SESSIONS)}


def session(identifier):
    (found,) = [
        s for s in mt.Montana.legislative_sessions if s["identifier"] == identifier
    ]
    return found


class _Resp:
    def __init__(self, data, status=200, url=None):
        self.data = data
        self.status_code = status
        self.url = url
        self.text = json.dumps(data)

    def json(self):
        return self.data


def run_scraper(monkeypatch, identifier, sessions=None):
    """Scrape one session's saved bill-search page, answering document requests from the
    saved responses; return the bills and the document URLs asked for."""
    scraped_name = session(identifier)["_scraped_name"]
    page = load(os.path.join(FIXTURES, f"archive_bills_search_{scraped_name}.json"))
    empty = {"bills": dict(page["bills"], content=[], numberOfElements=0)}
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, params=None, json=None, **kw: _Resp(
            page if params["offset"] == "0" else empty
        ),
    )
    saved = load(os.path.join(FIXTURES, "document_responses.json"))
    asked = []

    def get(url):
        asked.append(url)
        answer = saved[url]
        if answer["status"] != 200:
            # scrapelib raises on a 404, which the scraper catches as "no data"
            raise scrapelib.HTTPError(_Resp(answer["body"], answer["status"], url))
        return _Resp(answer["body"])

    jurisdiction = mt.Montana()
    if sessions is not None:
        jurisdiction.legislative_sessions = sessions
    scraper = MTBillScraper.__new__(MTBillScraper)
    scraper.jurisdiction = jurisdiction
    scraper.info = lambda *a, **k: None
    scraper.warning = lambda *a, **k: None
    scraper.get = get
    bills = [o for o in scraper.scrape(session=identifier) if isinstance(o, Bill)]
    return bills, asked


def version_urls(bills):
    return [link["url"] for b in bills for v in b.versions for link in v["links"]]


def test_each_regular_session_carries_the_archive_ordinal():
    ordinals = archive_ordinals()
    for identifier in SESSIONS:
        s = session(identifier)
        assert s["extras"]["legislatureOrdinal"] == ordinals[s["_scraped_name"]], s
        # still an archive session: the bills come from the archive endpoint
        assert s["extras"]["newAPIIdentifier"] is None


def test_every_archive_session_in_the_list_has_the_archive_ordinal():
    # the sessions the scraper keeps that the archive lists (2011 to 2023 and 2017s1)
    ordinals = archive_ordinals()
    listed = [
        s for s in mt.Montana.legislative_sessions if s["_scraped_name"] in ordinals
    ]
    assert len(listed) == 8
    for s in listed:
        assert s["extras"]["legislatureOrdinal"] == ordinals[s["_scraped_name"]], s


@pytest.mark.parametrize("identifier", SESSIONS)
def test_document_requests_carry_the_session_ordinal(monkeypatch, identifier):
    s = session(identifier)
    expected = archive_ordinals()[s["_scraped_name"]]
    bills, asked = run_scraper(monkeypatch, identifier)
    assert bills and asked
    for url in asked:
        query = parse_qs(urlparse(url).query)
        assert query["legislatureOrdinal"] == [str(expected)], url
        assert query["sessionOrdinal"] == [s["_scraped_name"]], url
    # every saved answer is a 200 with the documents listed, and each becomes a link
    saved = load(os.path.join(FIXTURES, "document_responses.json"))
    listed = sorted(
        f"https://api.legmt.gov/docs/v1/documents/getContent?documentId={doc['id']}"
        for url in asked
        for doc in saved[url]["body"]
    )
    linked = sorted(
        version_urls(bills)
        + [link["url"] for b in bills for d in b.documents for link in d["links"]]
    )
    assert listed and linked == listed


def test_2017_reaches_its_bill_text(monkeypatch):
    bills, asked = run_scraper(monkeypatch, "2017")
    (hb90,) = [b for b in bills if b.identifier == "HB 90"]
    (version,) = hb90.versions
    assert version["note"] == "HB0090_1.pdf"
    assert version["links"][0]["url"] == (
        "https://api.legmt.gov/docs/v1/documents/getContent?documentId=52172"
    )
    # what that URL returned: the bill's own text
    with open(os.path.join(FIXTURES, "HB0090_1.pdf"), "rb") as f:
        assert f.read(5) == b"%PDF-"
    with open(
        os.path.join(FIXTURES, "HB0090_1_first_lines.txt"), encoding="utf-8"
    ) as f:
        text = f.read()
    assert "65th Legislature" in text
    assert "HOUSE BILL NO. 90" in text


def test_2017_bill_text_urls_before_and_after(monkeypatch):
    # before: the 2017 entry as it was, with no extras, asks for legislatureOrdinal=None
    before_sessions = [
        dict((k, v) for k, v in s.items() if k != "extras")
        if s["identifier"] == "2017"
        else s
        for s in mt.Montana.legislative_sessions
    ]
    bills, asked = run_scraper(monkeypatch, "2017", sessions=before_sessions)
    assert asked and all("legislatureOrdinal=None&" in u for u in asked)
    assert version_urls(bills) == []
    assert not any(b.documents for b in bills)

    bills, asked = run_scraper(monkeypatch, "2017")
    # seven numbered bills: versions, amendments and other for each, fiscal notes for three
    assert len(asked) == 7 * 3 + 3
    assert len(version_urls(bills)) == 21
    assert sum(len(b.documents) for b in bills) == 3
