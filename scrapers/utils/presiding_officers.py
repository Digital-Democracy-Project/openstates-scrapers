"""OPEN-764, OPEN-785: a roll call's presiding-officer title ("Mr. Speaker", "Madam President"), in a
form the importer can match.

Some legislatures print each chamber's presiding officer by title, which matches no person by
name. Who they are comes from the jurisdiction manifest's votes.house_speaker_by_session and
votes.senate_president_by_session. There is no built-in table: for a session the manifest does
not list, the title is left as printed (and the caller warns), so it stays visibly unmatched
rather than going to the wrong person. Louisiana (la/voter_names.py), Rhode Island (ri/bills.py)
and Massachusetts' Speaker (ma/voter_names.py, OPEN-810) read them here; Idaho, Mississippi and
Missouri keep their own Speaker readers.

A session whose officer changed maps each first day held ('YYYY-MM-DD') to a name, for example
Rhode Island's 2026 House: {'2026-01-06': 'Joe Shekarchi', '2026-05-07': 'Chris Blazejewski'};
the officer of a roll call is the one in office on its day.
"""
from openstates.utils import _make_pseudo_id
from openstates.utils.ddp_manifest import manifest_value


def officer(state, field, session, day=None):
    """The name the manifest gives for `field` in `session` on `day` ('YYYY-MM-DD'), or None."""
    # session keys as strings: an unquoted 2026 in the manifest is read as a number
    officers = manifest_value(state, "votes." + field, {})
    name = {str(s): n for s, n in officers.items()}.get(str(session))
    if isinstance(name, dict):
        held = sorted(
            (str(first), n) for first, n in name.items() if day and str(first) <= day
        )
        return held[-1][1] if held else None
    return name


def add_voter(vote, option, name, chamber, session, state, titles, day=None):
    """Record `name`'s vote; a title in `titles` ({printed title: (chamber, manifest field)})
    on its own chamber's roll call gets that session's officer as its voter id (the printed
    name is kept). Returns the manifest field that had no name for the session (or day) when
    the title was left unresolved, else None."""
    vote.vote(option, name)
    officer_chamber, field = titles.get(name, (None, None))
    if officer_chamber != chamber:
        return None
    who = officer(state, field, session, day)
    if not who:
        return field
    vote.votes[-1]["voter_id"] = _make_pseudo_id(name=who)
    return None
