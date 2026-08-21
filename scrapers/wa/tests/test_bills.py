import tempfile

from wa.bills import WABillScraper, _wa_bill_id_to_no


def _make_scraper():
    return WABillScraper(None, tempfile.mkdtemp())


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
