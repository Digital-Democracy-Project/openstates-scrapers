"""OPEN-731: "Mr. Speaker" on a Mississippi House roll call, in a form the importer can match.

Mississippi House roll calls print the presiding Speaker as "Mr. Speaker", which matches no
person by name. Who that is comes from the jurisdiction manifest's
votes.house_speaker_by_session, as Idaho does (scrapers/id/voter_names.py, OPEN-680). There
is no built-in table: for a session the manifest does not list, the name is left as printed,
so it stays visibly unmatched rather than going to the wrong person.
"""
from openstates.utils import _make_pseudo_id
from openstates.utils.ddp_manifest import manifest_value


def house_speaker_by_session():
    # session keys as strings: an unquoted 2026 in the manifest is read as a number
    speakers = manifest_value("ms", "votes.house_speaker_by_session", {})
    return {str(session): name for session, name in speakers.items()}


def add_voter(vote, option, name, chamber, session):
    """Record `name`'s vote; "Mr. Speaker" on a House roll call gets the session's Speaker
    as its voter id (the printed name is kept)."""
    vote.vote(option, name)
    if name == "Mr. Speaker" and chamber == "lower":
        speaker = house_speaker_by_session().get(str(session))
        if speaker:
            vote.votes[-1]["voter_id"] = _make_pseudo_id(name=speaker)
