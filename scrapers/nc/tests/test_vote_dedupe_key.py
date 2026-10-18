"""OPEN-397: an NC extra session must not reuse the regular session's vote keys.
Run: python3 -m pytest scrapers/nc/tests/test_vote_dedupe_key.py"""
from scrapers.nc.bills import vote_dedupe_key


def test_extra_session_key_differs_from_regular_session_key():
    assert vote_dedupe_key("2025E1", "[S]-1") != vote_dedupe_key("2025", "[S]-1")


def test_regular_session_key_is_unchanged_so_stored_votes_keep_their_keys():
    assert vote_dedupe_key("2025", "[S]-1") == "[S]-1"


def test_every_extra_session_is_qualified():
    keys = {vote_dedupe_key(s, "[H]-7") for s in ("2003E1", "2003E3", "2025E1", "2025E12")}
    assert len(keys) == 4
