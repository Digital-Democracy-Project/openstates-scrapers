"""OPEN-649: Arizona names a bill's own links in its bill feed (NowPartOf), e.g. "Identical to SB 1278; See HBs 2125
and 2141; SBs 1098 and 1279". "Identical to" is a companion (Ramon, 2026-11-20, "Yes, same rule"), "See" is related,
each with azleg's own words as the label.

The fixtures are azleg's own answers (apps.azleg.gov/api/Bill, session 130 = 57th-2nd-regular), fetched 2026-11-23,
unchanged. The expected links are written out by hand from each file's NowPartOf:
* HB 2042: "Identical to SB 1278; See HBs 2125 and 2141; SBs 1098 and 1279" (SB 1278 names HB 2042 back);
* HB 2001: twenty "See" bills over three clauses, one of them a concurrent resolution ("HCR 2016");
* HCR 2004: "Identical to SCR 1004";
* SB 1741: "See SBs 1694" (a plural with one number);
* HB 2135: none.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from az import Arizona  # noqa: E402
from az.bills import AZBillScraper, now_part_of_links  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "az_open649")
SESSION = "57th-2nd-regular"


def page(number):
    with open(os.path.join(FIXTURES, f"{number}.json")) as f:
        return json.load(f)


class _Response:
    def __init__(self, data):
        self.content = json.dumps(data).encode("utf-8")


def related(number):
    """The links scrape_bill stores for one bill, its feed answer being the fixture."""
    scraper = AZBillScraper(Arizona(), "/tmp/")
    scraper.get = lambda url, **kwargs: _Response(page(number))
    scraper.scrape_versions_and_documents = lambda bill, internal_id: None
    scraper.scrape_sponsors = lambda bill, internal_id: None
    scraper.scrape_subjects = lambda bill, internal_id: None
    scraper.scrape_votes = lambda bill, page: iter(())
    chamber = "lower" if number.startswith("H") else "upper"
    [bill] = list(scraper.scrape_bill(chamber, SESSION, number, 130))
    return [
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    ]


def see(*identifiers):
    return [(i, SESSION, "related", "See") for i in identifiers]


def test_identical_is_a_companion_and_see_is_related_both_ways():
    assert related("HB2042") == [
        ("SB 1278", SESSION, "companion", "Identical to")
    ] + see("HB 2125", "HB 2141", "SB 1098", "SB 1279")
    assert related("SB1278") == [
        ("HB 2042", SESSION, "companion", "Identical to")
    ] + see("HB 2125", "HB 2141", "SB 1098", "SB 1279")


def test_a_long_see_list_over_several_clauses_and_bill_types():
    assert related("HB2001") == see(
        *[
            f"HB {n}"
            for n in (2221, 2366, 2505, 2506, 2510, 2511, 2628, 2654, 2907, 4058, 4060)
        ],
        "HCR 2016",
        *[f"SB {n}" for n in (1229, 1262, 1344, 1358, 1568, 1687, 1746, 1791)],
    )


def test_a_resolution_and_a_plural_with_one_number():
    assert related("HCR2004") == [("SCR 1004", SESSION, "companion", "Identical to")]
    assert related("SB1741") == see("SB 1694")


def test_no_links_no_related_bills():
    assert related("HB2135") == []


def test_the_bill_itself_and_a_repeat_are_left_out():
    scraper = AZBillScraper(Arizona(), "/tmp/")
    data = dict(
        page("HB2042"), NowPartOf="Identical to HB 2042; See SB 1278; SBs 1278 and 1098"
    )
    scraper.get = lambda url, **kwargs: _Response(data)
    scraper.scrape_versions_and_documents = lambda bill, internal_id: None
    scraper.scrape_sponsors = lambda bill, internal_id: None
    scraper.scrape_subjects = lambda bill, internal_id: None
    scraper.scrape_votes = lambda bill, page: iter(())
    [bill] = list(scraper.scrape_bill("lower", SESSION, "HB2042", 130))
    assert [(r["identifier"], r["relation_type"]) for r in bill.related_bills] == [
        ("SB 1278", "related"),
        ("SB 1098", "related"),
    ]


def test_a_bill_named_both_ways_is_a_companion_where_it_first_appears():
    # pm-review: "Identical to" wins over "See" whatever the order
    links, _ = now_part_of_links("See SB 5 and 6; Identical to SB 5")
    assert links == [("SB 5", "companion", "Identical to"), ("SB 6", "related", "See")]
    links, _ = now_part_of_links("Identical to SB 5; See SBs 5 and 6")
    assert links == [("SB 5", "companion", "Identical to"), ("SB 6", "related", "See")]


def test_a_clause_in_another_form_is_not_guessed():
    # an unknown lead word: its bills are not read, and the next known kind starts afresh
    links, unread = now_part_of_links("See HB 9; Similar to HB 1; SB 2; See HB 3")
    assert links == [("HB 9", "related", "See"), ("HB 3", "related", "See")]
    assert unread == ["Similar to HB 1", "SB 2"]
    assert now_part_of_links(None) == ([], [])
    assert now_part_of_links("") == ([], [])
