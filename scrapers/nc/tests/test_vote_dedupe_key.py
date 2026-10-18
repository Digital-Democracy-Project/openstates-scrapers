"""OPEN-397: no NC session may reuse another session's vote keys.
Run: PYTHONPATH=scrapers python3 -m pytest scrapers/nc/tests/test_vote_dedupe_key.py"""
from scrapers.nc.bills import vote_dedupe_key


def test_extra_session_key_is_the_session_plus_the_number():
    assert vote_dedupe_key("2025E1", "[S]-1") == "2025E1-[S]-1"


def test_2025_keeps_the_bare_number_so_stored_votes_keep_their_keys():
    assert vote_dedupe_key("2025", "[S]-1") == "[S]-1"


def test_next_regular_session_does_not_collide_with_2025():
    assert vote_dedupe_key("2027", "[S]-1") == "2027-[S]-1"


def test_same_number_in_every_session_gives_distinct_keys():
    sessions = ("2025", "2025E1", "2027", "2027E1")
    assert len({vote_dedupe_key(s, "[H]-7") for s in sessions}) == 4
