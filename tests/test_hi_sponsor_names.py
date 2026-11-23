"""OPEN-805: Hawaii's sponsor list keeps "SURNAME, I." as one sponsor, and a governor's message is
sponsored by the Governor's office.

The measure page's "Introducer(s)" is one comma-separated list, and a member who shares a surname is
written with an initial in the same list ("MIYAKE, AMATO, ..., KUSCH, LEE, M., SOUZA"), so splitting on
every comma made "LEE" and "M." two sponsors, neither of them a person (Hawaii's first scrape, 2026:
"LEE" 584, "C." 295, "M." 289 unmatched). The initial is joined back to the name before it, the rule
split_specific_votes already uses for roll calls, with no member's name in the code (Ramon,
2026-11-23, OPEN-802).

A GM is a governor's message; its sponsor was the person "governor", who matched no one (596). It is
now the organization "Office of the Governor", Hawaii's executive organization in core's metadata, as
Massachusetts names its governor's bills.

Fixtures (tests/fixtures/hi_open805/): the 2026 measure pages of HB 1180 and GM 1101 on
data.capitol.hawaii.gov (session/measure_indiv.aspx?billtype=..&billnumber=..&year=2026), saved
2026-11-23, scripts, styles and hidden form fields removed.
"""
import logging
import os
import sys

import lxml.html
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import hi  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open805")


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def scraper(pages):
    s = object.__new__(HIBillScraper)
    s.jurisdiction = hi.Hawaii()
    s.short_ids = {}
    s.members = {}
    s.logger = logging.getLogger("test")
    s.info = s.warning = s.error = s.logger.info

    def get(url, **kw):
        for key, text in pages.items():
            if key in url:
                return type("Response", (), {"text": text})
        raise AssertionError(f"unexpected request {url}")

    s.get = get
    return s


def bill_of(page, billtype, number):
    url = (
        "https://capitol.hawaii.gov/session/measure_indiv.aspx?"
        f"billtype={billtype}&billnumber={number}&year=2026"
    )
    out = scraper({f"billnumber={number}": page}).scrape_bill(
        "2026", "lower" if billtype == "HB" else "upper", "bill", url
    )
    (bill,) = [o for o in out if isinstance(o, Bill)]
    return bill


def sponsors(bill):
    return [
        (s["name"], s["entity_type"], s["classification"]) for s in bill.sponsorships
    ]


def introducers(text):
    table = lxml.html.fromstring(
        "<table><tr><th>Introducer(s):</th><td>" + text + "</td></tr></table>"
    )
    meta = HIBillScraper.parse_bill_metainf_table(object.__new__(HIBillScraper), table)
    return meta["Introducer(s)"]


def test_hb1180_keeps_lee_m_as_one_sponsor():
    bill = bill_of(read("HB1180-2026.html"), "HB", 1180)
    assert sponsors(bill) == [
        (name, "person", "primary")
        for name in [
            "MIYAKE",
            "AMATO",
            "KEOHOKAPU-LEE LOY",
            "KILA",
            "KUSCH",
            "LEE, M.",
            "SOUZA",
        ]
    ]


def test_a_governors_message_is_sponsored_by_the_governors_office():
    bill = bill_of(read("GM1101-2026.html"), "GM", 1101)
    assert sponsors(bill) == [("Office of the Governor", "organization", "primary")]
    assert bill.sponsorships[0]["organization_id"] == (
        '~{"name": "Office of the Governor"}'
    )
    assert bill.sponsorships[0]["person_id"] is None


@pytest.mark.parametrize(
    "text,expected",
    [
        # synthetic names that appear nowhere in the code: the rule is the shape, not a member
        ("QUOLL, ZEBEDEE, Q., WOMBAT", ["QUOLL", "ZEBEDEE, Q.", "WOMBAT"]),
        ("ZEBEDEE, Q., ZEBEDEE, X.", ["ZEBEDEE, Q.", "ZEBEDEE, X."]),
        ("Quoll, Zebedee, X.", ["Quoll", "Zebedee, X."]),
        ("ZEBEDEE, Q", ["ZEBEDEE, Q"]),
        (
            "QUOLL, ZEBEDEE, Q. (Introduced by request of another party)",
            ["QUOLL", "ZEBEDEE, Q. (Introduced by request of another party)"],
        ),
        # a surname, even a short one, is not an initial
        ("QUOLL, OI, WOMBAT", ["QUOLL", "OI", "WOMBAT"]),
        ("QUOLL", ["QUOLL"]),
        ("", [""]),
    ],
)
def test_an_initial_stays_with_the_name_before_it(text, expected):
    assert introducers(text) == expected


def test_the_split_initials_are_gone_and_nothing_is_counted_twice():
    names = introducers("MIYAKE, AMATO, KEOHOKAPU-LEE LOY, KILA, KUSCH, LEE, M., SOUZA")
    assert len(names) == len(set(names)) == 7
    assert not [n for n in names if n.rstrip(".").isalpha() and len(n) <= 2]
