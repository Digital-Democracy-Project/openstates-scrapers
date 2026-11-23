"""OPEN-764: "Mr. Speaker" and "Mr. President" on a Louisiana roll call, in a form the importer can match.

Louisiana roll-call PDFs print the presiding officer of each chamber by title: "Mr. Speaker"
on a House roll call, "Mr. President" on a Senate one. Neither matches a person by name. Who
they are comes from the jurisdiction manifest's votes.house_speaker_by_session and
votes.senate_president_by_session, read by utils/presiding_officers.py (shared with Rhode
Island, OPEN-785), as Idaho (scrapers/id/voter_names.py, OPEN-680), Mississippi
(scrapers/ms/voter_names.py, OPEN-731) and Missouri (scrapers/mo/voter_names.py, OPEN-738)
read the Speaker. There is no built-in table: for a session the manifest does not list, the
title is left as printed (and the scraper warns), so it stays visibly unmatched rather than
going to the wrong person.
"""
from utils import presiding_officers

# printed title -> (the chamber whose roll calls print it, the manifest field naming who it is)
PRESIDING_OFFICERS = {
    "Mr. Speaker": ("lower", "house_speaker_by_session"),
    "Mr. President": ("upper", "senate_president_by_session"),
}


def add_voter(vote, option, name, chamber, session):
    """Record `name`'s vote; a chamber's presiding-officer title gets that session's officer
    as its voter id (the printed name is kept). Returns the manifest field that had no name
    for this session when the title was left unresolved, else None."""
    return presiding_officers.add_voter(
        vote, option, name, chamber, session, "la", PRESIDING_OFFICERS
    )
