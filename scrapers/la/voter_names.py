"""OPEN-764: "Mr. Speaker" and "Mr. President" on a Louisiana roll call, in a form the importer can match.

Louisiana roll-call PDFs print the presiding officer of each chamber by title: "Mr. Speaker"
on a House roll call, "Mr. President" on a Senate one. Neither matches a person by name. Who
they are comes from the jurisdiction manifest's votes.house_speaker_by_session and
votes.senate_president_by_session, as Idaho (scrapers/id/voter_names.py, OPEN-680),
Mississippi (scrapers/ms/voter_names.py, OPEN-731) and Missouri (scrapers/mo/voter_names.py,
OPEN-738) read the Speaker. There is no built-in table: for a session the manifest does not
list, the title is left as printed (and the scraper warns), so it stays visibly unmatched
rather than going to the wrong person.
"""
from openstates.utils import _make_pseudo_id
from openstates.utils.ddp_manifest import manifest_value

# printed title -> (the chamber whose roll calls print it, the manifest field naming who it is)
PRESIDING_OFFICERS = {
    "Mr. Speaker": ("lower", "house_speaker_by_session"),
    "Mr. President": ("upper", "senate_president_by_session"),
}


def officer_by_session(field):
    # session keys as strings: an unquoted 2026 in the manifest is read as a number
    officers = manifest_value("la", "votes." + field, {})
    return {str(session): name for session, name in officers.items()}


def add_voter(vote, option, name, chamber, session):
    """Record `name`'s vote; a chamber's presiding-officer title gets that session's officer
    as its voter id (the printed name is kept). Returns the manifest field that had no name
    for this session when the title was left unresolved, else None."""
    vote.vote(option, name)
    officer_chamber, field = PRESIDING_OFFICERS.get(name, (None, None))
    if officer_chamber != chamber:
        return None
    officer = officer_by_session(field).get(str(session))
    if not officer:
        return field
    vote.votes[-1]["voter_id"] = _make_pseudo_id(name=officer)
    return None
