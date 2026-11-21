"""OPEN-557: every session in the Georgia, Oregon, Virginia and Washington lists says whether it is
regular ("primary") or special.

These four lists left `classification` blank, so api-v3 guessed from the identifier (and guessed
Georgia's "2026_ss" as regular). The import copies each list entry onto the stored session, so the
stored value is only as good as this list. The special sessions below are each legislature's own,
read on 2026-11-17:

* Georgia: the legislature's Session service (webservices.legis.ga.gov GetSessions), the "...EX"
  library sessions named "Special Session".
* Idaho (OPEN-724, read 2026-11-20): legislature.idaho.gov/sessioninfo/ names a "First
  Extraordinary Session" in 2015, 2020 and 2022 (and 2000 and 2006, before the scraper's list
  starts); every other session is regular.
* North Dakota (OPEN-721, read 2026-11-20): ndlegis.gov/assembly/ lists only two-year Legislative
  Assemblies, which are regular sessions; it keeps later special sessions inside their assembly,
  so only 67S1 (November 2021) is special.
* Oregon: OLIS (api.oregonlegislature.gov LegislativeSessions), the "S" session keys.
* Rhode Island (OPEN-726, read 2026-11-21): the year menu on status.rilegislature.gov (bill
  history, previous sessions) offers one regular session a year and names no special or
  extraordinary sessions, so every session is regular.
* Virginia: LIS (lis.virginia.gov GetSessionListAsync), SessionType "Special".
* Washington: leg.wa.gov lists only two-year bienniums, which are regular sessions; its special
  sessions are not separate sessions there.
"""
import ast
import os

import pytest

SCRAPERS = os.path.join(os.path.dirname(__file__), "..", "scrapers")

SPECIAL = {
    "ga": {"2011_ss", "2018_ss", "2020_ss", "2021_ss", "2023_ss", "2026_ss"},
    "id": {"2015spcl", "2020spcl", "2022spcl"},
    "nd": {"67S1"},
    "or": {
        "2008 Special Session",
        "2010 Special Session",
        "2012 Special Session",
        "2013 Special Session",
        "2018 Special Session",
        "2020S1",
        "2020S2",
        "2020S3",
        "2021S1",
        "2021S2",
        "2024S1",
        "2025S1",
    },
    "va": {
        "2011specialI",
        "2012specialI",
        "2013specialI",
        "2014specialI",
        "2015specialI",
        "2018specialI",
        "2018specialII",
        "2019specialI",
        "2020specialI",
        "2021S2",
        "2022S1",
        "2023S1",
        "2024S1",
        "2026S1",
    },
    "ri": set(),
    "wa": set(),
}


def _sessions(state):
    # Read the list from the source, not by importing the package: some state packages import
    # DDP core modules a plain test image may not have, and the list itself is plain data.
    with open(os.path.join(SCRAPERS, state, "__init__.py")) as f:
        tree = ast.parse(f.read())
    (node,) = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "legislative_sessions" for t in n.targets)
    ]
    # A session switched on by date (OPEN-632, Arizona's 2027) sets "active" or "start_date"
    # from a module constant; those values are read as None, the rest stays plain data.
    return ast.literal_eval(_NamesToNone().visit(node.value))


class _NamesToNone(ast.NodeTransformer):
    def visit_Name(self, node):
        return ast.copy_location(ast.Constant(None), node)

    def visit_UnaryOp(self, node):
        if isinstance(node.operand, ast.Name):
            return ast.copy_location(ast.Constant(None), node)
        return self.generic_visit(node)


@pytest.mark.parametrize("state", sorted(SPECIAL))
def test_every_session_is_classified_as_the_legislature_lists_it(state):
    sessions = _sessions(state)
    assert sessions
    got = {s["identifier"]: s.get("classification") for s in sessions}
    # one entry per identifier: the import keys sessions by identifier, and a dict would hide a
    # duplicate with a different classification
    assert len(got) == len(sessions)
    expected = {i: ("special" if i in SPECIAL[state] else "primary") for i in got}
    assert got == expected
    # every special named above is in the list (a typo here would otherwise pass silently)
    assert SPECIAL[state] <= set(got)


# Six sessions the upstream lists had the wrong way round, each checked against the
# legislature's own record of that session (2026-11-17).
CORRECTED = [
    # azleg.gov: "Fifty-first Legislature - First Special Session" (June 2013)
    ("az", "51st-1st-special", "special"),
    # azleg.gov: "Fifty-fifth Legislature - Second Regular Session" (2022)
    ("az", "55th-2nd-regular", "primary"),
    # flsenate.gov: Journal of the Senate, Special Session A (May 2021)
    ("fl", "2021A", "special"),
    # legis.la.gov: 2023 First Extraordinary Session (231ES)
    ("la", "2023s1", "special"),
    # nebraskalegislature.gov: 102nd Legislature, First Special Session (November 2011)
    ("ne", "102S1", "special"),
    # palegis.us: First Special Session of 2023-2024 (called for January 9, 2023)
    ("pa", "2023-2024S1", "special"),
]


@pytest.mark.parametrize("state,identifier,classification", CORRECTED)
def test_corrected_sessions(state, identifier, classification):
    (session,) = [s for s in _sessions(state) if s["identifier"] == identifier]
    assert session["classification"] == classification
