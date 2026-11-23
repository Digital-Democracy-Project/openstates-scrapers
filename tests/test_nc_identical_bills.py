"""OPEN-783: North Carolina's bill page heading links the bill filed identical to this one after "=", e.g. 2025
"House Bill 133 / SL 2026-54 (=S504)". Ramon, 2026-11-23 ("As companions", OPEN-651): it is stored as a companion
(D1, "Identical"), labelled "=". The heading names the bill by chamber and number only ("S504"); its stored id
("SB 504") comes from the session's own bill lists (FiledBillsFeed), never a guessed type.

The fixtures are ncleg.gov's own answers, fetched 2026-11-23, unchanged except that the two 2025 FiledBillsFeed files
are cut to the bills used here plus one resolution and one joint resolution per chamber, in their real order. The
expected links are written out by hand from each page's heading:
* 2025 H 133: "(=S504)" (House to Senate);
* 2025 S 375: "(=H632)" (Senate to House);
* 2023 S 44: "(=S417)" (both Senate);
* 2025 H 58: no "=" (its heading's only other links are the previous/next arrows, H57 and H59).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from nc.bills import NCBillScraper, stored_bill_id  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nc_open783")


def read(name, mode="r"):
    with open(os.path.join(FIXTURES, name), mode) as f:
        return f.read()


class _Response:
    def __init__(self, name):
        self.text = read(name)
        self.content = read(name, "rb")


def companions(session, nc_id, bill_type, stored_ids, warnings=None):
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    scraper._stored_ids = stored_ids
    if warnings is not None:
        scraper.warning = warnings.append
    scraper.get = lambda url, **kwargs: _Response(f"BillLookUp_{session}_{nc_id}.html")
    scraper.scrape_actions = lambda bill, doc: None
    scraper.scrape_votes = lambda bill, doc: iter(())
    chamber = "House" if nc_id.startswith("H") else "Senate"
    [bill] = list(scraper.scrape_bill(chamber, session, nc_id, bill_type, "t"))
    return [
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    ]


def stored_ids_2025():
    """The map scrape() builds, from the two real (cut) 2025 feeds."""
    scraper = NCBillScraper(jurisdiction="nc", datadir="/tmp")
    scraper.get = lambda url, **kwargs: _Response(
        f"FiledBillsFeed_2025_{url.rstrip('/').split('/')[-1]}.xml"
    )
    scraper.scrape_chamber = lambda chamber, session: iter(())
    list(scraper.scrape(session="2025"))
    return scraper._stored_ids


def test_the_session_lists_name_each_bill_as_stored():
    assert stored_ids_2025() == {
        "S1093": "SR 1093",
        "S1091": "SJR 1091",
        "S504": "SB 504",
        "S375": "SB 375",
        "H1248": "HJR 1248",
        "H1245": "HR 1245",
        "H632": "HB 632",
        "H133": "HB 133",
        "H58": "HB 58",
    }


def test_a_house_bill_identical_to_a_senate_bill_is_a_companion():
    assert companions("2025", "H133", "B", stored_ids_2025()) == [
        ("SB 504", "2025", "companion", "=")
    ]


def test_a_senate_bill_identical_to_a_house_bill_is_a_companion():
    assert companions("2025", "S375", "B", stored_ids_2025()) == [
        ("HB 632", "2025", "companion", "=")
    ]


def test_two_senate_bills_filed_identical_are_companions_too():
    assert companions("2023", "S44", "B", {"S417": "SB 417", "S44": "SB 44"}) == [
        ("SB 417", "2023", "companion", "=")
    ]


def test_no_mark_no_link_and_the_navigation_arrows_are_not_read():
    # the arrows' bills are in the lists here, so reading them would make links
    known = dict(stored_ids_2025(), H57="HB 57", H59="HB 59")
    assert companions("2025", "H58", "B", known) == []


def test_a_bill_missing_from_the_lists_is_not_guessed():
    warnings = []
    assert companions("2025", "H133", "B", {"H133": "HB 133"}, warnings) == []
    # pm-review: it is reported, naming both bills, not dropped in silence
    assert warnings == [
        "HB 133: identical bill 'S504' is not in the session's bill lists"
    ]


def test_the_stored_id_keeps_each_kind_of_instrument():
    assert stored_bill_id("S504", "B") == ("SB 504", "bill")
    assert stored_bill_id("S1093", "R") == ("SR 1093", "resolution")
    assert stored_bill_id("H1248", "JR") == ("HJR 1248", "joint resolution")


def test_a_bill_is_never_its_own_companion():
    # a list that answered "=S504" with the bill itself must not link it to itself
    assert companions("2025", "H133", "B", {"S504": "HB 133", "H133": "HB 133"}) == []
