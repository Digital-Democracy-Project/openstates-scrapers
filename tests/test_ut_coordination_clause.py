"""OPEN-775: Utah publishes no companion list; the only other bills a bill names are in its summary's coordination
clause. Ramon, 2026-11-23 ("Store as related"): each is stored as a related link (never a companion), labelled
"coordination clause".

The fixtures are le.utah.gov's own bill data files (/data/2026GS/<bill>.json, the files the scraper reads), fetched
2026-11-23, unchanged. The expected links are written out by hand from each file's highlightedProvisions:
* HB 223: "includes a coordination clause to standardize a defined term in this bill with the same term in H.B. 32,
  Signature Gathering and Verification Amendments";
* SB 153: "provides a coordination clause to merge provisions of this bill with H.B. 209, Voting Amendments, and
  H.B. 361, Elections Provisions Amendments";
* HB 27: no coordination clause.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from ut import Utah  # noqa: E402
from ut.bills import UTBillScraper, coordination_clause_bills  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ut_open775")


class _Response:
    def __init__(self, content):
        self.content = content


def related(filename, identifier, chamber):
    with open(os.path.join(FIXTURES, f"{filename}.json"), "rb") as f:
        body = f.read()
    scraper = UTBillScraper(Utah(), "/tmp/")
    scraper._start = None
    scraper.get = lambda url, **kwargs: _Response(body)
    # the method is a generator (it yields the bill's votes); vote pages are another fetch, not read here
    scraper.parse_html_vote = lambda *args, **kwargs: iter(())
    bill = Bill(identifier, legislative_session="2026", title="t", chamber=chamber)
    list(
        scraper.scrape_bill_details_from_api(
            bill, f"https://le.utah.gov/~2026/bills/static/{filename}.html", "2026GS"
        )
    )
    return [
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    ]


def test_a_clause_naming_one_bill():
    assert related("HB0223", "HB 223", "lower") == [
        ("HB 32", "2026", "related", "coordination clause")
    ]


def test_a_clause_naming_two_bills():
    assert related("SB0153", "SB 153", "upper") == [
        ("HB 209", "2026", "related", "coordination clause"),
        ("HB 361", "2026", "related", "coordination clause"),
    ]


def test_no_clause_no_link():
    assert related("HB0027", "HB 27", "lower") == []


def test_only_the_coordination_clause_bullet_is_read():
    provisions = (
        "This bill:<hr><ltbullet>amends a provision enacted by H.B. 5, 2025 General Session;"
        "<hr><ltbullet>provides a coordination clause to merge provisions of this bill with S.J.R. 3, "
        "H.C.R. 12, H.R. 2, S.R. 4 and S.B. 0045; and<hr><ltbullet>makes technical changes."
    )
    # every resolution kind, a leading zero, and a bill named outside the clause left out
    assert coordination_clause_bills(provisions) == [
        "SJR 3",
        "HCR 12",
        "HR 2",
        "SR 4",
        "SB 45",
    ]
    assert coordination_clause_bills(None) == []


def test_the_link_is_in_the_bills_own_session():
    # pm-review: a 2025 bill's clause links 2025 bills
    with open(os.path.join(FIXTURES, "HB0223.json"), "rb") as f:
        body = f.read()
    scraper = UTBillScraper(Utah(), "/tmp/")
    scraper._start = None
    scraper.get = lambda url, **kwargs: _Response(body)
    scraper.parse_html_vote = lambda *args, **kwargs: iter(())
    bill = Bill("HB 223", legislative_session="2025", title="t", chamber="lower")
    list(scraper.scrape_bill_details_from_api(bill, "https://x/HB0223.html", "2025GS"))
    assert [
        (r["identifier"], r["legislative_session"]) for r in bill.related_bills
    ] == [("HB 32", "2025")]


def test_the_bill_itself_and_a_repeat_are_left_out():
    provisions = (
        "<ltbullet>provides a coordination clause with H.B. 223 and H.B. 32;<hr>"
        "<ltbullet>provides a coordination clause to merge with H.B. 32"
    )
    assert coordination_clause_bills(provisions) == ["HB 223", "HB 32"]
    scraper = UTBillScraper(Utah(), "/tmp/")
    scraper._start = None
    scraper.get = lambda url, **kwargs: _Response(
        ('{"highlightedProvisions": "%s"}' % provisions).encode()
    )
    bill = Bill("HB 223", legislative_session="2026", title="t", chamber="lower")
    list(scraper.scrape_bill_details_from_api(bill, "https://x/HB0223.html", "2026GS"))
    assert [r["identifier"] for r in bill.related_bills] == ["HB 32"]
