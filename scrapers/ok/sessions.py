"""OPEN-758: which Oklahoma session a bill or a roll call belongs to (the Iowa rule, OPEN-745,
scrapers/ia/sessions.py).

Oklahoma's journals name each year of a Legislature as its own regular session ("First Regular
Session of the Sixtieth Legislature" in 2025, "Second Regular Session" in 2026), and so does the
legislature's search form ("2025 Regular Session", "2026 Regular Session"). Bills, though, are
numbered once per Legislature and carry over into its second year, and the site keeps the
Legislature's whole record under the second year: on the form, the 2026 Regular Session lists
every 2025 bill as well, with its 2026 actions, while the 2025 Regular Session's list and bill
pages stop at the 2025 close (HB 1002: 7 actions to 2025-03-10 under 2500, 18 to 2026-04-16
under 2600, read 2026-11-22). So both regular sessions of a Legislature read the newest list of
the Legislature the scraper knows, and each keeps only what is its own (Ramon 2026-11-21, Iowa:
"bills by filing year"):

* a bill belongs to the regular session its first dated action falls in: the first of the
  Legislature's regular sessions that has not closed by that day (an action after the first
  year's close, before the second year opens, is filed for the second year). A bill carried over
  into the second year stays in its first year, with its later actions. The site lists no
  companions, so a bill with no dated action is left out with a warning (Iowa's rule falls back
  on the companion the site lists; Oklahoma's has none to follow);
* a roll call is filed under the session its own date falls in, by the same rule, and stays
  linked to its bill: both come from the bill's page in the same scrape, so the bill's whole set
  of roll calls is always imported together.

Special sessions keep their own lists (their own codes on the form), bills and roll calls.
"""
from datetime import date


def _regular(session):
    return session["classification"] == "primary" and session["identifier"].isdigit()


def _legislature(sessions, identifier):
    """The regular sessions of the Legislature of regular session `identifier`, oldest first:
    the odd year it opened in and the even year after it, as far as the list has them."""
    year = int(identifier)
    first = year if year % 2 else year - 1
    return sorted(
        (
            s
            for s in sessions
            if _regular(s) and int(s["identifier"]) in (first, first + 1)
        ),
        key=lambda s: s["identifier"],
    )


def _is_regular(sessions, identifier):
    return any(s["identifier"] == identifier and _regular(s) for s in sessions)


def listing_session(sessions, identifier):
    """The session whose list on the legislature's search form the scrape of `identifier`
    reads: for a regular session, the newest regular session of its Legislature in the list
    (the one whose list and bill pages carry both years); a special session reads its own."""
    if not _is_regular(sessions, identifier):
        return identifier
    return _legislature(sessions, identifier)[-1]["identifier"]


def session_for_day(sessions, identifier, day):
    """The session a bill first acted on `day`, or a roll call held on `day`, belongs to, for a
    bill read by the scrape of `identifier`: the first regular session of its Legislature that
    has not closed by `day` (the last one if all have); a special session's own bills and roll
    calls stay in it. None when `day` is None."""
    if day is None:
        return None
    if not _is_regular(sessions, identifier):
        return identifier
    legislature = _legislature(sessions, identifier)
    for s in legislature:
        if day <= date.fromisoformat(s["end_date"]):
            return s["identifier"]
    return legislature[-1]["identifier"]
