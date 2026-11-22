"""OPEN-747: which Maine session a bill or a roll call belongs to.

Maine names each session of a two-year Legislature on its own: its printed bills are headed
"132nd MAINE LEGISLATURE / FIRST REGULAR SESSION-2025" (LD 1222) or "FIRST SPECIAL SESSION-2025"
(LD 1223), its Laws of Maine and their Legislative Statistics are kept per session (132R1, 132S1,
132R2), and each session has its own convening and adjournment days. LawMakerWeb, though, keeps
one bill list per Legislature (LD and paper numbers run on through all its sessions). So every
session of a Legislature (all carrying its number as `extras.legislature`) reads the same list
and keeps only what is its own:

* a bill belongs to the session that was sitting on its first dated action, or, when the
  Legislature was not sitting that day, to the next session to convene: LD 1989 of the 132nd was
  received on 2025-12-03 and is printed for the "SECOND REGULAR SESSION-2026". A bill carried
  over into a later session stays in the session it was introduced in, with its later actions
  (LD 216 of the 132nd, carried over from the First Regular into the First Special Session).
  LawMakerWeb lists no companion bills, so a bill with no dated action is skipped with a warning;
* a roll call belongs to the session sitting on its date, though its bill may be filed under
  an earlier session of the same Legislature. A bill's roll calls are read from the bill's own
  page and come with the bill, so a bill always brings all its roll calls (openstates-core
  deletes a bill's stored roll calls that an import does not bring).

Checked 2026-11-21 against the session printed at the head of each bill (bills/getPDF.asp, the
Law Library's copies at lldc.mainelegislature.org/Open/LDs/, and the 121st and 122nd's bill text
pages): the bills first acted on either side of a session boundary in the 121st, 122nd, 123rd,
125th and 128th to 132nd Legislatures, and 42 bills drawn at random from the 125th, 126th and
128th to 132nd, are all printed for the session this rule gives them.
"""
from datetime import date


def legislature(sessions, identifier):
    """The Legislature number (121 to 132) of a session."""
    (found,) = [s for s in sessions if s["identifier"] == identifier]
    return found["extras"]["legislature"]


def _of(sessions, number):
    return sorted(
        (s for s in sessions if s["extras"]["legislature"] == number),
        key=lambda s: s["start_date"],
    )


def session_for_bill(sessions, number, first_action):
    """The identifier of the session of Legislature `number` that a bill first acted on on
    `first_action` (a date) belongs to, or None when it has no dated action or was first acted
    on after the Legislature's last session adjourned."""
    if first_action is None:
        return None
    for s in _of(sessions, number):
        if first_action <= date.fromisoformat(s["end_date"]):
            return s["identifier"]
    return None


def session_for_roll_call(sessions, number, day):
    """The identifier of the session of Legislature `number` sitting on `day`, or None."""
    for s in _of(sessions, number):
        start = date.fromisoformat(s["start_date"])
        if start <= day <= date.fromisoformat(s["end_date"]):
            return s["identifier"]
    return None
