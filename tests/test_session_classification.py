"""OPEN-557: every session in the Georgia, Oregon, Virginia and Washington lists says whether it is
regular ("primary") or special.

These four lists left `classification` blank, so api-v3 guessed from the identifier (and guessed
Georgia's "2026_ss" as regular). The import copies each list entry onto the stored session, so the
stored value is only as good as this list. The special sessions below are each legislature's own,
read on 2026-11-17:

* Georgia: the legislature's Session service (webservices.legis.ga.gov GetSessions), the "...EX"
  library sessions named "Special Session".
* Hawaii (OPEN-729, read 2026-11-21): the year menu on data.capitol.hawaii.gov
  (session/archives/main.aspx, the page get_session_list reads) offers one entry a year and lists
  no special sessions, and the scraper names each session a "Regular Session", so every session
  is regular. OPEN-748 found the 27 special sessions since 2011 in the legislature's journals
  (data.capitol.hawaii.gov/sessions/journal/Senate/<year>/, each titled "Special Session of
  <year>", "Second Special Session of <year>", ...); since then (Ramon 2026-11-21: "All 28", 27
  on the journals' count) each is a special session of its own, named as its journal names it.
* Idaho (OPEN-724, read 2026-11-20): legislature.idaho.gov/sessioninfo/ names a "First
  Extraordinary Session" in 2015, 2020 and 2022 (and 2000 and 2006, before the scraper's list
  starts); every other session is regular. Since OPEN-753 (read 2026-11-22) every session's dates
  are the "Convened" and "Adjourned" days on legislature.idaho.gov/sessioninfo/sessiondates/.
* Iowa (OPEN-741, read 2026-11-21): legis.iowa.gov/legislation/findLegislation (the page
  get_session_list reads) names only two-year General Assemblies (76 to 91) and lists no special
  or extraordinary sessions, which Iowa keeps inside their General Assembly, so every session is
  regular. OPEN-744 found the four extraordinary sessions in the scraper's span in the journals
  (2021-10-05 and 2021-10-28 in General Assembly 89, 2023-07-11 in 90, 2026-10-02 in 91), each
  convened by the Governor's proclamation in an "Extraordinary Session"; since OPEN-745 (Ramon
  2026-11-21: "Separate sessions, own dates") each is a special session of its own, 2021s1,
  2021s2, 2023s1 and 2026s1, though the site lists them under their General Assembly.
* Kentucky (OPEN-728, read 2026-11-21): apps.legislature.ky.gov/record/pastses.html (the page
  get_session_list reads) names a "Special Session" in 2011, 2012, 2013, 2018, 2019, 2021 and
  2022 and every other entry a "Regular Session"; 2024 to 2026 are current and not on that page.
* Maine (OPEN-739, read 2026-11-21): the LegSession menu on mainelegislature.org
  (LawMakerWeb/advancedsearch.asp, the page get_session_list reads) offers one entry per two-year
  Legislature (121st to 131st, plus "2001-2002"; the current 132nd is not on it yet) and lists no
  special sessions, which Maine keeps inside their Legislature's bill numbering. Since OPEN-747
  (Ramon 2026-11-21: "Separate sessions, own dates") each Legislature's First and Second Regular
  Sessions and each of its special sessions are sessions of their own, as Maine names them on its
  printed bills and in the Laws of Maine; the fourteen special sessions below are listed on the
  Legislative Statistics pages of the Laws of Maine (lldc.mainelegislature.org/Open/Laws/).
* Maryland (OPEN-742, read 2026-11-21): the session menu on mgaleg.maryland.gov
  (mgawebsite/Search/Legislation, the page get_session_list reads) names each session a
  "Regular Session" or a "Special Session"; the six special ones in the scraper's list are
  below (its 2004, 2006 and 2025 special sessions are in ignored_scraped_sessions), every other
  is regular.
* Mississippi (OPEN-730, read 2026-11-21): billstatus.ls.state.ms.us/sessions.htm (the page
  get_session_list reads) names each session a "Regular Session" or an "... Extraordinary
  Session"; the nineteen extraordinary ones below are special, every other is regular (its 2008
  First Extraordinary Session is not in the scraper's list).
* Missouri (OPEN-736, read 2026-11-21): the Senate's journal list (senate.mo.gov/journallist/,
  one page per year) names a "First Extraordinary Session" in 2019, 2020, 2021, 2022 and 2025 and
  a "Second Extraordinary Session" in 2020 and 2025, beside each year's Regular and Veto sessions
  (veto sessions are not separate sessions in the scraper's list); the scraper's own
  "_scraped_name"s, from house.mo.gov's bill list, say the same. Every other session is regular.
* Montana (OPEN-734, read 2026-11-21): the two session endpoints get_session_list reads,
  api.legmt.gov/archive/v1/sessions (sessionTypeDesc "Regular" for 2011 to 2023) and
  api.legmt.gov/legislators/v1/sessions (type REGULAR for 2025 and 2027); its one special session
  in that span, 20172 ("November Special Session", sessionTypeDesc "Special"), is a session of its
  own since OPEN-749, 2017s1; every other session in the list is regular.
* North Dakota (OPEN-721, read 2026-11-20): ndlegis.gov/assembly/ lists only two-year Legislative
  Assemblies, which are regular sessions; it keeps later special sessions inside their assembly.
  Since OPEN-746 (read 2026-11-21) each special session is a session of its own, as the
  legislature's own session pages and journals name it: 62S1 (Nov 2011), 64S1 (Aug 2016), 67S1
  (Nov 2021), 68S1 (Oct 2023), 69S1 (Jan 2026) and 69S2 (Sep 2026).
* Oklahoma (OPEN-727, read 2026-11-21): the session menu on webapps.oklegislature.gov
  (WebApplication3/WebForm1.aspx, the page get_session_list reads) names each session "Regular
  Session" or "... Special Session"; the twelve special ones are below, every other is regular.
* Oregon: OLIS (api.oregonlegislature.gov LegislativeSessions), the "S" session keys.
* Rhode Island (OPEN-726, read 2026-11-21): the year menu on status.rilegislature.gov (bill
  history, previous sessions) offers one regular session a year and names no special or
  extraordinary sessions, so every session is regular. Since OPEN-754 (read 2026-11-22) every
  session runs from the first to the last day either chamber sat, on the House and Senate
  Journals pages (rilegislature.gov/journals/), each year one "January Session".
* Virginia: LIS (lis.virginia.gov GetSessionListAsync), SessionType "Special".
* Washington: leg.wa.gov lists only two-year bienniums, which are regular sessions; its special
  sessions are not separate sessions there.
* Wyoming (OPEN-752, read 2026-11-22): the session menu on wyoleg.gov/Legislation/<year> names a
  "General Session" in odd years and a "Budget Session" in even years (both regular) and a
  "Special Session" in 2020 and 2021 (and 2004, before the scraper's list starts); the
  legislature's session days (lsoservice.wyoleg.gov/api/Session) flag only those two with a
  specialSessionValue since 2011. Every other session is regular, 2012 included.
"""
import ast
import os

import pytest

SCRAPERS = os.path.join(os.path.dirname(__file__), "..", "scrapers")

SPECIAL = {
    "ga": {"2011_ss", "2018_ss", "2020_ss", "2021_ss", "2023_ss", "2026_ss"},
    "hi": {
        "2011 Special Session",
        "2012 Special Session",
        "2013 Special Session",
        "2013 Second Special Session",
        "2014 Special Session",
        "2015 Special Session",
        "2016 Special Session",
        "2016 Second Special Session",
        "2016 Third Special Session",
        "2017 Special Session",
        "2017 Second Special Session",
        "2017 Third Special Session",
        "2018 Special Session",
        "2018 Second Special Session",
        "2019 Special Session",
        "2019 Second Special Session",
        "2020 Special Session",
        "2020 Second Special Session",
        "2021 Special Session",
        "2021 Second Special Session",
        "2021 Third Special Session",
        "2022 Special Session",
        "2022 Second Special Session",
        "2022 Third Special Session",
        "2023 Special Session",
        "2023 Second Special Session",
        "2024 Special Session",
    },
    "ia": {"2021s1", "2021s2", "2023s1", "2026s1"},
    "id": {"2015spcl", "2020spcl", "2022spcl"},
    "ky": {"2011SS", "2012SS", "2013SS", "2018SS", "2019SS", "2021SS", "2022SS"},
    "md": {"2007s1", "2011s1", "2012s1", "2012s2", "2021s1", "2026s1"},
    "me": {
        "121S1",
        "121S2",
        "122S1",
        "122S2",
        "123S1",
        "125S1",
        "126S1",
        "128S1",
        "128S2",
        "129S1",
        "130S1",
        "130S2",
        "131S1",
        "132S1",
    },
    "ms": {
        "20091E",
        "20092E",
        "20093E",
        "20101E",
        "20102E",
        "20111E",
        "20131E",
        "20132E",
        "20141E",
        "20142E",
        "20161E",
        "20162E",
        "20171E",
        "20181E",
        "20221E",
        "20241E",
        "20242E",
        "20251E",
        "20261E",
    },
    "mo": {"2019S1", "2020S1", "2020S2", "2021S1", "2022S1", "2025S1", "2025S2"},
    "mt": {"2017s1"},
    "nd": {"62S1", "64S1", "67S1", "68S1", "69S1", "69S2"},
    "ok": {
        "2012SS1",
        "2013SS1",
        "2017SS1",
        "2017SS2",
        "2020SS1",
        "2021SS1",
        "2022SS2",
        "2022SS3",
        "2023S1",
        "2023S2",
        "2024S3",
        "2024S4",
    },
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
    "wy": {"2020S1", "2021S1"},
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


def test_ri_sessions_do_not_overlap_and_end_after_they_start():
    # OPEN-754: each Rhode Island session is one year's sitting days, so none ends before it
    # starts and no two share a day (a session's later sittings, as in Dec 2020, stay inside it)
    sessions = sorted(_sessions("ri"), key=lambda s: s["start_date"])
    for s in sessions:
        assert s["start_date"] <= s["end_date"], s["identifier"]
    for a, b in zip(sessions, sessions[1:]):
        assert a["end_date"] < b["start_date"], (a["identifier"], b["identifier"])


# Sessions the upstream lists had the wrong way round, each checked against the
# legislature's own record of that session (2026-11-17, Wyoming 2026-11-22).
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
    # wyoleg.gov/Legislation/2012: "Legislation - 2012 Budget Session" (Feb 13 to Mar 9, 2012);
    # OPEN-752, upstream had it special
    ("wy", "2012", "primary"),
]


@pytest.mark.parametrize("state,identifier,classification", CORRECTED)
def test_corrected_sessions(state, identifier, classification):
    (session,) = [s for s in _sessions(state) if s["identifier"] == identifier]
    assert session["classification"] == classification


# OPEN-752 (Wyoming), OPEN-753 (Idaho): regular and special sessions are separate, each with its
# own dates, so no regular session's dates may cover a special session's.
@pytest.mark.parametrize("state", ["id", "wy"])
def test_no_regular_session_covers_a_special_session(state):
    sessions = _sessions(state)
    regular = [s for s in sessions if s["classification"] == "primary"]
    for special in (s for s in sessions if s["classification"] == "special"):
        for r in regular:
            assert (
                r["end_date"] < special["start_date"]
                or special["end_date"] < r["start_date"]
            ), (r["identifier"], special["identifier"])
