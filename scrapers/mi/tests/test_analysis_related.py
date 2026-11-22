"""OPEN-648: Michigan publishes no companion list; the bills a fiscal agency analyses together ("This document analyzes
HB5152, HB5153") are stored as related links, labelled with the agency's own heading (Ramon, 2026-11-22: "Store as
related").

The fixtures are real Michigan bill pages as the scraper saved them (openstates-scrapers/_cache, fetched by the scheduled
Michigan runs on 2026-06-28 and 2026-08-24), the HTML body unchanged. No live request: Michigan's site is read only the
scraper's way. The expected links are written out by hand from each page's Analysis section:
* HB 5807 of 2026: the Senate Fiscal Agency analyses HB5805, HB5806, HB5807; the House Fiscal Agency the same three
  and, in one document, SB966;
* HJR E of 2025 and HB 4148 of 2025 name each other (a joint resolution's letter, written "HJRE" on the page);
* HB 4961 of 2025: one House Fiscal Agency document analyses HB4180-4183, HB4951, HB4961 and SB578; the Legislative
  Service Bureau's note names only HB 4961 itself;
* SB 714 of 2025: no analysis.
"""
import os
import tempfile

from mi.bills import MIBillScraper

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
HFA = "House Fiscal Agency Analysis"
SFA = "Senate Fiscal Agency Analysis"


def related(monkeypatch, object_name, bill_id, session="2025-2026"):
    with open(os.path.join(FIXTURES, f"open648_{object_name}.html"), "rb") as f:
        body = f.read()

    class FakeResponse:
        content = body

    monkeypatch.setattr("mi.bills.mi_waf_get", lambda request_func: FakeResponse())
    scraper = MIBillScraper(None, tempfile.mkdtemp())
    scraper.scrape_votes = lambda bill, page: iter(())
    url = f"https://legislature.mi.gov/Bills/Bill?ObjectName={object_name}"
    [bill] = list(scraper.scrape_bill(session, bill_id, url))
    return sorted(
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    )


def test_both_agencies_and_a_bill_only_one_names(monkeypatch):
    assert related(monkeypatch, "2026-HB-5807", "HB 5807") == [
        ("HB 5805", "2025-2026", "related", f"{SFA}; {HFA}"),
        ("HB 5806", "2025-2026", "related", f"{SFA}; {HFA}"),
        ("SB 966", "2025-2026", "related", HFA),
    ]


def test_a_joint_resolution_letter_both_ways(monkeypatch):
    assert related(monkeypatch, "2025-HJR-E", "HJR E") == [
        ("HB 4148", "2025-2026", "related", HFA)
    ]
    assert related(monkeypatch, "2025-HB-4148", "HB 4148") == [
        ("HJR E", "2025-2026", "related", HFA)
    ]


def test_a_package_and_the_bill_itself_left_out(monkeypatch):
    assert related(monkeypatch, "2025-HB-4961", "HB 4961") == [
        (f"HB {n}", "2025-2026", "related", HFA)
        for n in ("4180", "4181", "4182", "4183", "4951")
    ] + [("SB 578", "2025-2026", "related", HFA)]


def test_no_analysis_no_link(monkeypatch):
    assert related(monkeypatch, "2025-SB-0714", "SB 714") == []


def test_each_link_keeps_the_session_its_own_link_names(monkeypatch):
    """Every real link names its session (`sessions=2025-2026`), the same as the page's; scraped as another session,
    the links must still say 2025-2026, so the session is read from the link, not copied from the bill."""
    assert [
        r[:2] for r in related(monkeypatch, "2025-HJR-E", "HJR E", session="2023-2024")
    ] == [("HB 4148", "2025-2026")]
