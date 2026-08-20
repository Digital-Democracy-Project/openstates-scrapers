"""Tests for OPEN-82: UT's bills scraper had no way to target a specific bill
or set of bills -- every scrape() call always walked the full session's bill
list and ran scrape_bill()'s full detail-page fetch (bill detail page,
cosponsor AJAX call, paginated actions/votes, and for 2025+ sessions a JSON
API call) for every single bill found.

bill_no= now accepts one identifier or a comma-separated list and scopes a
scrape to just those bills, mirroring FL's OPEN-77 template and the original
MA convention it's based on. UT has no spatula SkipItem mechanism to reuse
(unlike FL) -- the filter instead hooks into the existing plain-loop walk
over bill-list page <a> elements, using the label text already present on
that one page fetch to decide match/skip *before* scrape_bill() (the
expensive step) is ever called.

_normalize_bill_no() is the shared canonicalization: it maps both a
bill-list label (e.g. "H.B. 5 First Substitute") and a free-form bill_no=
value (e.g. "HB5", "hb 5", "HB0005") to the same key. It stops matching at
the first digit run, so a label's trailing "First Substitute"/"Second
Substitute"/etc. text is ignored by construction -- deliberately not reusing
SUB_BLACKLIST, which has a gap (only "Second Substitute".."Ninth Substitute"
plus a bare "Substitute" are listed, so "First Substitute" isn't fully
stripped by it).
"""
import os
import sys

import lxml.html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ut import Utah  # noqa: E402
from ut.bills import UTBillScraper, _normalize_bill_no  # noqa: E402


def make_scraper() -> UTBillScraper:
    return UTBillScraper(Utah(), "/tmp/")


# ── _normalize_bill_no: real bill-list label formats ────────────────────────


def test_normalizes_plain_house_bill_label():
    assert _normalize_bill_no("H.B. 1 ") == "HB1"


def test_normalizes_house_bill_label_with_first_substitute_suffix():
    # The exact gap SUB_BLACKLIST leaves open -- "First Substitute" isn't in
    # that list, so a reuse of it would leave "FIRST" stuck to the result.
    assert _normalize_bill_no("H.B. 5 First Substitute") == "HB5"


def test_normalizes_house_bill_label_with_higher_ordinal_substitute_suffix():
    assert _normalize_bill_no("H.B. 22 Fourth Substitute") == "HB22"


def test_normalizes_senate_bill_label():
    assert _normalize_bill_no("S.B. 3 ") == "SB3"


def test_normalizes_house_concurrent_resolution_label():
    assert _normalize_bill_no("H.C.R. 1 ") == "HCR1"


def test_normalizes_house_joint_resolution_label_with_substitute_suffix():
    assert _normalize_bill_no("H.J.R. 1 Second Substitute") == "HJR1"


def test_normalizes_house_resolution_label():
    assert _normalize_bill_no("H.R. 1") == "HR1"


def test_normalizes_senate_concurrent_resolution_label():
    assert _normalize_bill_no("S.C.R. 2 ") == "SCR2"


def test_normalizes_senate_joint_resolution_label():
    assert _normalize_bill_no("S.J.R. 4 ") == "SJR4"


def test_normalizes_senate_resolution_label():
    assert _normalize_bill_no("S.R. 1 ") == "SR1"


# ── _normalize_bill_no: free-form bill_no= input variants ───────────────────


def test_normalizes_bill_no_without_dots_or_spaces():
    assert _normalize_bill_no("HB5") == "HB5"


def test_normalizes_bill_no_lowercase_with_space():
    assert _normalize_bill_no("hb 5") == "HB5"


def test_normalizes_bill_no_with_dots_no_space():
    assert _normalize_bill_no("H.B.5") == "HB5"


def test_normalizes_bill_no_zero_padded():
    assert _normalize_bill_no("HB0005") == "HB5"
    assert _normalize_bill_no("HCR001") == "HCR1"


# ── scrape(): single- and multi-bill targeting ──────────────────────────────

FIXTURE_HTML = """
<html><body>
<a class="mitem" href="javascript:toggleObj('g1s1')">House Bills 1 - 49</a>
<div id="g1s1"><ul>
<li><a href="https://le.utah.gov/~2026/bills/static/HB0001.html" class="billlink">H.B. 1 </a></li>
<li><a href="https://le.utah.gov/~2026/bills/static/HB0005.html" class="billlink">H.B. 5 First Substitute</a></li>
</ul></div>
<a class="mitem" href="javascript:toggleObj('g5s1')">Senate Bills 1 - 49</a>
<div id="g5s1"><ul>
<li><a href="https://le.utah.gov/~2026/bills/static/SB0001.html" class="billlink">S.B. 1 </a></li>
<li><a href="https://le.utah.gov/~2026/bills/static/SB0003.html" class="billlink">S.B. 3 </a></li>
</ul></div>
</body></html>
"""


def run_scrape(scraper, **scrape_kwargs):
    """Runs scrape() with lxmlize() faked to the fixture list page and
    scrape_bill() faked to record calls instead of doing real detail-page
    work. Returns the list of (chamber, url) scrape_bill() was called with.
    """
    calls = []

    def fake_lxmlize(url, raise_exceptions=False, verify=None):
        return lxml.html.fromstring(FIXTURE_HTML)

    def fake_scrape_bill(chamber, session, url, session_slug):
        calls.append((chamber, url))
        return iter([])

    scraper.lxmlize = fake_lxmlize
    scraper.scrape_bill = fake_scrape_bill

    list(scraper.scrape(**scrape_kwargs))
    return calls


def test_no_bill_no_processes_every_bill_in_the_list():
    scraper = make_scraper()

    calls = run_scrape(scraper, session="2026")

    urls = {url for (_chamber, url) in calls}
    assert len(calls) == 4
    assert urls == {
        "https://le.utah.gov/~2026/bills/static/HB0001.html",
        "https://le.utah.gov/~2026/bills/static/HB0005.html",
        "https://le.utah.gov/~2026/bills/static/SB0001.html",
        "https://le.utah.gov/~2026/bills/static/SB0003.html",
    }


def test_single_bill_no_only_processes_that_one_bill():
    scraper = make_scraper()

    calls = run_scrape(scraper, session="2026", bill_no="HB5")

    assert calls == [
        ("lower", "https://le.utah.gov/~2026/bills/static/HB0005.html")
    ]


def test_multi_bill_no_only_processes_the_targeted_bills():
    scraper = make_scraper()

    calls = run_scrape(scraper, session="2026", bill_no="HB1,SB3")

    urls = {url for (_chamber, url) in calls}
    assert len(calls) == 2
    assert urls == {
        "https://le.utah.gov/~2026/bills/static/HB0001.html",
        "https://le.utah.gov/~2026/bills/static/SB0003.html",
    }


def test_multi_bill_no_matches_regardless_of_input_formatting():
    scraper = make_scraper()

    # mixed casing, spacing, and dotted vs. bare prefix -- all should still
    # match the fixture's "H.B. 1 " and "S.B. 3 " labels.
    calls = run_scrape(scraper, session="2026", bill_no="hb 1, S.B.3")

    urls = {url for (_chamber, url) in calls}
    assert len(calls) == 2
    assert urls == {
        "https://le.utah.gov/~2026/bills/static/HB0001.html",
        "https://le.utah.gov/~2026/bills/static/SB0003.html",
    }


def test_unmatched_bill_no_target_is_logged():
    scraper = make_scraper()
    warnings = []
    scraper.warning = lambda msg: warnings.append(msg)

    calls = run_scrape(scraper, session="2026", bill_no="HB1,HB9999")

    assert calls == [("lower", "https://le.utah.gov/~2026/bills/static/HB0001.html")]
    assert any("HB9999" in msg for msg in warnings)
