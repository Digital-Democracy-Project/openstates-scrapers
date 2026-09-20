import tempfile

import lxml.html
import scrapelib

from wa.bills import WABillScraper, _wa_bill_id_to_no


def _make_scraper():
    scraper = WABillScraper(None, tempfile.mkdtemp())
    scraper.biennium = "2025-26"
    return scraper


class _FakeHTTPResponse:
    status_code = 404
    url = "http://lawfilesext.leg.wa.gov/"
    text = "Not Found"


def _http_404():
    return scrapelib.HTTPError(_FakeHTTPResponse())


def _listing_page(entries):
    # doc.xpath("//a")[1:] in both _load_versions and _load_documents skips
    # the first <a> (a "parent directory" link on the real listing pages) --
    # the leading dummy link here mirrors that.
    links = "".join(f'<a href="{href}">{text}</a>' for href, text in entries)
    return lxml.html.fromstring(f"<html><body><a href=\"../\">..</a>{links}</body></html>")


def _mock_bill_list(scraper, monkeypatch, bill_ids):
    # get_prefiles/scrape_chamber together are how scrape() builds
    # self._bill_id_list -- both are cheap, metadata-only fetches, unfiltered by
    # bill_no= just like FL's list-walk. Stubbing them out here isolates the
    # thing this ticket actually changes: which of those ids go on to
    # scrape_bill(), the expensive per-bill fetch.
    monkeypatch.setattr(scraper, "get_prefiles", lambda chamber, session, year: [])

    def fake_scrape_chamber(chamber, session):
        scraper._bill_id_list.extend(bill_ids)

    monkeypatch.setattr(scraper, "scrape_chamber", fake_scrape_chamber)


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-78: bill_no= targeting -- scopes scrape() to just the requested bill(s)
# within the already-built bill_id list, instead of every matching bill.
# ═══════════════════════════════════════════════════════════════════════════


def test_wa_bill_id_to_no_normalizes_spacing_case_and_padding():
    assert _wa_bill_id_to_no("HB 1146") == "HB1146"
    assert _wa_bill_id_to_no("hb1146") == "HB1146"
    assert _wa_bill_id_to_no("SB 0205") == "SB205"
    assert _wa_bill_id_to_no("HJR 4200") == "HJR4200"
    assert _wa_bill_id_to_no("SCR 0003") == "SCR3"
    assert _wa_bill_id_to_no("HJM 4001") == "HJM4001"


def test_scrape_with_bill_no_only_scrapes_the_matching_bill(monkeypatch):
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["HB 1146", "SB 5000", "HB 9999"])

    scraped_ids = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda chamber, session, bill_id, year: scraped_ids.append(bill_id) or iter(()),
    )

    list(scraper.scrape(chamber="lower", session="2025-2026", bill_no="HB1146"))

    assert scraped_ids == ["HB 1146"]


def test_scrape_with_multi_bill_no_scrapes_all_requested_bills_only(monkeypatch):
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["HB 1146", "SB 5000", "HB 9999"])

    scraped_ids = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda chamber, session, bill_id, year: scraped_ids.append(bill_id) or iter(()),
    )

    list(scraper.scrape(chamber="lower", session="2025-2026", bill_no="HB1146,SB5000"))

    assert sorted(scraped_ids) == ["HB 1146", "SB 5000"]


def test_scrape_without_bill_no_scrapes_every_bill_unchanged(monkeypatch):
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["HB 1146", "SB 5000", "HB 9999"])

    scraped_ids = []
    monkeypatch.setattr(
        scraper,
        "scrape_bill",
        lambda chamber, session, bill_id, year: scraped_ids.append(bill_id) or iter(()),
    )

    list(scraper.scrape(chamber="lower", session="2025-2026"))

    assert sorted(scraped_ids) == ["HB 1146", "HB 9999", "SB 5000"]


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-123: warn when a requested bill_no matched nothing. Before this, a typo
# or stale number in a targeted backfill scraped zero bills and exited cleanly,
# which is indistinguishable from "that bill had nothing to recover".
# ═══════════════════════════════════════════════════════════════════════════


def _capture_warnings(scraper, monkeypatch):
    warnings = []
    monkeypatch.setattr(scraper, "warning", lambda msg: warnings.append(msg))
    monkeypatch.setattr(scraper, "scrape_bill", lambda *args: iter(()))
    return warnings


def test_scrape_warns_on_unmatched_bill_no(monkeypatch):
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["HB 1146", "SB 5000", "HB 9999"])
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape(chamber="lower", session="2025-2026", bill_no="HB1146,HB404"))

    assert any("HB404" in msg for msg in warnings)
    assert not any("HB1146" in msg for msg in warnings)
    # VA's wording names the session, which is what makes the warning actionable
    # when a number is valid in one session but not the one being scraped.
    assert any("2025-2026" in msg for msg in warnings)


def test_scrape_does_not_warn_when_every_requested_bill_no_matched(monkeypatch):
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["HB 1146", "SB 5000", "HB 9999"])
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape(chamber="lower", session="2025-2026", bill_no="HB1146,SB5000"))

    assert warnings == []


def test_scrape_does_not_warn_on_padding_or_spacing_difference(monkeypatch):
    # "SB 0205" on the list page must satisfy a requested "SB205": the matched set
    # is built with the same _wa_bill_id_to_no() used to filter, so a padding
    # difference cannot produce a false "not found".
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["SB 0205"])
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape(chamber="lower", session="2025-2026", bill_no="SB205"))

    assert warnings == []


def test_scrape_without_bill_no_never_warns(monkeypatch):
    # bill_no is unset on every scheduled production run -- that path must not
    # gain any new warning behaviour.
    scraper = _make_scraper()
    _mock_bill_list(scraper, monkeypatch, ["HB 1146", "SB 5000"])
    warnings = _capture_warnings(scraper, monkeypatch)

    list(scraper.scrape(chamber="lower", session="2025-2026"))

    assert warnings == []


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-299: a fetch failure for one bill_type's/doctype's listing page must
# not abandon every one that comes after it. _load_versions/_load_documents
# each walk a fixed ordered list ("Bills" first in _load_versions -- which is
# why HB/SB never showed the symptom -- then Resolutions, Concurrent
# Resolutions, Joint Memorials, Joint Resolutions, Passed Legislature; three
# doctypes in _load_documents). Before this fix, `except scrapelib.
# HTTPError: return` inside the loop exited the whole method the moment any
# one entry 404'd, silently leaving every later entry's bills with zero
# version/document links -- exactly the WA pattern OPEN-297 traced (101 HR +
# 83 SR + every resolution/memorial type failing "no archived text", 0
# HB/SB).
# ═══════════════════════════════════════════════════════════════════════════


def test_load_versions_a_later_bill_type_still_loads_after_an_earlier_one_404s(
    monkeypatch,
):
    # base_url already ends in ".../Htm/Bills/" (a fixed path segment), so a
    # plain `"Bills" in url` substring check would match every bill_type's
    # URL, not just the "Bills" bill_type -- matching on the exact suffix
    # each bill_type actually produces instead.
    scraper = _make_scraper()
    resolutions_page = _listing_page([("1234.htm", "1234.htm")])

    def fake_lxmlize(url):
        if url.endswith("House Bills"):
            raise _http_404()
        if url.endswith("House Resolutions"):
            return resolutions_page
        return _listing_page([])

    monkeypatch.setattr(scraper, "lxmlize", fake_lxmlize)

    scraper._load_versions("lower")

    # "HR 1234" -- chamber[0]="H", bill_types["Resolutions"]="R". Before this
    # fix, the "Bills" 404 would have returned out of the method entirely,
    # and self.versions would be empty.
    assert "HR 1234" in scraper.versions
    assert scraper.versions["HR 1234"]


def test_load_versions_an_earlier_bill_type_is_preserved_when_a_later_one_404s(
    monkeypatch,
):
    scraper = _make_scraper()
    bills_page = _listing_page([("5678.htm", "5678.htm")])

    def fake_lxmlize(url):
        if url.endswith("House Bills"):
            return bills_page
        raise _http_404()

    monkeypatch.setattr(scraper, "lxmlize", fake_lxmlize)

    scraper._load_versions("lower")

    # "HB 5678" -- the first bill_type's real data must survive every later
    # bill_type failing, not just the other way around.
    assert "HB 5678" in scraper.versions
    assert scraper.versions["HB 5678"]


def test_load_versions_logs_a_warning_naming_the_failed_bill_type(monkeypatch):
    scraper = _make_scraper()
    warnings = []
    monkeypatch.setattr(scraper, "warning", lambda msg: warnings.append(msg))
    monkeypatch.setattr(
        scraper,
        "lxmlize",
        lambda url: (_ for _ in ()).throw(_http_404())
        if url.endswith("House Bills")
        else _listing_page([]),
    )

    scraper._load_versions("lower")

    assert any("Bills" in msg for msg in warnings)


def test_load_documents_a_later_doctype_still_loads_after_an_earlier_one_404s(
    monkeypatch,
):
    scraper = _make_scraper()
    digests_page = _listing_page([("9999.htm", "9999 Digest.htm")])

    def fake_lxmlize(url):
        if "Amendments" in url:
            raise _http_404()
        if "Digests" in url:
            return digests_page
        return _listing_page([])

    monkeypatch.setattr(scraper, "lxmlize", fake_lxmlize)

    scraper._load_documents("lower")

    # Before this fix, the "Amendments" 404 (first in document_types) would
    # have returned out of the method entirely, and self.documents would be
    # empty -- "Bill Reports" and "Digests" never even attempted.
    assert "9999" in scraper.documents
    assert scraper.documents["9999"]


def test_load_documents_logs_a_warning_naming_the_failed_doctype(monkeypatch):
    scraper = _make_scraper()
    warnings = []
    monkeypatch.setattr(scraper, "warning", lambda msg: warnings.append(msg))
    monkeypatch.setattr(
        scraper,
        "lxmlize",
        lambda url: (_ for _ in ()).throw(_http_404())
        if "Amendments" in url
        else _listing_page([]),
    )

    scraper._load_documents("lower")

    assert any("Amendments" in msg for msg in warnings)
