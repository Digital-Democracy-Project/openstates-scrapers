"""OPEN-745: which Iowa session a bill or a journal belongs to.

Iowa's journals name each year of a General Assembly as its own regular session ("Ninety-first
General Assembly of Iowa, 2025 Regular Session", then "2026 Regular Session"), and its
extraordinary sessions as sessions of their own. legis.iowa.gov, though, keeps one bill list
(bills numbered once per General Assembly, HF 2801) and one pair of journal lists per General
Assembly. So every session of a General Assembly (its two years and its extraordinary sessions,
all carrying the General Assembly's number as `extras.ordinal`) reads the same lists and keeps
only what is its own:

* a bill belongs to an extraordinary session when its first dated action falls from that
  session's `extras.bills_filed_from` (the day after the legislature last sat) to its
  `end_date`: the regular session cannot introduce a bill while it is not sitting, and a business
  resolution can be filed a few days before the session convenes (HCR 10, filed 2023-07-07 for
  2023-07-11). Otherwise it belongs to the regular session of the year of its first dated
  action (Ramon 2026-11-21: "bills by filing year"); a bill carried over into the second year
  stays in its first year, with its later actions. A bill with no dated action follows the
  companion the site lists for it (Ramon 2026-11-21: SCR 8 of 2023 goes with HCR 10);
* a journal, with every roll call in it, belongs to the extraordinary session that sat on its
  date, else to the regular session of its year. A roll call is linked to its bill wherever in
  the General Assembly the bill is filed, and either year's scrape brings both years' roll calls
  (votes.py).

Checked 2026-11-21 on every bill numbered in each extraordinary session's window (the site
numbers bills in filing order, so each bill type was read from its highest number down to the
first bill first acted on before the window): only the extraordinary sessions' own bills fall in
a window. The first bills of each second year (HF 2001, SF 2001, HJR 2001, HR 101, SCR 101 of
the 91st; SF 2001 of the 90th) were first acted on in January of the second year: pre-filing is
not an action on the site.
"""
from datetime import date


def ordinal(sessions, identifier):
    """The General Assembly number (the site's `ga=`) of a session."""
    (found,) = [s for s in sessions if s["identifier"] == identifier]
    return str(found["extras"]["ordinal"])


def of_general_assembly(sessions, ga):
    """The identifiers of every session of General Assembly `ga`."""
    return [s["identifier"] for s in sessions if str(s["extras"]["ordinal"]) == str(ga)]


def _of(sessions, ga, classification):
    return [
        s
        for s in sessions
        if s["classification"] == classification
        and str(s["extras"]["ordinal"]) == str(ga)
    ]


def _regular_of_year(sessions, ga, year):
    for s in _of(sessions, ga, "primary"):
        if s["identifier"] == str(year):
            return s["identifier"]
    return None


def session_for_bill(sessions, ga, first_action):
    """The identifier of the session of General Assembly `ga` a bill first acted on on
    `first_action` (a date) belongs to, or None when `first_action` is None or falls in no
    session of that General Assembly."""
    if first_action is None:
        return None
    for s in _of(sessions, ga, "special"):
        start = date.fromisoformat(s["extras"]["bills_filed_from"])
        if start <= first_action <= date.fromisoformat(s["end_date"]):
            return s["identifier"]
    return _regular_of_year(sessions, ga, first_action.year)


def session_for_journal(sessions, ga, day):
    """The identifier of the session of General Assembly `ga` a journal dated `day` belongs
    to, or None."""
    for s in _of(sessions, ga, "special"):
        start = date.fromisoformat(s["start_date"])
        if start <= day <= date.fromisoformat(s["end_date"]):
            return s["identifier"]
    return _regular_of_year(sessions, ga, day.year)


def is_regular(sessions, identifier):
    return any(
        s["identifier"] == identifier and s["classification"] == "primary"
        for s in sessions
    )


def newest_active_regular(sessions):
    """The newest regular session switched on: the one pre-filed bills are filed under."""
    active = [
        s["identifier"]
        for s in sessions
        if s["classification"] == "primary" and s.get("active")
    ]
    return max(active, default=None)
