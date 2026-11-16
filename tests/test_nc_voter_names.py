"""OPEN-234: NC roll-call names keep the space in two-word names ("John Lowery", not "JohnLowery").

The fixtures are two real ncleg.gov roll-call transcript pages, saved 2026-11-15:
2025 session House roll call 690 and 2025E1 House roll call 7."""
import os
from collections import Counter

import lxml.html

from nc.bills import roll_call_votes

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "nc_open234")


def votes(filename):
    with open(os.path.join(FIXTURES, filename), encoding="utf-8") as f:
        return list(roll_call_votes(lxml.html.fromstring(f.read())))


def test_two_word_names_keep_their_space():
    found = votes("rollcall_2025_H_690.html")
    assert ("yes", "Carson Smith") in found
    assert ("no", "Charles Smith") in found
    assert ("no", "von Haefen") in found
    assert ("absent", "John Lowery") in found
    names = [name for _, name in found]
    for squashed in ("CarsonSmith", "CharlesSmith", "vonHaefen", "JohnLowery"):
        assert squashed not in names


def test_every_name_on_the_page_is_counted_once_per_vote_type():
    # counted by hand from the pages' name lines (names separated by "; "). The pages' own printed totals
    # differ (690 prints 71 ayes and 44 noes for 70 and 43 listed names; 2025E1 7 prints 11 not voting for 9),
    # so they cannot be the reference.
    assert Counter(t for t, _ in votes("rollcall_2025_H_690.html")) == {
        "yes": 70,
        "no": 43,
        "absent": 5,
    }
    assert Counter(t for t, _ in votes("rollcall_2025E1_H_7.html")) == {
        "yes": 62,
        "no": 40,
        "not voting": 9,
        "absent": 7,
    }


def test_names_that_already_resolved_are_unchanged():
    found = votes("rollcall_2025E1_H_7.html")
    # "(Speaker)" dropped with no trailing space; initials and hyphens as before
    assert ("yes", "D. Hall") in found
    assert ("yes", "John Lowery") in found
    assert ("no", "G. Pierce") in found
    assert ("no", "Johnson-Hostler") in found
    assert ("yes", "Par\u00e9") in found
    assert ("no", "Helfrich") in found
    assert all(name == name.strip() and name for _, name in found)
