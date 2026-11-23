"""
Regression test for the OK vote-roll name reader.

Real OK vote pages print names in fixed-width Courier columns padded with
spaces (Word's mso-spacerun runs), so two names are always two or more
spaces apart while the words of one entry ("Mr. Speaker", "West (T)", a
surname of several words) are one space apart (OPEN-802, measured on all
3,741 vote pages of 2025-2026). `extract_names` splits on those column gaps
and stops at the declared count, so trailing free text (e.g. "STRIKE THE
TITLE - ADOPTED" after a zero-count section) never gets mistaken for a vote.
The lines below keep the pages' real column spacing.
"""

from ..bills import extract_names


def test_plain_names():
    line = "Baker              Bashore            Bennett            Blancett"
    assert extract_names(line, 4) == ["Baker", "Bashore", "Bennett", "Blancett"]


def test_parenthetical_disambiguator_stays_attached():
    line = "Caldwell (C)       Humphrey           Pae                Turner"
    assert extract_names(line, 4) == ["Caldwell (C)", "Humphrey", "Pae", "Turner"]


def test_mr_speaker_is_one_name():
    line = "Dobrinski          Martinez           Sims               Mr. Speaker"
    assert extract_names(line, 4) == ["Dobrinski", "Martinez", "Sims", "Mr. Speaker"]


def test_apostrophe_and_hyphen_names():
    line = "O'Donnell          Alonso-Sandoval"
    assert extract_names(line, 2) == ["O'Donnell", "Alonso-Sandoval"]


def test_extract_names_stops_at_declared_limit():
    # Real example: a zero-count "CONSTITUTIONAL PRIVILEGE" section is
    # sometimes followed by trailing outcome text before the "*****"
    # separator. A declared limit of 0 must yield zero fake "votes".
    assert extract_names("STRIKE THE TITLE - ADOPTED", 0) == []


def test_extract_names_caps_at_limit_not_line_contents():
    # If a line has more names than the declared count still needs, only
    # take what's left.
    line = "Dobrinski          Martinez           Sims               Mr. Speaker"
    assert extract_names(line, 3) == ["Dobrinski", "Martinez", "Sims"]


if __name__ == "__main__":
    test_plain_names()
    test_parenthetical_disambiguator_stays_attached()
    test_mr_speaker_is_one_name()
    test_apostrophe_and_hyphen_names()
    test_extract_names_stops_at_declared_limit()
    test_extract_names_caps_at_limit_not_line_contents()
    print("ok")
