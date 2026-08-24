"""Tests for OPEN-134: MI's search `dateFrom=` filters on introduction date, so an incremental
run never returns a pre-existing bill that merely moved -- ~80 bills a week (OPEN-89).

The fix drops the date filter entirely and instead diffs each result row's own "Last Action:"
text against what the previous run recorded, re-scraping only the bills whose text changed.
These tests cover the parts where getting it wrong is silent: the skip decision, and when the
baseline is allowed to advance.
"""
import json
import os
import sys
from unittest import mock

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from mi.bills import (  # noqa: E402
    MIBillScraper,
    _mi_last_action_path,
    _mi_load_last_actions,
    _mi_normalize_last_action,
    _mi_save_last_actions,
)
import mi.bills as mi_bills  # noqa: E402
from openstates.exceptions import ScrapeError  # noqa: E402

SESSION = "2025-2026"


def results_page(rows) -> lxml.html.HtmlElement:
    """A minimal but structurally faithful ExecuteSearch results page.

    The xpath under test is anchored on div.tableScrollWrapper > table[1] > tbody > tr, with the
    bill link in td[1] and "Last Action: ..." at the end of td[3] -- matching the real page.
    """
    body = "".join(
        f"""<tr>
              <td><a href="/Home/GetObject?objectName={obj}">{label}</a></td>
              <td>House Bill</td>
              <td>Some description here.<br />{last}</td>
            </tr>"""
        for obj, label, last in rows
    )
    return lxml.html.fromstring(
        f'<div class="tableScrollWrapper"><table><tbody>{body}</tbody></table></div>'
    )


# --- normalization -------------------------------------------------------------------

def test_normalize_collapses_whitespace_and_case():
    assert (
        _mi_normalize_last_action("  REFERRED  to\n Committee ON  Rules ")
        == "referred to committee on rules"
    )


def test_normalize_handles_empty_and_none():
    assert _mi_normalize_last_action("") == ""
    assert _mi_normalize_last_action(None) == ""


def test_normalize_does_not_strip_dates():
    # A date IS part of the action text and a change in it is a real change. Stripping it would
    # make two different administrative rows compare equal, which is the silent-miss direction.
    a = _mi_normalize_last_action("bill electronically reproduced 06/24/2026")
    b = _mi_normalize_last_action("bill electronically reproduced 06/25/2026")
    assert a != b


# --- extraction ----------------------------------------------------------------------

def test_extract_reads_bill_no_and_last_action():
    page = results_page([
        ("2025-HB-4864", "HB 4864 of 2025", "Last Action: referred to second reading"),
        ("2025-SB-0001", "SB 0001 of 2025", "Last Action: referred to Committee on Rules"),
    ])
    got = MIBillScraper._extract_last_actions(None, page)
    assert got == {
        "HB4864": "referred to second reading",
        "SB1": "referred to committee on rules",
    }


def test_extract_normalizes_leading_zeros_like_the_scrape_loop():
    # The loop keys its skip decision on _mi_bill_id_to_no(bill_id); if extraction keyed
    # differently, every bill would look changed forever and the fix would silently become a
    # full walk.
    page = results_page([("2025-SB-0001", "SB 0001 of 2025", "Last Action: adopted")])
    assert "SB1" in MIBillScraper._extract_last_actions(None, page)


def test_extract_omits_row_with_no_last_action_marker():
    # Omitted, NOT recorded as "". An empty string would compare equal to a later genuinely
    # empty read and mask a change.
    page = results_page([("2025-HB-4001", "HB 4001 of 2025", "no marker here")])
    assert MIBillScraper._extract_last_actions(None, page) == {}


def test_extract_takes_the_last_marker_when_description_mentions_it():
    page = results_page([(
        "2025-HB-4002",
        "HB 4002 of 2025",
        "text mentioning Last Action: bogus <br />Last Action: real one",
    )])
    assert MIBillScraper._extract_last_actions(None, page) == {"HB4002": "real one"}


def test_extract_ignores_rows_without_a_link():
    page = lxml.html.fromstring(
        '<div class="tableScrollWrapper"><table><tbody>'
        "<tr><td></td><td>x</td><td>Last Action: adopted</td></tr>"
        "</tbody></table></div>"
    )
    assert MIBillScraper._extract_last_actions(None, page) == {}


def test_extract_on_empty_results_page():
    page = lxml.html.fromstring(
        '<div class="tableScrollWrapper"><table><tbody></tbody></table></div>'
    )
    assert MIBillScraper._extract_last_actions(None, page) == {}


# --- baseline persistence ------------------------------------------------------------

@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(mi_bills.settings, "CACHE_DIR", str(tmp_path))
    return tmp_path


def test_load_returns_none_when_absent(cache_dir):
    # None, not {}. {} would mean "recorded and empty" and would make every bill look changed.
    assert _mi_load_last_actions(SESSION) is None


def test_load_returns_none_on_corrupt_file(cache_dir):
    (cache_dir / f"mi_last_actions_{SESSION}.json").write_text("{not json")
    assert _mi_load_last_actions(SESSION) is None


def test_load_returns_none_when_json_is_not_a_dict(cache_dir):
    (cache_dir / f"mi_last_actions_{SESSION}.json").write_text('["a", "b"]')
    assert _mi_load_last_actions(SESSION) is None


def test_save_then_load_round_trip(cache_dir):
    _mi_save_last_actions(SESSION, {"HB4001": "adopted"})
    assert _mi_load_last_actions(SESSION) == {"HB4001": "adopted"}


def test_save_leaves_no_temp_file(cache_dir):
    _mi_save_last_actions(SESSION, {"HB4001": "adopted"})
    assert not [p for p in os.listdir(cache_dir) if p.endswith(".tmp")]


def test_baseline_is_keyed_per_session(cache_dir):
    # Bill numbers restart each session; a shared file would let a new session's HB 4001
    # inherit the previous one's last action and be skipped as unchanged.
    _mi_save_last_actions("2023-2024", {"HB4001": "old thing"})
    _mi_save_last_actions("2025-2026", {"HB4001": "new thing"})
    assert _mi_load_last_actions("2023-2024") == {"HB4001": "old thing"}
    assert _mi_load_last_actions("2025-2026") == {"HB4001": "new thing"}
    assert _mi_last_action_path("2023-2024") != _mi_last_action_path("2025-2026")


# --- scrape() wiring -----------------------------------------------------------------

@pytest.fixture
def scraper(cache_dir):
    s = MIBillScraper.__new__(MIBillScraper)
    s.info = mock.Mock()
    s.warning = mock.Mock()
    s.make_bill_url = lambda href: f"https://legislature.mi.gov/{href}"
    s._warn_unmatched_bill_nos = mock.Mock()
    return s


def drive(scraper, rows, start="2026-08-01", bill_no=None, scrape_bill=None):
    """Run scrape() against a stubbed results page, collecting which bills it fetched."""
    fetched = []

    # Patched onto the class, so this receives `self` like the real method.
    def fake_scrape_bill(_self, session, bill_id, bill_url):
        fetched.append(bill_id)
        if scrape_bill:
            yield from scrape_bill(session, bill_id, bill_url)
        else:
            return
            yield  # pragma: no cover

    resp = mock.Mock()
    resp.content = lxml.html.tostring(results_page(rows))
    with mock.patch.object(mi_bills, "mi_waf_get", return_value=resp), \
            mock.patch.object(MIBillScraper, "scrape_bill", fake_scrape_bill), \
            mock.patch.object(MIBillScraper, "get", create=True), \
            mock.patch.object(MIBillScraper, "_redirected_single_bill", return_value=None):
        list(scraper.scrape(SESSION, start=start, bill_no=bill_no))
    return fetched


ROWS = [
    ("2025-HB-4001", "HB 4001 of 2025", "Last Action: referred to Committee on Rules"),
    ("2025-HB-4002", "HB 4002 of 2025", "Last Action: adopted"),
    ("2025-HB-4003", "HB 4003 of 2025", "Last Action: reported with recommendation"),
]


def test_no_baseline_fails_closed_and_writes_nothing(scraper, cache_dir):
    """Neither automatic option is acceptable on a cold start, so it must refuse.

    Seeding from the sweep would record the site's state as "what we hold" and silently mark
    every already-stale bill current -- on the real corpus that would have buried 187 genuine
    differences including bills that had become Public Acts. Treating all bills as changed would
    be a full walk at MI's 10 rpm WAF cap. So: stop, loudly, and write nothing.
    """
    with pytest.raises(ScrapeError, match="no usable last-action baseline"):
        drive(scraper, ROWS)
    assert _mi_load_last_actions(SESSION) is None
    assert not os.listdir(cache_dir)


def test_empty_baseline_is_not_treated_as_authoritative(scraper, cache_dir):
    """A `{}` baseline must not mean "every bill changed".

    That reading turns a stray or truncated file into ~3,900 per-bill fetches against a
    rate-capped WAF -- a full walk arrived at by accident, which is the one outcome the design
    must never reach on an error path.
    """
    (cache_dir / f"mi_last_actions_{SESSION}.json").write_text("{}")
    assert _mi_load_last_actions(SESSION) is None
    with pytest.raises(ScrapeError, match="no usable last-action baseline"):
        drive(scraper, ROWS)


def test_extraction_shortfall_fails_closed(scraper, cache_dir):
    """If the page lists bills but their last actions stop parsing, refuse to skip anything.

    This is the failure the whole change is most exposed to: a markup change shrinks
    site_actions, changed_nos comes out empty, and the run skips every bill while looking
    perfectly healthy -- the exact silent miss the ticket exists to remove.
    """
    _mi_save_last_actions(SESSION, {"HB4001": "x", "HB4002": "y", "HB4003": "z"})
    broken = [
        ("2025-HB-4001", "HB 4001 of 2025", "Last Action: referred to Committee on Rules"),
        ("2025-HB-4002", "HB 4002 of 2025", "marker gone"),
        ("2025-HB-4003", "HB 4003 of 2025", "marker gone"),
    ]
    with pytest.raises(ScrapeError, match="last actions could be parsed"):
        drive(scraper, broken)


def test_extraction_shortfall_does_not_touch_the_baseline(scraper, cache_dir):
    before = {"HB4001": "x", "HB4002": "y", "HB4003": "z"}
    _mi_save_last_actions(SESSION, before)
    broken = [(f"2025-HB-400{i}", f"HB 400{i} of 2025", "marker gone") for i in (1, 2, 3)]
    with pytest.raises(ScrapeError):
        drive(scraper, broken)
    assert _mi_load_last_actions(SESSION) == before


def test_full_extraction_does_not_trip_the_coverage_guard(scraper, cache_dir):
    # The guard must not fire on a healthy page -- otherwise it converts the fix into an outage.
    _mi_save_last_actions(SESSION, {"HB4001": "referred to committee on rules"})
    assert sorted(drive(scraper, ROWS)) == ["HB 4002", "HB 4003"]


def test_only_bills_whose_last_action_changed_are_scraped(scraper, cache_dir):
    _mi_save_last_actions(SESSION, {
        "HB4001": "referred to committee on rules",   # unchanged
        "HB4002": "introduced by rep smith",          # CHANGED -> now "adopted"
        "HB4003": "reported with recommendation",     # unchanged
    })
    assert drive(scraper, ROWS) == ["HB 4002"]


def test_bill_absent_from_baseline_counts_as_changed(scraper, cache_dir):
    # A newly introduced bill has no baseline entry, so it must be scraped -- this is what
    # replaces the old dateFrom= behaviour for new bills.
    _mi_save_last_actions(SESSION, {"HB4001": "referred to committee on rules"})
    assert sorted(drive(scraper, ROWS)) == ["HB 4002", "HB 4003"]


def test_committee_action_change_is_detected(scraper, cache_dir):
    # The whole point of OPEN-134: a committee report on a pre-existing bill. dateFrom= could
    # never return this, and journals (OPEN-150) do not carry committee reports either.
    _mi_save_last_actions(SESSION, {"HB4003": "referred to Committee on Rules".lower()})
    rows = [("2025-HB-4003", "HB 4003 of 2025",
             "Last Action: reported with recommendation with substitute (H-1)")]
    assert drive(scraper, rows) == ["HB 4003"]


def test_nothing_changed_scrapes_nothing_and_keeps_baseline(scraper, cache_dir):
    before = {
        "HB4001": "referred to committee on rules",
        "HB4002": "adopted",
        "HB4003": "reported with recommendation",
    }
    _mi_save_last_actions(SESSION, before)
    assert drive(scraper, ROWS) == []
    assert _mi_load_last_actions(SESSION) == before


def test_baseline_advances_only_for_bills_actually_scraped(scraper, cache_dir):
    """A bill whose scrape raises must not have its baseline advanced.

    This is the OPEN-152 lesson one level down: a failed run that still records progress makes
    the bill invisible to every later run.
    """
    _mi_save_last_actions(SESSION, {
        "HB4001": "referred to committee on rules",
        "HB4002": "stale one",
        "HB4003": "also stale",
    })

    def boom(session, bill_id, bill_url):
        if bill_id == "HB 4003":
            raise RuntimeError("WAF block")
        return
        yield  # pragma: no cover

    with pytest.raises(RuntimeError):
        drive(scraper, ROWS, scrape_bill=boom)

    after = _mi_load_last_actions(SESSION)
    # The run died, so nothing was written at all -- HB 4002's success is re-detected next run
    # rather than HB 4003's failure being recorded as done.
    assert after["HB4003"] == "also stale"


def test_bill_no_request_does_not_rewrite_the_baseline(scraper, cache_dir):
    """A targeted bill_no= run is a subset, not a statement about the corpus.

    Rewriting the baseline from it would mark every bill it did not ask for as current and hide
    their real changes from the next incremental run.
    """
    before = {"HB4001": "stale", "HB4002": "stale", "HB4003": "stale"}
    _mi_save_last_actions(SESSION, before)
    assert drive(scraper, ROWS, bill_no="HB4002") == ["HB 4002"]
    assert _mi_load_last_actions(SESSION) == before


def test_full_run_scrapes_everything_and_records_whole_sweep(scraper, cache_dir):
    # start=None means a full scrape: no recency filter, and the sweep becomes the new baseline
    # so the next incremental run has something to diff against for free.
    assert len(drive(scraper, ROWS, start=None)) == 3
    assert _mi_load_last_actions(SESSION) == {
        "HB4001": "referred to committee on rules",
        "HB4002": "adopted",
        "HB4003": "reported with recommendation",
    }


def test_search_url_no_longer_sends_a_date_window(scraper, cache_dir):
    """The regression guard for the actual bug: dateFrom= must be empty.

    If a future change reintroduces a date window here, the ~80-bills-a-week hole silently
    reopens and every test above still passes, because they stub the page rather than the URL.
    """
    # A real baseline, not {} -- an empty one now fails closed by design, so it would abort
    # before the URL was ever built and this guard would pass for the wrong reason.
    _mi_save_last_actions(SESSION, {
        "HB4001": "referred to committee on rules",
        "HB4002": "adopted",
        "HB4003": "reported with recommendation",
    })
    seen = {}

    def capture(fn):
        # mi_waf_get is called with a lambda closing over search_url; invoke it against a
        # recording stub to recover the URL actually requested.
        def rec(url, **kwargs):
            seen["url"] = url
            r = mock.Mock()
            r.content = lxml.html.tostring(results_page(ROWS))
            return r
        scraper.get = rec
        return fn(None, "ua")

    with mock.patch.object(mi_bills, "mi_waf_get", capture), \
            mock.patch.object(MIBillScraper, "scrape_bill",
                              lambda *a, **k: iter(())), \
            mock.patch.object(MIBillScraper, "_redirected_single_bill", return_value=None):
        list(scraper.scrape(SESSION, start="2026-08-01"))

    assert "dateFrom=&" in seen["url"], seen["url"]
    assert "dateFrom=2026" not in seen["url"]
