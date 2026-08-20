from usa.bills import (
    USBillScraper,
    _US_BILL_URL_RE,
    _normalize_bill_no_input,
    _us_bill_no_key,
)


def make_scraper():
    return USBillScraper(jurisdiction="usa", datadir="/tmp")


class FakeResponse:
    def __init__(self, content):
        self.content = content


SITEMAP_INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://www.govinfo.gov/sitemap/bulkdata/BILLSTATUS/119hr/sitemap.xml</loc>
    <lastmod>2026-04-21T20:20:00.649Z</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://www.govinfo.gov/sitemap/bulkdata/BILLSTATUS/119s/sitemap.xml</loc>
    <lastmod>2026-04-21T20:20:00.649Z</lastmod>
  </sitemap>
</sitemapindex>
"""

# HR76's lastmod is deliberately much older than the others -- used to prove bill_no
# targeting bypasses the start-date cutoff (see test_scrape_with_bill_no_bypasses_start_cutoff).
HR_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr160.xml</loc>
    <lastmod>2026-04-21T20:20:00.649Z</lastmod>
  </url>
  <url>
    <loc>https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr76.xml</loc>
    <lastmod>2000-01-01T00:00:00.000Z</lastmod>
  </url>
  <url>
    <loc>https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr9999.xml</loc>
    <lastmod>2026-07-13T23:39:29.830Z</lastmod>
  </url>
</urlset>
"""

S_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s325.xml</loc>
    <lastmod>2026-05-01T00:00:00.000Z</lastmod>
  </url>
  <url>
    <loc>https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s9999.xml</loc>
    <lastmod>2026-06-01T00:00:00.000Z</lastmod>
  </url>
</urlset>
"""

HR160_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr160.xml"
HR76_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr76.xml"
HR9999_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr9999.xml"
S325_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s325.xml"
S9999_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s9999.xml"


def _mock_sitemaps(scraper):
    def fake_get(url):
        if "sitemapindex.xml" in url:
            return FakeResponse(SITEMAP_INDEX_XML)
        if "119hr/sitemap.xml" in url:
            return FakeResponse(HR_SITEMAP_XML)
        if "119s/sitemap.xml" in url:
            return FakeResponse(S_SITEMAP_XML)
        raise ValueError(f"unexpected url in test: {url}")

    scraper.get = fake_get


def _record_parse_bill(scraper):
    processed = []
    scraper.parse_bill = lambda url, scrape_hearings=True: processed.append(url) or iter(())
    return processed


# --- unit tests: normalization helpers ---


def test_us_bill_no_key_strips_leading_zeros_and_uppercases():
    assert _us_bill_no_key("hr", "0160") == "HR160"
    assert _us_bill_no_key("S", "325") == "S325"
    assert _us_bill_no_key("hjres", "68") == "HJRES68"


def test_normalize_bill_no_input_matches_us_bill_no_key_regardless_of_formatting():
    assert _normalize_bill_no_input("HR160") == "HR160"
    assert _normalize_bill_no_input("hr160") == "HR160"
    assert _normalize_bill_no_input("HR 0160") == "HR160"
    assert _normalize_bill_no_input("H.R. 160") == "HR160"
    assert _normalize_bill_no_input("S325") == "S325"


def test_us_bill_url_re_extracts_type_and_num_from_a_real_shaped_url():
    match = _US_BILL_URL_RE.search(HR160_URL)
    assert match is not None
    assert match.groups() == ("hr", "160")
    assert _us_bill_no_key(*match.groups()) == "HR160"


# --- scrape()-level tests ---


def test_scrape_with_bill_no_only_processes_the_matching_bill():
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    processed = _record_parse_bill(scraper)

    list(scraper.scrape(session="119", bill_no="HR160"))

    assert processed == [HR160_URL]


def test_scrape_with_multi_bill_no_processes_all_requested_bills_only():
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    processed = _record_parse_bill(scraper)

    list(scraper.scrape(session="119", bill_no="HR160,S325"))

    assert sorted(processed) == sorted([HR160_URL, S325_URL])


def test_scrape_without_bill_no_processes_every_bill_unchanged():
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    processed = _record_parse_bill(scraper)

    list(scraper.scrape(session="119"))

    assert sorted(processed) == sorted(
        [HR160_URL, HR76_URL, HR9999_URL, S325_URL, S9999_URL]
    )


def test_scrape_with_bill_no_bypasses_start_cutoff():
    # Without bill_no, this start value excludes HR76 (lastmod 2000, well before start).
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    processed = _record_parse_bill(scraper)

    list(scraper.scrape(session="119", start="2020-01-01T00:00:00"))

    assert HR76_URL not in processed

    # With bill_no explicitly targeting it, HR76 is fetched regardless of that same
    # start cutoff -- an explicit target shouldn't be silently dropped for staleness.
    scraper2 = make_scraper()
    _mock_sitemaps(scraper2)
    processed2 = _record_parse_bill(scraper2)

    list(scraper2.scrape(session="119", start="2020-01-01T00:00:00", bill_no="HR76"))

    assert processed2 == [HR76_URL]
