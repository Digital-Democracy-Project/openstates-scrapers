"""Tests for classify_motion() and config/motion_classification.yaml integrity."""
import logging
import re
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))
from classify_motion import needs_two_thirds, classify_motion, KNOWN_JURISDICTIONS, _config, _PREPROCESSORS


# ---------------------------------------------------------------------------
# YAML config integrity
# ---------------------------------------------------------------------------

def test_yaml_loads_without_error():
    assert "jurisdictions" in _config


def test_all_expected_jurisdiction_keys_present():
    expected = {"us", "az", "ut", "fl", "mi", "ma", "wa", "va", "pa", "ne", "la", "al", "nc", "nv", "ga", "or"}
    assert expected == KNOWN_JURISDICTIONS


def test_all_preprocess_values_are_known():
    for jur, cfg in _config["jurisdictions"].items():
        preprocess = cfg.get("preprocess")
        if preprocess:
            assert preprocess in _PREPROCESSORS, (
                f"{jur}: unknown preprocessor {preprocess!r}"
            )


def test_all_patterns_are_valid_regex():
    for jur, cfg in _config["jurisdictions"].items():
        for key in ("not_passage", "passage", "committee_passage", "two_thirds"):
            for pattern in cfg.get(key, []):
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise AssertionError(
                        f"{jur}.{key}: invalid regex {pattern!r}: {e}"
                    )
        for pattern in cfg.get("bill_action", {}).get("committee_passage", []):
            re.compile(pattern)


# ---------------------------------------------------------------------------
# Loader behaviour
# ---------------------------------------------------------------------------

def test_unknown_jurisdiction_returns_empty_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        result = classify_motion("xx", "some motion text")
    assert result == []
    assert "unknown jurisdiction" in caplog.text


def test_unknown_preprocessor_raises():
    _config["jurisdictions"]["_test"] = {"preprocess": "nonexistent"}
    try:
        with pytest.raises(ValueError, match="unknown preprocessor"):
            classify_motion("_test", "text")
    finally:
        del _config["jurisdictions"]["_test"]


def test_preprocessor_strips_sequence_number():
    assert classify_motion("wa", "3rd Reading & Final Passage (#7)") == ["passage"]
    assert classify_motion("wa", "Final Passage (#3)") == ["passage"]
    assert classify_motion("wa", "Final Passage as Amended (#3)") == ["passage"]


def test_va_bill_action_drives_committee_passage():
    assert classify_motion("va", "some motion", bill_action="Reported from Finance") == ["committee-passage"]
    assert classify_motion("va", "some motion", bill_action="Subcommittee recommends reporting") == ["committee-passage"]
    assert classify_motion("va", "some motion", bill_action=None) == []


def test_fl_default_catches_unknown_floor_text():
    assert classify_motion("fl", "Third Reading En Bloc") == ["passage"]
    assert classify_motion("fl", "Second Reading") == []


# ---------------------------------------------------------------------------
# Per-jurisdiction true positives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("On Passage", ["passage"]),
    ("On motion to suspend the rules and pass HR 1", ["passage"]),
    ("Passed Senate by Unanimous Consent", ["passage"]),
    ("On the Cloture Motion (S.1234)", ["passage"]),
    ("Passage, Senate Amendment", ["passage"]),
])
def test_us_passage(text, expected):
    assert classify_motion("us", text) == expected


@pytest.mark.parametrize("text", [
    "On Cloture on the Motion to Proceed (S.1234)",
    "Measure laid before Senate",
    "Resolving differences",
    "Postponed Proceedings",
    "Ordered to be reported",
])
def test_us_not_passage(text):
    assert classify_motion("us", text) == []


@pytest.mark.parametrize("text,expected", [
    ("Passed", ["passage"]),
    ("failed to pass", ["passage"]),
    ("do pass", ["committee-passage"]),
    ("do pass amended", ["committee-passage"]),
])
def test_az_classification(text, expected):
    assert classify_motion("az", text) == expected


@pytest.mark.parametrize("text", [
    "Retained on the Calendar",
    "Tabled",
])
def test_az_not_passage(text):
    assert classify_motion("az", text) == []


@pytest.mark.parametrize("text,expected", [
    ("House/ passed 3rd reading", ["passage"]),
    ("Senate/ passed 3rd reading", ["passage"]),
    ("House/ passed on 3rd reading", ["passage"]),
    ("Senate/ passed on 3rd reading", ["passage"]),
    # The shapes below were once blocked by not_passage and are passage since 807fa5785 (2026-07-03):
    # a chamber's concurrence, a conference report's final passage, a combined 2nd-and-3rd-reading
    # passage under suspension of the rules, and a failed passage vote. Each shape is in the replica.
    ("Senate/ passed 2nd & 3rd readings/ suspension", ["passage"]),
    ("House/ concurs with Senate amendment", ["passage"]),
    ("Senate/ concurs with House amendment", ["passage"]),
    ("House Conference Committee - Final Passage", ["passage"]),
    ("Senate Conference Committee - Final Passage", ["passage"]),
    # "passage" says what the vote was about (a vote on passage), not how it came out: a failed
    # passage vote is still the bill's up-or-down vote and the broker scores it. Do not "fix"
    # these to []; the result field carries pass/fail.
    ("House/ failed", ["passage"]),
    ("Senate/ failed", ["passage"]),
])
def test_ut_passage(text, expected):
    assert classify_motion("ut", text) == expected


@pytest.mark.parametrize("text", [
    "House/ passed 2nd reading",
    "Senate/ passed 2nd reading",
    "House/ second reading",
    "House/ substitute adoption failed",  # ends in "failed" but is not the bare "House/ failed"
    "House/ floor amendment",
    # Bare "Final Passage" is not a Utah text (0 of 1,917 stored votes; the real one is
    # "... Conference Committee - Final Passage" above), and the rule that matched it was removed in 807fa5785.
    "Final Passage",
])
def test_ut_not_passage(text):
    assert classify_motion("ut", text) == []


@pytest.mark.parametrize("text,expected", [
    ("Third Reading", ["passage"]),
    ("Passage on Third Reading", ["passage"]),
    ("Third Reading En Bloc", ["passage"]),
])
def test_fl_passage(text, expected):
    assert classify_motion("fl", text) == expected


@pytest.mark.parametrize("text", [
    "Second Reading Amendment",
    "2nd Reading",
    "Placed on Calendar",
    "Amendment No. 1",
])
def test_fl_not_passage(text):
    assert classify_motion("fl", text) == []


@pytest.mark.parametrize("text,expected", [
    ("PASSED ROLL CALL # 120 YEAS 107 NAYS 0", ["passage"]),
    ("The bill passed", ["passage"]),
    ("PASSAGE ROLL CALL # 88 YEAS 62 NAYS 40", ["passage"]),
    ("Passed as Amended ROLL CALL # 5 YEAS 57 NAYS 50", ["passage"]),
    # A chamber's concurrence and a conference report's adoption are passage since 807fa5785
    # (2026-07-03): real, tallied votes the old "concur"/"conference report" blocks hid.
    ("HOUSE AMENDMENT(S) CONCURRED IN ROLL CALL # 116 YEAS 100 NAYS 3", ["passage"]),
    ("Senate amendment(s) concurred in Roll Call #248 Yeas 102 Nays 7 Excused 0 Not Voting 1", ["passage"]),
    ("Conference Report adopted ROLL CALL # 5", ["passage"]),
    ("SENATE ADOPTED CONFERENCE REPORT WITH IMMEDIATE EFFECT ROLL CALL # 3", ["passage"]),
])
def test_mi_passage(text, expected):
    assert classify_motion("mi", text) == expected


# The other side of the boundary: Michigan roll calls that are not the bill's passage vote.
@pytest.mark.parametrize("text", [
    "Amendment adopted ROLL CALL # 12 YEAS 60 NAYS 40",
    "Substitute (S-1) adopted ROLL CALL # 9",
    "Motion to reconsider ROLL CALL # 4",
    "Referred to Committee on Appropriations ROLL CALL # 2",
])
def test_mi_not_passage(text):
    assert classify_motion("mi", text) == []


@pytest.mark.parametrize("text,expected", [
    ("Passed to be engrossed", ["passage"]),
    ("Enacted", ["passage"]),
    ("Adopted", ["passage"]),
    ("Committee of conference report accepted", ["passage"]),
])
def test_ma_passage(text, expected):
    assert classify_motion("ma", text) == expected


@pytest.mark.parametrize("text", [
    "Amendment #1 (Tarr) rejected",
    "Amendment #22 adopted",
    "Item 7004-0109 passed over veto",
])
def test_ma_not_passage(text):
    assert classify_motion("ma", text) == []


@pytest.mark.parametrize("text,expected", [
    ("3rd Reading & Final Passage (#7)", ["passage"]),
    ("Final Passage as Amended (#3)", ["passage"]),
    ("3rd Reading & Final Passage (#12)", ["passage"]),
])
def test_wa_passage(text, expected):
    assert classify_motion("wa", text) == expected


@pytest.mark.parametrize("text", [
    # The classic WA false-positive — starts with "Motion", not "3rd" or "final"
    "Motion to Place Measure on 3rd Reading & Final Passage (#1)",
    "Amendment (H-1234.1)",
    "2nd Reading",
])
def test_wa_not_passage(text):
    assert classify_motion("wa", text) == []


@pytest.mark.parametrize("text,expected", [
    ("Passage  R", ["passage"]),
    ("H VOTE:", ["passage"]),
    ("S VOTE:", ["passage"]),
    ("Passage-Enrolled Bill  R", ["passage"]),
    # "Agree to R" was never matched: the pattern's \b was a backspace inside double quotes
    ("Agree to  R", ["passage"]),
    # OPEN-416: LIS now sends the bill's own action text (with the tally) as the motion
    ("Read third time and passed House (96-Y 0-N 0-A)", ["passage"]),
    ("Read third time and passed House Block Vote (96-Y 0-N 0-A)", ["passage"]),
    ("Read third time and defeated by House (3-Y 95-N 0-A)", ["passage"]),
    ("Passed Senate (21-Y 19-N 0-A)", ["passage"]),
    ("Passed House (98-Y 0-N 0-A)", ["passage"]),
    ("Passed Senate with substitute (22-Y 18-N 0-A)", ["passage"]),
    ("Passed Senate with amendments Block Vote (40-Y 0-N 0-A)", ["passage"]),
    ("Defeated by Senate (18-Y 21-N 0-A)", ["passage"]),
    ("Agreed to by House (96-Y 0-N 0-A)", ["passage"]),
    ("Agreed to by Senate (39-Y 0-N 0-A)", ["passage"]),
    ("Senate substitute agreed to by House (98-Y 0-N 0-A)", ["passage"]),
    ("Senate substitute rejected by House (3-Y 95-N 0-A)", ["passage"]),
    ("Senate amendments agreed to by House (71-Y 28-N 0-A)", ["passage"]),
    ("Senate substitute with amendment rejected by House (40-Y 55-N 0-A)", ["passage"]),
    ("Conference report agreed to by Senate (21-Y 18-N 0-A)", ["passage"]),
    ("Conference report agreed to by House (60-Y 38-N 0-A)", ["passage"]),
    ("Senate acceded to request (40-Y 0-N 0-A)", ["passage"]),
    ("Senate acceded to request  Block Vote (40-Y 0-N 0-A)", ["passage"]),
    ("House concurred in Governor's recommendation (60-Y 38-N 0-A)", ["passage"]),
    ("Senate concurred in Governor's recommendation nos 1 - 3 (21-Y 18-N 0-A)", ["passage"]),
    ("Governor's amendment nos. 1 - 3 agreed to (96-Y 0-N 0-A)", ["passage"]),
    ("Governor's recommendation adopted (96-Y 0-N 0-A)", ["passage"]),
    ("Governor's recommendation nos. 1 - 3 passed by House (60-Y 38-N 0-A)", ["passage"]),
])
def test_va_passage(text, expected):
    assert classify_motion("va", text) == expected


@pytest.mark.parametrize("text", [
    "Constitutional reading dispensed (on 2nd reading)",
    "Constitutional reading dispensed Block Vote (on 2nd reading) (96-Y 0-N 0-A)",
    "Continued to next session in Finance and Appropriations (11-Y 3-N)",
    # a vote ABOUT passage is not a vote on passage
    "Reconsideration of Senate passage agreed to by Senate (21-Y 19-N 0-A)",
    "Reconsideration of Defeated action agreed to by Senate",
    "Passed by indefinitely in Finance and Appropriations (10-Y 4-N)",
    "Senate insisted on substitute (21-Y 19-N 0-A)",
    "Senate insisted on substitute Block Vote (21-Y 19-N 0-A)",
    # amendments, elections, reading waivers and committee referrals are not passage
    "Floor Amendment Item 4-14 #2h offered by Delegate McNamara passed by (64-Y 33-N 0-A)",
    "Contested committee amendment Item 4-5.04 #1h agreed to (64-Y 32-N 0-A)",
    "Committee amendment agreed to (21-Y 19-N 0-A)",
    "Senator Jordan Amendment rejected (18-Y 21-N 0-A)",
    "Elected by House (98-Y 0-N 0-A)",
    "Reading waived (35-Y 0-N 0-A)",
    "Stricken from docket by Appropriations (12-Y 8-N)",
    "Rereferred from Education and Health and rereferred to Commerce and Labor (9-Y 4-N)",
    "Failed to report from Transportation with substitute (6-Y 7-N)",
    "Subcommittee failed to recommend reporting with amendment(s) (4-Y 6-N)",
    # subcommittee votes that kill or park a bill
    "Subcommittee recommends laying on the table (5-Y 0-N)",
    "Subcommittee recommends striking from the docket (5-Y 0-N)",
    "Subcommittee recommends continuing to 2027 (5-Y 0-N)",
    "Subcommittee recommends incorporating into HB 1 (5-Y 0-N)",
    # look-alike actions LIS logs that are not votes on passage
    "Governor's recommendation received by House",
    "Governor's Action Deadline 11:59 p.m., April 13, 2026",
    "Governor's Veto Received by Senate",
    "Conference Report released",
    "House requested conference committee",
    "Failed to Pass from conference",
])
def test_va_not_passage(text):
    assert classify_motion("va", text) == []
    # the bill_action override must not turn these into committee passage either (the scraper
    # now hands classify_motion the same text as bill_action)
    assert classify_motion("va", text, bill_action=text) == []


def test_va_first_matching_section_wins():
    # evaluation order is bill_action -> not_passage -> committee_passage -> passage
    # bill_action decides before the motion text is looked at
    assert classify_motion(
        "va", "Passed Senate (21-Y 19-N 0-A)", bill_action="Reported from Finance"
    ) == ["committee-passage"]
    # not_passage beats passage: a vote about passage is not a vote on passage
    assert classify_motion("va", "Reconsideration of Senate passage agreed to by Senate") == []
    # committee_passage beats passage
    assert classify_motion("va", "Reported from Courts of Justice and passed by") == ["committee-passage"]


@pytest.mark.parametrize("text", [
    "Reported from Finance and Appropriations",
    "Reported from Courts of Justice with substitute (22-Y 0-N)",
    "Reported from Counties, Cities and Towns with amendment(s) (15-Y 2-N)",
    "Subcommittee recommends reporting",
    "Subcommittee recommends reporting with substitute and rereferred to Appropriations (9-Y 0-N)",
    "Subcommittee recommends reporting with amendment(s) (8-Y 0-N)",
])
def test_va_committee_passage(text):
    assert classify_motion("va", text) == ["committee-passage"]
    assert classify_motion("va", text, bill_action=text) == ["committee-passage"]


# ---------------------------------------------------------------------------
# OPEN-478/479/480: Pennsylvania, Nebraska, Louisiana (pilot #2)
# Texts are the real motion texts from each state's first full production scrape (2026-11-06).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    # floor: final passage, including the reconsidered re-votes
    ("FINAL PASSAGE", ["passage"]),
    ("FINAL PASSAGE - RECONSIDERATION", ["passage"]),
    ("FINAL PASSAGE-RECONSIDERED", ["passage"]),
    # committee reports (floor-vote texts are upper-cased by the scraper; committee texts are not)
    ("Committee vote (Appropriations): Re-report Bill As Committed", ["committee-passage"]),
    ("Committee vote (Judiciary): Report Bill As Committed", ["committee-passage"]),
    ("Committee vote (Health & Human Services): Reported as Committed", ["committee-passage"]),
    ("Committee vote (Appropriations): Re-Reported as Committed", ["committee-passage"]),
    ("Committee vote (Judiciary): Report Bill As Amended", ["committee-passage"]),
    ("Committee vote (Judiciary): Reported as Amended", ["committee-passage"]),
    ("Committee vote (Appropriations): Re-Reported as Amended", ["committee-passage"]),
    ("Committee vote (Tourism, Recreation & Economic Development): Report Bill As Committed", ["committee-passage"]),
    # not passage of any kind
    ("Committee vote (Rules): Re-refer Bill To Another Committee", []),
    ("Committee vote (Judiciary): Adopt Resolution", []),
    ("Committee vote (Judiciary): Adopt Amendment A1101", []),
    ("Committee vote (Judiciary): Vote To Table", []),
    ("CONCURRENCE", []),
    ("MOTION TO TABLE", []),
    ("MOTION TO SUSPEND RULES", []),
    ("MOTION TO APPEAL RULING OF THE CHAIR", []),
    ("MOTION TO CONSIDER BILL ON SECOND CONSIDERATION", []),
    ("CONSTITUTIONALITY", []),
    ("RE-REFERRED TO THE COMMITTEE ON APPROPRIATIONS", []),
    ("RECOMMIT TO THE COMMITTEE ON RULES", []),
    ("A1363", []),
    ("House Bill 1663", []),
])
def test_pa(text, expected):
    # the pa scraper upper-cases floor motions before classifying
    motion = text if text.startswith("Committee vote") else text.upper()
    assert classify_motion("pa", motion) == expected


@pytest.mark.parametrize("text,expected", [
    ("Passed on Final Reading 49-0-0", ["passage"]),
    ("Passed on Final Reading 47-1*-1", ["passage"]),
    ("Passed on Final Reading with Emergency Clause 49-0-0", ["passage"]),
    ("Passed on Final Reading with Emergency Clause stricken 40-9-0", ["passage"]),
    ("Failed on Final Reading 20-25-4", ["passage"]),                     # a lost vote on passage
    ("Failed on Final Reading with Emergency Clause 30-15-4", ["passage"]),
    # advancement and procedure are not passage (Utah precedent)
    ("Advanced to Enrollment and Review Initial", []),
    ("Advanced to Enrollment and Review for Engrossment", []),
    ("Failed to advance to Enrollment and Review Initial", []),
    ("Failed to advance to Enrollment and Review for Engrossment", []),
    ("Returned to Select File for specific amendment", []),
    ("Motion to return to Select File failed", []),
    ("Adopted", []),
    ("Hansen AM1097 lost", []),
    ("Arch AM1312 adopted", []),
    ("Raybould FA27 lost", []),
    ("Cavanaugh, M. MO207 prevailed", []),
    ("Failed to become law notwithstanding the objections of the Governor 25-24-0", []),
])
def test_ne(text, expected):
    assert classify_motion("ne", text) == expected


@pytest.mark.parametrize("text,expected", [
    ("FINAL PASSAGE (#1023)", ["passage"]),
    ("FINAL PASSAGE (#7)", ["passage"]),
    ("FINAL PASSAGE, SB 444 BY EDMONDS (#12)", ["passage"]),
    ("BY CLOUD, FINAL PASSAGE (#40)", ["passage"]),
    ("MOTION BY EDMONDS, FINAL PASSAGE (#9)", ["passage"]),
    ("SENATOR MILLER, FINAL PASSAGE (#3)", ["passage"]),
    ("FINAL PASSGE (#5)", ["passage"]),                                   # typo present in the source
    ("AMENDMENT # 3891 BY AMEDEE, MOTION TO ADOPT (#14)", []),
    ("AMENDMENT # 4587 BY LUNEAU, HB 1098 BY MCFARLAND (#9)", []),
    ("MOTION TO RECONSIDER (#4)", []),
    ("CONCUR (#4)", []),
    ("CONCUR IN SENATE AMENDMENTS (#4)", []),
    ("FINAL CONSIDERATION (#4)", []),
    ("ADOPT (#4)", []),
    ("ADOPT CONFERENCE REPORT (#4)", []),
    ("REJECT SENATE AMENDMENTS (#4)", []),
    ("CO-AUTHORS (#4)", []),
    ("MODIFY TIME LIMITS (#4)", []),
])
def test_la(text, expected):
    assert classify_motion("la", text) == expected


def test_pa_ne_la_scrapers_use_classify_motion():
    """The three scrapers must classify through the shared rules, not on their own."""
    root = os.path.join(os.path.dirname(__file__), "..", "scrapers")
    for state, call in (("pa", 'classify_motion("pa"'), ("ne", 'classify_motion("ne"'), ("la", 'classify_motion("la"')):
        src = open(os.path.join(root, state, "bills.py")).read()
        assert "from classify_motion import classify_motion" in src, state
        assert call in src, state
    ne_src = open(os.path.join(root, "ne", "bills.py")).read()
    assert 'classification="passage"' not in ne_src   # NE used to call every vote passage


# ---------------------------------------------------------------------------
# OPEN-527: Alabama. Real ALISON action texts of 2026rs roll calls (Mac replica and ALISON,
# 2026-11-10), with their "- Adopted/Lost Roll Call N" endings as the scraper sends them.
# Amendment adoptions are labelled "amendment" by the al scraper before this is called
# (tests/test_al_votes.py); here a bare "Motion to Adopt" is a resolution's adoption.
# ---------------------------------------------------------------------------

AL_CASES = [
    # final passage, including as amended and a lost passage vote
    ("Motion to Read a Third Time and Pass - Adopted Roll Call 1009", ["passage"]),
    ("Motion to Read a Third Time and Pass as Amended - Adopted Roll Call 536", ["passage"]),
    ("Motion to Read a Third Time and Pass - Lost Roll Call 1225", ["passage"]),
    ("Waggoner motion to Read a Third Time and Pass - Adopted Roll Call 1304", ["passage"]),
    # a resolution's adoption (SR 96) and HB 201's final Senate vote
    ("Waggoner motion to Adopt - Adopted Roll Call 950", ["passage"]),
    ("Motion to Adopt - Adopted Roll Call 101", ["passage"]),
    # concurrence in the other house's / the governor's amendments, conference reports
    ("Gudger Motion to Concur In and Adopt Executive Amendment - Adopted Roll Call 1229", ["passage"]),
    ("Moore (M) Motion to Concur In and Adopt Senate Amendment - Adopted Roll Call 1251", ["passage"]),
    ("Warren motion to Concur In and Adopt Senate Amendment - Adopted Roll Call 1349", ["passage"]),
    ("Ingram motion to Concur In and Adopt Conference Committee Report - Adopted Roll Call 1355", ["passage"]),
    ("Kirkland motion to Concur In and Adopt in Conference Committee - Adopted Roll Call 1341", ["passage"]),
    ("Gudger Concur In and Adopt - Adopted Roll Call 147", ["passage"]),
    ("Roberts Concur in and Adopt- Adopted Roll Call 801", ["passage"]),
    ("Reynolds Concur-In and Adopt Executive Amendment Roll Call 159", ["passage"]),
    # not passage: budget isolation resolutions, conference procedure, procedure
    ("Third Reading in House of Origin", []),
    ("Third Reading in Second House", []),
    ("In Conference Committee", []),
    ("Gudger motion to Non-Concur and Appoint Conference Committee - Adopted Roll Call 1262", []),
    ("Lovvorn motion to Accede - Adopted Roll Call 1333 House appoints Ingram, Reynolds and Lawrence", []),
    ("Kiel motion to Table - Adopted Roll Call 559", []),
    ("Kirkland motion to Table - Lost Roll Call 1221", []),
    ("Lee motion to Previous Question adopted - Adopted Roll Call 528", []),
    ("Brown motion to Previous Question - Adopted Roll Call 446", []),
    ("Petition To Close Debate- Adopted Roll Call 1008", []),
    ("Waggoner Petition to Cease Debate - Adopted Roll Call 1311", []),
    ("Motion to Add Cosponsor - Adopted Roll Call 226", []),
    ("Add Cosponsor - Adopted Roll Call 441", []),
    ("Chambliss Local Certification Resolution - Adopted Roll Call 364", []),
    ("Local Certification Resolution - Adopted Roll Call 671", []),
    # an unknown text stays unclassified
    ("Carried Over to the Call of the Chair", []),
]


@pytest.mark.parametrize("text,expected", AL_CASES)
def test_al(text, expected):
    assert classify_motion("al", text) == expected


@pytest.mark.parametrize("text,expected", AL_CASES[:-1])
def test_al_every_real_text_is_decided_by_a_rule(text, expected):
    # the not-passage texts are named on purpose (the budget isolation resolution above all),
    # so that a later, wider passage pattern cannot pick them up by accident
    cfg = _config["jurisdictions"]["al"]
    key = "passage" if expected else "not_passage"
    assert any(re.search(p, text.lower()) for p in cfg[key])


def test_al_scraper_uses_classify_motion():
    root = os.path.join(os.path.dirname(__file__), "..", "scrapers")
    src = open(os.path.join(root, "al", "bills.py")).read()
    assert "from classify_motion import classify_motion" in src
    assert 'classify_motion("al"' in src
    assert "classification=[]" not in src


# OPEN-561: Massachusetts motions that need two thirds (real MA 194th motion texts).
@pytest.mark.parametrize("text", [
    "Item 4000-0051 passed over veto",
    "Motion (Tarr) to suspend the rules does not prevail",
    "Emergency preamble adopted",
    "Rules suspended",
    "H. 4240 Shall item 4000-0051 (Family Resource Centers",
])
def test_ma_needs_two_thirds(text):
    assert needs_two_thirds("ma", text)


@pytest.mark.parametrize("text", [
    "Decision of the Chair sustained on appeal",
    "Amendment 412 (Tarr) rejected",
    "Passed to be engrossed",
    "Enacted",
    "Committee of conference report accepted",
    "Amendment 3 (Tarr), inserting before the enacting clause an emergency preamble, adopted",
    "Passing the bill to be engrossed, the amendment requiring a two-thirds vote of the board",
    "",
])
def test_ma_does_not_need_two_thirds(text):
    assert not needs_two_thirds("ma", text)


def test_jurisdiction_without_a_two_thirds_list_is_never_two_thirds():
    assert not needs_two_thirds("wa", "Item 4000-0051 passed over veto")
    assert not needs_two_thirds("xx", "Item 4000-0051 passed over veto")


# ---------------------------------------------------------------------------
# OPEN-590: Georgia. Real captions from Georgia's vote service (GetVotes, sessions 2025_26 and
# 2026_ss, House and Senate, 1,917 roll calls, read 2026-11-16), as written there (some with a
# trailing space). The House reconsideration of a calendar ("Local Calendar" again) is decided
# by the ga scraper from the bill's status history (tests/test_ga_votes.py); here it is passage.
# ---------------------------------------------------------------------------

GA_CASES = [
    # passage
    ("PASSAGE", ["passage"]),
    ("PASSAGE BY SUBSTITUTE", ["passage"]),
    ("PASSAGE AS AMENDED", ["passage"]),
    ("SBs 234,  235,  & 336 Passage", ["passage"]),
    # concurrence
    ("AGREE TO HOUSE SUBSTITUTE", ["passage"]),
    ("Agree to Senate Substitute", ["passage"]),
    ("Agree to Senate Sub as Am", ["passage"]),
    ("AGREE TO HOUSE SUBSTITUTE AS AMENDED BY AMENDMENT #2", ["passage"]),
    ("Agree to SAm to HSub As HAm", ["passage"]),
    # conference report
    ("ADOPT CONFERENCE COMMITTEE REPORT", ["passage"]),
    ("Adopt CCR", ["passage"]),
    ("Adopt Conference Comm. Report", ["passage"]),
    # resolutions, constitutional amendments
    ("ADOPT", ["passage"]),
    ("ADOPTION", ["passage"]),
    ("ADOPTION BY SUBSTITUTE", ["passage"]),
    ("ADOPTION OF CONSTITUTIONAL AMENDMENT", ["passage"]),
    ("Uncontested House Resolutions", ["passage"]),
    ("CONSENT CALENDAR FOR SENATE STUDY COMMITTEES", ["passage"]),
    # veto override: Ramon, 2026-11-16 (for nc), "Veto overrides count as passage"
    ("Veto Override", ["passage"]),
    # local calendars
    ("Local Calendar", ["passage"]),
    ("Local Calendar ", ["passage"]),
    ("Local Calendar as a Whole", ["passage"]),
    ("Previous Local Calendar", ["passage"]),
    ("Supplemental Local Calendar #2", ["passage"]),
    ("Local Calendar Without HBs 851 & 852", ["passage"]),
    ("LOCAL CONSENT CALENDAR", ["passage"]),
    ("SUPPLEMENTAL LOCAL CONSENT CALENDAR", ["passage"]),
    # amendments
    ("ADOPTION OF AMENDMENT #1 BY THE SENATOR FROM THE 44TH", []),
    ("ADOPTION OF AMEND #1A BY SEN FROM THE 14TH TO AMEND #1 BY SEN FROM THE 14TH", []),
    ("ADOPTION OF THE AMENDMENT BY THE SEN FROM THE 19TH AS AMENDED", []),
    ("AM 62 0077", []),
    # reconsideration
    ("Reconsider", []),
    ("MOTION FOR RECONSIDERATION", []),
    ("MOTION TO RECONSIDER AMENDMENT #1", []),
    ("MOTION TO RECONSIDER LOCAL CONSENT CALENDAR", []),
    ("Recon SB 234,  235,  & 336", []),
    ("SB614 & SB627 RECON", []),
    # procedure
    ("MOTION TO ENGROSS", []),
    ("MOTION TO ENGROSS: SB 31, SB 175", []),
    ("MOTION FOR THE PREVIOUS QUESTION", []),
    ("MOTION TO WITHDRAW AND COMMIT", []),
    ("MOTION TO TABLE", []),
    ("TABLE", []),
    ("MOTION TO REMOVE FROM THE TABLE", []),
    ("MOTION TO TABLE REMAINING LEGISLATION ON THE RULES CALENDAR", []),
    ("SHALL THE RULING OF THE CHAIR BE SUSTAINED", []),
    ("MOTION TO SUSPEND SENATE RULE 7-1-6(b)", []),
    ("Immediately Transmit", []),
    ("MOTION TO IMMEDIATELY TRANSMIT TO GOVERNOR", []),
    ("MOTION TO RESOLVE DEBATE", []),
    ("MOTION TO ADJOURN", []),
    ("Adjournment", []),
    ("RECEDE FROM SENATE AMENDMENT", []),
    ("MOTION TO PRINT", []),
    ("Move from P&CH to Hth", []),
    ("Remove from Local Cal/Vote Separately", []),
]

# left to the default (unclassified) on purpose: none of them is on one bill
GA_DEFAULT = [
    "Attendance",
    "MORNING ROLL CALL",
    "CONFIRMATION OF GOVERNOR'S APPOINTMENTS",
    "MOTION TO CONFIRM WITH ONE ROLL CALL",
    "Speaker of the House",
    "Dispense with Reading of Journal",
]


@pytest.mark.parametrize("text,expected", GA_CASES)
def test_ga(text, expected):
    assert classify_motion("ga", text) == expected


@pytest.mark.parametrize("text,expected", GA_CASES)
def test_ga_every_real_text_is_decided_by_a_rule(text, expected):
    cfg = _config["jurisdictions"]["ga"]
    key = "passage" if expected else "not_passage"
    assert any(re.search(p, text.strip().lower()) for p in cfg[key])


@pytest.mark.parametrize("text", GA_DEFAULT)
def test_ga_default_texts_are_unclassified(text):
    cfg = _config["jurisdictions"]["ga"]
    t = text.lower()
    assert not any(re.search(p, t) for p in cfg["not_passage"] + cfg["passage"])
    assert classify_motion("ga", text) == []


def test_ga_scraper_uses_classify_motion():
    root = os.path.join(os.path.dirname(__file__), "..", "scrapers")
    src = open(os.path.join(root, "ga", "bills.py")).read()
    assert "from classify_motion import classify_motion" in src
    assert 'classify_motion("ga"' in src
    assert "veto-override" not in src


# ---------------------------------------------------------------------------
# OPEN-572: North Carolina. Every motion text stored for NC (Mac replica, sessions 2025 and 2025E1,
# 781 roll calls, 2026-11-15), as the bill page's vote table writes it. A bare "Second Reading" is
# decided by the nc scraper from the bill's later roll calls (tests/test_nc_votes.py); here it is [].
# ---------------------------------------------------------------------------

NC_CASES = [
    # passage: third readings, conference reports, concurrences, resolution adoptions
    ("Third Reading", ["passage"]),
    ("Third Reading Motion 9 To Concur", ["passage"]),
    ("Conference Rpt Third Reading", ["passage"]),
    ("Conference Report Motion 8 To Adopt", ["passage"]),
    ("Conference Rpt Motion 8 To Adopt", ["passage"]),
    ("C RPT Adoption", ["passage"]),
    ("R3 Ruled Mat'l C RPT Adoption", ["passage"]),
    ("M11 Concur", ["passage"]),
    ("M11 Concur Sen. Amd. 1", ["passage"]),
    ("R3 Ruled Mat'l M11 Concur", ["passage"]),
    ("Motion 9 To Concur", ["passage"]),
    ("Motion 9 To Concur House Amend", ["passage"]),
    ("Motion 8 To Adopt", ["passage"]),
    ("R2 For Adoption", ["passage"]),
    # veto overrides: Ramon, 2026-11-16, "Veto overrides count as passage"
    ("Veto Override", ["passage"]),
    ("Motion 11 Veto Override", ["passage"]),
    # second readings that a third-reading roll call follows
    ("Second Reading", []),
    ("Second Reading Motion 9 To Concur", []),
    ("R2 Ruled Mat'l C RPT Adoption", []),
    ("R2 Ruled Mat'l M11 Concur", []),
    ("Conference Rpt Second Reading", []),
    # amendments
    ("Amendment 1", []),
    ("Amendment 2", []),
    ("A1 Chesser Second Reading", []),
    ("A1 Jones, B. Second Reading", []),
    ("A2 Pierce, R. Second Reading", []),
    ("A2 Par\u00e9 Second Reading", []),
    ("A3 Budd Second Reading", []),
    ("A4 Morey R2 For Adoption", []),
    # non-concurrence
    ("M11 Not Concur", []),
    # procedure
    ("Amendment 2  Motion 1 To Table", []),
    ("A1 Morey Second Reading M3 To Lay On The Table", []),
    ("Veto Override M4 Previous Question", []),
    ("Second Reading M4 Previous Question", []),
    ("R2 For Adoption M4 Previous Question", []),
    ("M6 Reconsider", []),
    ("Second Reading Motion 12/Appeal Ruling of Chair", []),
    ("Second Reading Motion 12/Divide", []),
    # an unknown text stays unclassified
    ("Motion To Adjourn", []),
]


@pytest.mark.parametrize("text,expected", NC_CASES)
def test_nc(text, expected):
    assert classify_motion("nc", text) == expected


@pytest.mark.parametrize("text,expected", NC_CASES[:-1])
def test_nc_every_real_text_is_decided_by_a_rule(text, expected):
    # the not-passage texts are named on purpose, so a later, wider passage pattern cannot pick them up
    cfg = _config["jurisdictions"]["nc"]
    key = "passage" if expected else "not_passage"
    assert any(re.search(p, text.lower()) for p in cfg[key])


def test_nc_scraper_uses_classify_motion():
    root = os.path.join(os.path.dirname(__file__), "..", "scrapers")
    src = open(os.path.join(root, "nc", "bills.py")).read()
    assert "from classify_motion import classify_motion" in src
    assert 'classify_motion("nc"' in src
    assert 'classification="passage"' not in src


# OPEN-595: real Nevada motion texts (2025 session 83 from the OpenStates API, 2025Special36 from
# govbot-data and the 10-31 probe sample). Every Nevada roll call the scraper reads is a chamber's
# final-passage vote, labelled with the version voted on; the last two are not seen and must not count.
NV_CASES = [
    ("Assembly (As Introduced)", ["passage"]),
    ("Senate (As Introduced)", ["passage"]),
    ("Assembly (1st Reprint)", ["passage"]),
    ("Senate (1st Reprint)", ["passage"]),
    ("Assembly (2nd Reprint)", ["passage"]),
    ("Senate (3rd Reprint)", ["passage"]),
    ("Assembly (4th Reprint)", ["passage"]),
    ("Senate (As Introduced) (2)", ["passage"]),  # AB 591, the same label twice on 2025-05-23
    ("Senate (2nd Reprint) (2)", ["passage"]),  # AB 44
    ("Assembly (Veto)", []),  # not seen
    ("Senate (As Enrolled)", []),  # not seen
]


@pytest.mark.parametrize("text,expected", NV_CASES)
def test_nv(text, expected):
    assert classify_motion("nv", text) == expected


# ---------------------------------------------------------------------------
# OPEN-597: Oregon. Every distinct floor motion text the OpenStates API publishes for 2025R1 and 2026R1
# (one real example per text once sponsor names are set aside; 1,976 floor roll calls, read 2026-11-16).
# Committee roll calls ("Heard and Reported Out", "... with Amendments", "Heard") are labelled
# committee-passage by the or scraper from where they come from (tests/test_or_votes.py), not here.
# ---------------------------------------------------------------------------

OR_CASES = [
    # bill passage: third reading, whatever its outcome (a lost third reading is a lost passage vote)
    ("Third reading. Carried by Nelson. Passed.", ["passage"]),
    ("Rules suspended. Third reading. Carried by Anderson. Passed.", ["passage"]),
    ("Third reading as Special Order of Business. Carried by Boice. Passed.", ["passage"]),
    ("Rules suspended. Third reading as Special Order of Business. Carried by Nosse. Passed.", ["passage"]),
    ("Made Special Order of Business. Third reading. Carried by Sollman. Passed.", ["passage"]),
    ("Made Special Order of Business by voice vote. Third reading. Carried by Lieber. Passed.", ["passage"]),
    ("Third reading. Carried by Gomberg. Failed.", ["passage"]),
    ("Third reading. Carried by Frederick. Bill failed.", ["passage"]),
    # the House's roll call recorded after a separate "Third reading. Carried by X." line
    ("Passed.", ["passage"]),
    ("Carried by Nelson. Passed.", ["passage"]),
    ("Repassed.", ["passage"]),
    # resolution and memorial adoption
    ("Final reading. Carried by Manning Jr. Adopted.", ["passage"]),
    ("Rules suspended. Final reading. Carried by Bonham. Adopted.", ["passage"]),
    ("Special Order of Business. Final reading. Carried by McLane. Adopted.", ["passage"]),
    ("Special Order of Business, Final reading. Carried by Prozanski. Adopted.", ["passage"]),
    ("Made Special Order of Business. Final reading. Carried by Weber. Adopted.", ["passage"]),
    ("Read. Carried by Chotzen. Adopted.", ["passage"]),
    ("Rules suspended. Read. Carried by Bowman. Adopted.", ["passage"]),
    ("Read as Special Order of Business. Carried by Levy B. Adopted.", ["passage"]),
    ("Rules suspended. Read as Special Order of Business. Carried by Bowman. Adopted.", ["passage"]),
    (
        "Under the provisions of the Report of the Committee on Permanent Organization and Order of Business, "
        "read final time. Carried by Jama. Adopted.",
        ["passage"],
    ),
    ("Rules suspended. Resolution adopted in conjunction with the 2025 Rules of the House.", ["passage"]),
    # concurrence and repassage (ut, mi, wa, va, al, nc precedent)
    ("House concurred in Senate amendments and repassed bill.", ["passage"]),
    ("Senate concurred in House amendments and repassed bill.", ["passage"]),
    ("Rules suspended. Senate concurred in House amendments and repassed bill.", ["passage"]),
    ("Rules suspended. House concurred in Senate amendments and repassed bill.", ["passage"]),
    ("House concurred in Senate amendments and readopted measure.", ["passage"]),
    ("Senate concurred in House amendments and readopted Resolution.", ["passage"]),
    # conference report adoption
    ("House adopted Conference Committee Report.", ["passage"]),
    ("Senate adopted Conference Committee Report and repassed bill.", ["passage"]),
    # veto override: counted as passage as in nc (Ramon, 2026-11-16); a decision for Ramon for Oregon
    (
        "Motion to repass bill notwithstanding Governor's veto carried in accordance with Art. V, sec. 15b, "
        "Oregon Constitution. Bill repassed.",
        ["passage"],
    ),
    # refusal to concur
    ("House refused to concur in Senate amendments.", []),
    ("Senate refused to concur in House amendments.", []),
    # procedure: refer, re-refer, withdraw from committee
    ("Motion to refer to Rules failed.", []),
    ("Motion to refer to Committee on Rules failed.", []),
    ("Motion to refer to Committee on Legislative Counsel failed.", []),
    ("Motion to refer to Ways and Means failed.", []),
    ("Motion to re-refer to Judiciary failed.", []),
    ("Motion to re-refer to Revenue failed.", []),
    ("Motion to rerefer to Committee on Human Services carried.", []),
    ("Motion to rerefer to Committee on Rules carried.", []),
    ("Motion to rerefer to Labor and Workplace Standards failed.", []),
    ("Motion to withdraw from Rules failed.", []),
    ("Motion to withdraw from Rules carried.", []),
    ("Motion to withdraw from Judiciary failed.", []),
    ("Motion to withdraw from Revenue failed.", []),
    ("Motion to withdraw from Education failed.", []),
    ("Motion to withdraw from Health Care failed.", []),
    ("Motion to withdraw from Housing and Homelessness failed.", []),
    ("Motion to withdraw from committee on Rules failed.", []),
    ("Motion to withdraw from committee on Judiciary failed.", []),
    ("Motion to withdraw from committee on Health Care failed.", []),
    ("Motion to withdraw from committee on Early Childhood and Behavioral Health failed.", []),
    # procedure: minority report, table, reconsider, postpone, calendar, special order
    ("Motion to substitute Minority Report for Committee Report failed.", []),
    ("Rules suspended. Motion to substitute Minority Report for Committee Report failed.", []),
    ("Motion to table carried.", []),
    ("Motion to table carried. Tabled.", []),
    ("Motion to lay bill, together with Governor's message, on the table carried.", []),
    ("Vote reconsideration carried.", []),
    ("Motion to reconsider carried.", []),
    ("Jama moved for immediate reconsideration. Motion to reconsider carried.", []),
    (
        "Motion to postpone to June 9, 2025 Calendar carried. Ayes, 32; Nays, 20--Boice, Boshart Davis, "
        "Breese-Iverson, Cate; Excused, 7--Andersen, Gamba.",
        [],
    ),
    (
        "Taken from 06-18 Calendar and placed on 06-19 Calendar. Ayes, 18; Nays, 11--Anderson, Bonham; "
        "Excused, 1--Gorsek.",
        [],
    ),
    (
        "Rules suspended. Third reading. Taken from 06-24 Calendar and placed on 06-25 Calendar. Ayes, 29; "
        "Excused, 1--Thatcher.",
        [],
    ),
    ("Rules suspended. Made a Special Order of Business immediately.", []),
    # an unknown text stays unclassified
    ("Motion to adjourn carried.", []),
]


@pytest.mark.parametrize("text,expected", OR_CASES)
def test_or(text, expected):
    assert classify_motion("or", text) == expected


@pytest.mark.parametrize("text,expected", OR_CASES[:-1])
def test_or_every_real_text_is_decided_by_a_rule(text, expected):
    # the not-passage texts are named on purpose, so a later, wider passage pattern cannot pick them up
    cfg = _config["jurisdictions"]["or"]
    key = "passage" if expected else "not_passage"
    assert any(re.search(p, text.lower()) for p in cfg[key])
