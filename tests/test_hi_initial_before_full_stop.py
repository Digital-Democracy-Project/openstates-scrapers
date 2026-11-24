"""OPEN-879: a committee roll call's last name keeps one initial, not an initial and a stray "C.".

The measure page ends a list of names with a full stop, so a member who shares a surname and ends the list is
written "Lee, C.." (initial, then the list's full stop). That "C.." was not an initial, so the blind ", " split left
"Lee" and "C." as two voters: "C." matched no one (147 stored roll-call votes on the Mac replica, 2026-11-24, "M." 30
the same way) and a third name was stored for a roll call that excused two. The two full stops are read as one, with no
member's name in the code.

Text: the WAM committee vote on SB 964 of 2026 (data.capitol.hawaii.gov, session/measure_indiv.aspx?billtype=SB&
billnumber=964&year=2026, 2/28/2025), read 2026-11-24.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import hi  # noqa: E402
from hi.bills import HIBillScraper, split_specific_votes  # noqa: E402

SB964_WAM = (
    "The committee(s) on WAM recommend(s) that the measure be PASSED, UNAMENDED. The votes in WAM were as follows: "
    "11 Aye(s): Senator(s) Dela Cruz, Moriwaki, Aquino, DeCoite, Elefante, Hashimoto, Inouye, Kanuha, Kim, Wakai, "
    "Fevella; Aye(s) with reservations: none ; 0 No(es): none; and 2 Excused: Senator(s) Kidani, Lee, C.."
)


def scraper():
    s = object.__new__(HIBillScraper)
    s.jurisdiction = hi.Hawaii()
    s.logger = logging.getLogger("test")
    return s


def test_an_initial_followed_by_the_lists_full_stop_stays_with_its_surname():
    s = scraper()
    parsed, _motion = s.parse_vote(SB964_WAM)
    names = [s.clean_voter_name(n) for n in split_specific_votes(parsed["excused"])]
    assert names == ["Kidani", "Lee, C"]  # the same name as a "Lee, C." mid-list, once its full stop is cleaned
    assert len(names) == int(parsed["n_excused"])


def test_a_double_stop_is_one_stop_and_the_other_shapes_are_unchanged():
    assert split_specific_votes("Senator(s) Kidani, Lee, C..") == ["Kidani", "Lee, C."]
    assert split_specific_votes("Senator(s) Lee, C., Kidani") == ["Lee, C.", "Kidani"]  # mid-list, as before
    assert split_specific_votes("Senator(s) Kidani, Lee, C") == ["Kidani", "Lee, C"]
    assert split_specific_votes("Representative(s) Alcos, Garcia..") == ["Alcos", "Garcia."]
