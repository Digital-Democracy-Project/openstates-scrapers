"""OPEN-738: "MR SPEAKER" on a Missouri House roll call, in a form the importer can match.

Missouri House roll-call PDFs (scrapers/mo/votes.py, OPEN-696) print the presiding Speaker
as "MR SPEAKER", which matches no person by name. Who that is comes from the jurisdiction
manifest's votes.house_speaker_by_session, as Idaho (scrapers/id/voter_names.py, OPEN-680)
and Mississippi (scrapers/ms/voter_names.py, OPEN-731) do. There is no built-in table: for
a session the manifest does not list, the name is left as printed, so it stays visibly
unmatched rather than going to the wrong person.
"""
from openstates.utils import _make_pseudo_id
from openstates.utils.ddp_manifest import manifest_value


def house_speaker_by_session():
    # session keys as strings: an unquoted 2026 in the manifest is read as a number
    speakers = manifest_value("mo", "votes.house_speaker_by_session", {})
    return {str(session): name for session, name in speakers.items()}


def add_voter(vote, option, name, chamber, session):
    """Record `name`'s vote; "MR SPEAKER" on a House roll call gets the session's Speaker
    as its voter id (the printed name is kept)."""
    vote.vote(option, name)
    if name == "MR SPEAKER" and chamber == "lower":
        speaker = house_speaker_by_session().get(str(session))
        if speaker:
            vote.votes[-1]["voter_id"] = _make_pseudo_id(name=speaker)
