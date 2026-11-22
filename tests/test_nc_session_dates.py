"""OPEN-765: North Carolina's 2025 Regular Session ends on the date the legislature's own adjournment resolution sets
(Resolution 2026-6, SJR 1091, section 6: sine die on Friday, December 18, 2026), not on 2026-07-01.

The importer matches a roll call's voter only among people whose seat started before the session's end date
(openstates-core `resolve_person`: `memberships__start_date__lt=end_date`). Sen. Jerry Tillett was sworn in on
2026-09-03 (people data, ncleg.gov member 1003) and voted on 2026-11-17 in this session; with the old end date he was
left out and 5 of his votes were stored with no person. The dates below are written out from those sources.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from test_session_classification import _sessions  # noqa: E402

TILLETT_SWORN_IN = "2026-09-03"
TILLETT_VOTED = "2026-11-17"
SINE_DIE = "2026-12-18"


def _session(identifier):
    [session] = [s for s in _sessions("nc") if s["identifier"] == identifier]
    return session


def test_the_2025_session_ends_on_its_adjournment_resolution_date():
    assert _session("2025")["end_date"] == SINE_DIE


def test_a_senator_sworn_in_during_the_session_is_inside_it():
    session = _session("2025")
    # resolve_person's filter: the seat must start before the session ends
    assert session["start_date"] <= TILLETT_SWORN_IN < session["end_date"]
    assert TILLETT_SWORN_IN <= TILLETT_VOTED <= session["end_date"]
