"""OPEN-748: which Hawaii session a roll call or a bill belongs to.

Hawaii's special sessions are sessions of their own (Ramon 2026-11-21: "regular session and special
session are two different things. don't ever mix their dates together"), each dated from its own
journal on data.capitol.hawaii.gov (hi/__init__.py). The site's bill lists and measure pages hold
only regular-session measures (a special session numbers its measures from 1 again, and asking for
one returns the regular measure of that number), so a special session's own measures are not
scraped here (OPEN-751 reads them from the journal PDFs). What the regular measure pages do carry
from a special session is the roll calls taken on a regular bill while it sat, for example the
veto overrides of the 2021 Special Session on HB 862 of 2021 (7/6/2021, "Act 001, Special Session
2021"): such a roll call is filed under the special session whose dates hold its date, and stays
linked to its bill in the regular session.

2011 and 2012 are two regular sessions, as the site's archive lists them (Ramon 2026-11-21). The
2012 bill list also lists the 2011 bills carried over into 2012; each bill is filed under the year
of its first dated action (the Iowa rule, OPEN-745), so a carried-over 2011 bill stays in 2011 with
its 2012 actions (read from its 2012 page, which holds its whole history) and the 2012 session skips
it. A bill with no dated action follows the companion the site lists for it. Only this pair is
filed this way: the later years keep the upstream filing (a carried-over bill in both years, linked
by "prior-session").
"""
from datetime import date

# the first year of a biennium whose bills are filed by the year of their first dated action, and
# the second year whose list repeats its carried-over bills (by `_scraped_name`, the site's year)
CARRIED_INTO = {"2011": "2012"}


def _day(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def special_session_on(sessions, day):
    """The identifier of the special session whose dates hold `day`, or None."""
    day = _day(day)
    for s in sessions:
        if s["classification"] == "special" and (
            _day(s["start_date"]) <= day <= _day(s["end_date"])
        ):
            return s["identifier"]
    return None


def is_special(sessions, identifier):
    return any(
        s["identifier"] == identifier and s["classification"] == "special"
        for s in sessions
    )


def scraped_name(sessions, identifier):
    """The site's year (`_scraped_name`) of a regular session."""
    (found,) = [s for s in sessions if s["identifier"] == identifier]
    return found["_scraped_name"]


def belongs_to_earlier_year(year, first_action):
    """True when a bill on the list of the site's year `year` (a `_scraped_name`) belongs to the
    first year of its biennium instead: `year` repeats that year's carried-over bills
    (CARRIED_INTO) and the bill was first acted on before `year`. `first_action` is a date or
    None."""
    return (
        year in CARRIED_INTO.values()
        and first_action is not None
        and first_action.year < int(year)
    )
