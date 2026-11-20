"""OPEN-680: the names Idaho roll calls print, in a form the importer can match.

openstates-core's `resolve_person` matches a bare voter name case-insensitively against a
person's `name`, `other_names` or `family_name`; any other pseudo-id spec it turns into a
database filter on the person, among members of the vote's chamber serving that session.
Idaho's House vote lists print two kinds of names that match no one by name:

* "Crane(12)", "Tanner(14)": the district, printed to tell same-surname members apart
  (the House has two Cranes and two Tanners). The name is kept as printed and the voter
  id asks for the member with that family name holding a seat in that district. House
  seats are "12A"/"12B", Senate seats "12", so the seat label is the district number
  followed by at most one letter ("1" never matches "12A").
* "Mr. Speaker": who that is comes from the jurisdiction manifest's
  votes.house_speaker_by_session (as Massachusetts does, scrapers/ma/voter_names.py).
  There is no built-in table: for a session the manifest does not list, the name is left
  as printed, so it stays visibly unmatched rather than going to the wrong person.
"""
import re

from openstates.utils import _make_pseudo_id
from openstates.utils.ddp_manifest import manifest_value

_DISTRICT_RE = re.compile(r"^(?P<surname>.+?)\s*\((?P<district>\d+)\)$")


def house_speaker_by_session():
    # session keys as strings: an unquoted 2026 in the manifest is read as a number
    speakers = manifest_value("id", "votes.house_speaker_by_session", {})
    return {str(session): name for session, name in speakers.items()}


def voter_pseudo_id(name, chamber, session):
    """The voter id for a name printed on an Idaho roll call of `chamber` in `session`."""
    match = _DISTRICT_RE.match(name)
    if match:
        return _make_pseudo_id(
            family_name__iexact=match.group("surname"),
            memberships__post__label__regex=r"^{}[A-Z]?$".format(
                int(match.group("district"))
            ),
        )
    if name == "Mr. Speaker" and chamber == "lower":
        speaker = house_speaker_by_session().get(str(session))
        if speaker:
            return _make_pseudo_id(name=speaker)
    return _make_pseudo_id(name=name)


def add_voter(vote, option, name, chamber, session):
    """Record `name`'s vote, with the voter id above (the printed name is kept)."""
    vote.vote(option, name)
    vote.votes[-1]["voter_id"] = voter_pseudo_id(name, chamber, session)
