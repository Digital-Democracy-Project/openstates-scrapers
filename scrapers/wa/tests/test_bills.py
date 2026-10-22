import datetime
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
    return lxml.html.fromstring(
        f'<html><body><a href="../">..</a>{links}</body></html>'
    )


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


# ═══════════════════════════════════════════════════════════════════════════
# OPEN-409: upstream #5876's bulk GetLegislationIntroducedSince list, and the start= filter.
#
# The bulk list has ONE RECORD PER VERSION of a bill, oldest version first, and each record
# carries that version's own CurrentStatus: the base "HB 1390" record says 2025-03-03 while
# "SHB 1390" says 2026-03-31. A record's date can also be unset (0001-01-01). Reading the first
# record's date silently skipped a bill whose latest version had moved since start=. The shapes
# below are real records from the 2025-26 list.
# ═══════════════════════════════════════════════════════════════════════════

from wa.utils import NS  # noqa: E402


class _Proceeded(Exception):
    """scrape_bill() got past the start= filter and went on to fetch the bill's pages."""


def _record(bill_id, date, bill_number):
    return (
        f"<Legislation><Biennium>2025-26</Biennium><BillNumber>{bill_number}</BillNumber>"
        f"<BillId>{bill_id}</BillId><OriginalAgency>House</OriginalAgency>"
        "<LongDescription>A bill.</LongDescription>"
        "<ShortLegislationType><LongLegislationType>Bill</LongLegislationType>"
        "</ShortLegislationType>"
        f"<CurrentStatus><ActionDate>{date}</ActionDate></CurrentStatus></Legislation>"
    )


def _bulk_list(*records):
    return (
        f'<ArrayOfLegislation xmlns="{NS["wa"]}">'
        + "".join(records)
        + "</ArrayOfLegislation>"
    ).encode()


UNSET = "0001-01-01T00:00:00"


def _passes_start_filter(
    monkeypatch, records, bill_number, start="2026-03-29T00:00:00", per_bill=None
):
    scraper = _make_scraper()
    scraper._start_dt = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
    # normally filled in during a real scrape and read once past the filter
    scraper.documents = {}
    bulk = _bulk_list(*records)

    def fake_get(url, *args, **kwargs):
        if "GetLegislationIntroducedSince" in url:
            return type("R", (), {"content": bulk})()
        if per_bill is not None and "GetLegislation?biennium" in url:
            return type("R", (), {"content": per_bill})()
        raise _Proceeded(url)  # any other fetch means the bill got past the filter

    monkeypatch.setattr(scraper, "get", fake_get)
    try:
        list(scraper.scrape_bill("lower", "2025-2026", f"HB {bill_number}", 2026))
    except _Proceeded:
        return True
    return False


def test_start_filter_uses_the_latest_version_record_not_the_first(monkeypatch):
    # real HB 1390: base record 2025-03-03, substitute 2026-03-31 ("Effective date")
    records = [
        _record("HB 1390", "2025-03-03T00:00:00", "1390"),
        _record("SHB 1390", "2026-03-31T00:00:00", "1390"),
    ]
    assert _passes_start_filter(monkeypatch, records, "1390") is True


def test_start_filter_does_not_skip_a_bill_whose_first_record_has_no_date(monkeypatch):
    # real HB 2487: the first records are unset, only the last has a date after start=
    records = [
        _record("HB 2487", UNSET, "2487"),
        _record("EHB 2487", UNSET, "2487"),
        _record("HB 2487", UNSET, "2487"),
        _record("EHB 2487", "2026-04-01T00:00:00", "2487"),
    ]
    assert _passes_start_filter(monkeypatch, records, "2487") is True
    # real SB 6246: unset base record, dated engrossed version
    records = [
        _record("SB 6246", UNSET, "6246"),
        _record("ESB 6246", "2026-03-30T00:00:00", "6246"),
    ]
    assert _passes_start_filter(monkeypatch, records, "6246") is True


def test_start_filter_still_skips_a_bill_with_nothing_after_start(monkeypatch):
    records = [
        _record("HB 1000", "2026-01-10T00:00:00", "1000"),
        _record("SHB 1000", "2026-02-02T00:00:00", "1000"),
        _record("2SHB 1000", UNSET, "1000"),
    ]
    assert _passes_start_filter(monkeypatch, records, "1000") is False


def test_start_filter_scrapes_a_bill_when_no_record_has_a_usable_date(monkeypatch):
    # when in doubt scrape it: an unset date does not mean the bill is ancient
    records = [_record("HB 3000", UNSET, "3000"), _record("SHB 3000", UNSET, "3000")]
    assert _passes_start_filter(monkeypatch, records, "3000") is True


def test_start_filter_does_not_depend_on_the_order_of_a_bills_records(monkeypatch):
    records = [
        _record("HB 1390", "2025-03-03T00:00:00", "1390"),
        _record("SHB 1390", "2026-03-31T00:00:00", "1390"),
    ]
    assert _passes_start_filter(monkeypatch, records, "1390") is True
    assert _passes_start_filter(monkeypatch, list(reversed(records)), "1390") is True


def test_start_filter_skips_a_bill_dated_exactly_at_start_and_scrapes_one_second_later(
    monkeypatch,
):
    # unchanged behaviour: a bill whose latest status is not after start= is skipped
    at = [_record("HB 4000", "2026-03-29T00:00:00", "4000")]
    after = [_record("HB 4001", "2026-03-29T00:00:01", "4001")]
    assert _passes_start_filter(monkeypatch, at, "4000") is False
    assert _passes_start_filter(monkeypatch, after, "4001") is True


def test_start_filter_on_the_per_bill_path_for_resolutions_uses_its_own_date(
    monkeypatch,
):
    # resolutions are not in the bulk list; their GetLegislation record is used as before.
    # (The unset-date rule applies here too: a record with no date is scraped, not skipped.)
    def check(date):
        return _passes_start_filter(
            monkeypatch,
            [_record("HB 1", "2026-01-01T00:00:00", "1")],
            "8700",
            per_bill=_bulk_list(_record("SR 8700", date, "8700")),
        )

    assert check("2026-01-05T00:00:00") is False
    assert check("2026-04-05T00:00:00") is True
    assert check(UNSET) is True
