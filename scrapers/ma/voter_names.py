"""OPEN-474: the names Massachusetts roll calls print, in a form the importer can match.

openstates-core's `resolve_person` matches a voter name case-insensitively against a
person's `name`, `other_names` or `family_name`, among members of the vote's chamber.
The roll calls print names in forms the people data does not hold:

* House sheets: "--Jones--" (the sheet's mark for a party leader), "Tyler *" (vote cast
  after the roll closed), "Mr. Speaker", and "Moran M." where the people data has
  "Moran, M.".
* Senate sheets: "Keenan, John F.", "Driscoll, Jr., William J." -- surname first. The
  people data has "John F. Keenan" and "William J. Driscoll, Jr.".

The House reader also must split "X Silvia" (one space between the letter and the name)
into its letter and name; that is `HOUSE_CELL_RE`, not a name rule.
"""
import re

from utils import presiding_officers

# One "<vote letter> <name>" cell of the House roll grid in `pdftotext -layout` output,
# e.g. "Y   Mr. Speaker", "N   Tyler *" or "X Silvia" (a single space happens). The letter
# is paired with the name printed beside it; reading letters and names as two separate
# lists attaches votes to the wrong legislators as soon as one cell is misread.
HOUSE_CELL_RE = re.compile(
    r"(?:^|(?<=\s))([YNXP])\s+(\S(?:.*?\S)?)(?=\s{2,}[YNXP]\s|\s*$)"
)

# "Mr. Speaker" is the session's Speaker, named by the manifest's votes.house_speaker_by_session
# through the shared reader utils/presiding_officers.py (OPEN-810: no member name in code). A
# session the manifest does not list keeps the title as printed, so it stays visibly unmatched
# rather than going to the wrong person, and the bills scraper warns.
SPEAKER_TITLE = "Mr. Speaker"

_SURNAME_INITIAL_RE = re.compile(r"^(?P<surname>[^,]+?) (?P<initial>[A-Z]\.)$")
_SUFFIX_RE = re.compile(r"^(Jr|Sr|II|III|IV)\.?$")


def house_voter_name(raw, session):
    """A name from the House roll grid, as the people data spells it."""
    name = raw.rstrip(" *").replace("--", "").strip()
    if name == SPEAKER_TITLE:
        return (
            presiding_officers.officer("ma", "house_speaker_by_session", session)
            or name
        )
    # "Moran M." -> "Moran, M." (the sheet sometimes drops the comma it prints for
    # "Ramos, A." and "Rogers, J.")
    match = _SURNAME_INITIAL_RE.match(name)
    if match:
        return "{}, {}".format(match.group("surname"), match.group("initial"))
    return name


def senate_voter_name(raw):
    """A name from a Senate roll call, "Surname[, Suffix], Given names", reordered to
    "Given names Surname[, Suffix]". A name without a comma is returned unchanged."""
    parts = [p.strip() for p in raw.strip().split(",")]
    if len(parts) == 2 and all(parts):
        surname, given = parts
        return "{} {}".format(given, surname)
    if len(parts) == 3 and all(parts) and _SUFFIX_RE.match(parts[1]):
        surname, suffix, given = parts
        return "{} {}, {}".format(given, surname, suffix)
    return raw.strip()
