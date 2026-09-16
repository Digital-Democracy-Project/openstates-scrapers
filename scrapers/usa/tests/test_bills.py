import os

import lxml.html

from usa.bills import (
    USBillScraper,
    _US_BILL_URL_RE,
    _normalize_bill_no_input,
    _us_bill_no_key,
)


FIXTURE_DIR = os.path.join(os.path.dirname(__file__))


def make_scraper():
    return USBillScraper(jurisdiction="usa", datadir="/tmp")


def _load_page(filename):
    with open(os.path.join(FIXTURE_DIR, filename), "rb") as f:
        return lxml.html.fromstring(f.read())


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


# --- OPEN-123: warn when a requested bill_no matched nothing ---
#
# US does its per-entry filtering in parse_bill_list(), which scrape() may call
# once per chamber sitemap, so the matched set is threaded into it and diffed
# back in scrape(). Members are keyed with the same _us_bill_no_key() the filter
# uses, so a padding/case difference can't produce a false "not found".


def _capture_warnings(scraper):
    warnings = []
    scraper.warning = lambda msg: warnings.append(msg)
    return warnings


def test_scrape_warns_on_unmatched_bill_no():
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    _record_parse_bill(scraper)
    warnings = _capture_warnings(scraper)

    list(scraper.scrape(session="119", bill_no="HR160,HR40404"))

    assert any("HR40404" in msg for msg in warnings)
    assert not any("HR160" in msg for msg in warnings)
    assert any("119" in msg for msg in warnings)


def test_scrape_does_not_warn_when_every_requested_bill_no_matched():
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    _record_parse_bill(scraper)
    warnings = _capture_warnings(scraper)

    list(scraper.scrape(session="119", bill_no="HR160,S325"))

    assert warnings == []


def test_scrape_does_not_warn_for_matches_spread_across_chamber_sitemaps():
    # HR160 is found walking the 119hr sitemap and S325 the 119s one -- two
    # separate parse_bill_list() calls. Diffing per call would warn about
    # whichever chamber was walked first. Guards that regression.
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    processed = _record_parse_bill(scraper)
    warnings = _capture_warnings(scraper)

    list(scraper.scrape(session="119", bill_no="S325"))

    assert processed == [S325_URL]
    assert warnings == []


def test_scrape_does_not_warn_on_padding_or_punctuation_difference():
    # "H.R. 0160" must satisfy the sitemap's own hr160 entry.
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    _record_parse_bill(scraper)
    warnings = _capture_warnings(scraper)

    list(scraper.scrape(session="119", bill_no="H.R. 0160"))

    assert warnings == []


def test_scrape_without_bill_no_never_warns():
    # bill_no is unset on every scheduled production run -- that path must not
    # gain any new warning behaviour.
    scraper = make_scraper()
    _mock_sitemaps(scraper)
    _record_parse_bill(scraper)
    warnings = _capture_warnings(scraper)

    list(scraper.scrape(session="119"))

    assert warnings == []


# --- OPEN-293 (correction): the LIVE production vote-scraping code lives here, in
# bills.py's scrape_house_votes()/scrape_senate_votes() -- not in usa/votes.py. "votes" is
# commented out of UnitedStates.scrapers (scrapers/usa/__init__.py), so USVoteScraper is
# never invoked by any real run; os-update's own scraper lookup (`juris.scrapers[name]`)
# would KeyError on "votes" if anything ever tried. votes.py is a parallel, unused
# reimplementation of the identical Clerk/Senate-LIS parsing logic -- confirmed by diffing
# the two side by side, xpath for xpath. PRs #47/#48 fixed votes.py's copy of this bug; this
# fixes the same bug in the copy that actually runs. Fixtures mirror votes.py's own
# tests/roll293_hjres_fixture.xml (unmodified, identical XML shape) and
# tests/senate_*_fixture.xml (with <congress> added -- bills.py's scrape_senate_votes()
# reads session from the page itself, while votes.py's scrape_senate_vote() takes it as a
# parameter instead; that's the one real structural difference between the two copies).


def test_scrape_house_votes_normalizes_hjres_bill_id():
    """Real case: HJRES 1's roll-293 vote had bill_identifier "HJ RES 1" before this fix --
    matches no real bill, so the vote never linked to anything and was silently dropped."""
    scraper = make_scraper()
    page = _load_page("roll293_hjres_fixture.xml")

    vote = scraper.scrape_house_votes(bill=None, page=page, url="https://clerk.house.gov/evs/2026/roll293.xml")

    assert vote.bill_identifier == "HJRES 1"


def test_scrape_senate_votes_normalizes_sjres_bill_id():
    """Real case: SJRES 55's roll-275 vote had bill_identifier "SJRes 55" before this fix --
    correct spacing, wrong case, so it still matched no real bill and was dropped."""
    scraper = make_scraper()
    page = _load_page("bills_senate_sjres_fixture.xml")

    votes = list(scraper.scrape_senate_votes(page, "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_275.xml"))

    assert len(votes) == 1
    assert votes[0].bill_identifier == "SJRES 55"


def test_scrape_senate_votes_normalizes_amendment_to_document_number():
    """The amendment_to_document_number branch (a vote on a free-standing amendment, not the
    bill itself) goes through the same normalize_senate_bill_id() call as document_name --
    confirms that branch actually gets normalized too, not just exercised structurally."""
    scraper = make_scraper()
    page = _load_page("bills_senate_amendment_fixture.xml")

    votes = list(scraper.scrape_senate_votes(page, "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_280.xml"))

    assert len(votes) == 1
    assert votes[0].bill_identifier == "SCONRES 10"


def test_scrape_senate_votes_still_skips_nominations_after_normalization():
    """Confirms the PN-nomination skip-check downstream of the normalization change still
    works -- a nomination vote (document_name "PN123", already bare/upper by convention) must
    still yield nothing, not get treated as a real bill vote."""
    scraper = make_scraper()
    page = _load_page("bills_senate_nomination_fixture.xml")

    votes = list(scraper.scrape_senate_votes(page, "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_281.xml"))

    assert votes == []
