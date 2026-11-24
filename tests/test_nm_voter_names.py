"""OPEN-818: New Mexico's Senate roll calls print two senators with a generational suffix after a comma
("POPE, JR.", "SHENDO, JR."), so their 218 person votes matched no one. The scraper now drops a trailing
JR / SR / II / III / IV (with or without a period, any case) and leaves House names, which put initials
after the comma ("Chavez, N.", "Hernandez, JF", "García, MP"), as printed.

The PDFs in fixtures/nm_open685 are nmlegis.gov's own, unchanged (HB 253 Senate RCS 158 and 173, HB 164
House RCS 128, 2026 Regular Session).
"""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from nm.votes import NMVoteScraper, voter_name  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nm_open685")


@pytest.mark.parametrize(
    "printed,stored",
    [
        ("POPE, JR.", "POPE"),
        ("SHENDO, JR.", "SHENDO"),
        ("SMITH, III", "SMITH"),
        ("Smith, Sr.", "Smith"),
        ("SMITH,JR", "SMITH"),
        ("Smith, ii", "Smith"),
        ("SMITH, IV.", "SMITH"),
        ("SMITH, JR. ", "SMITH"),
    ],
)
def test_trailing_generational_suffix_is_dropped(printed, stored):
    assert voter_name(printed) == stored


@pytest.mark.parametrize(
    "name",
    [
        "Chavez, N.",
        "Hernandez, JF",
        "García, MP",
        "O'MALLEY",
        "SEDILLO-LOPEZ",
        "WIRTH",
        "Romero, GA",
        "JRUSSELL",  # a suffix-like start with no comma is part of the name
        "SRINIVASAN",
    ],
)
def test_other_names_are_unchanged(name):
    assert voter_name(name) == name


def _voters(fname, chamber):
    doc = fitz.open(os.path.join(FIXTURES, fname))
    scraper = NMVoteScraper(jurisdiction="x", datadir="/tmp")
    vote = scraper.parse_vote(
        doc,
        f"https://www.nmlegis.gov/Sessions/26%20Regular/votes/{fname}",
        "2026",
        "HB 253",
        chamber,
    )
    return [v["voter_name"] for v in vote.votes]


@pytest.mark.parametrize("fname", ["HB0253SVOTE.PDF", "HB0253SVOTE2.PDF"])
def test_senate_pdf_stores_surname_without_suffix(fname):
    names = _voters(fname, "upper")
    assert "POPE" in names and "SHENDO" in names
    assert not [n for n in names if "," in n]
    assert len(names) == len(set(names))


def test_house_pdf_keeps_initials_after_comma():
    names = _voters("HB0164HVOTE.PDF", "lower")
    for printed in [
        "Chavez, N.",
        "Hernandez, JF",
        "García, MP",
        "Romero, GA",
        "Martínez, J.",
    ]:
        assert printed in names
