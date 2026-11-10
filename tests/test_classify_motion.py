"""Tests for classify_motion() and config/motion_classification.yaml integrity."""
import logging
import re
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))
from classify_motion import classify_motion, KNOWN_JURISDICTIONS, _config, _PREPROCESSORS


# ---------------------------------------------------------------------------
# YAML config integrity
# ---------------------------------------------------------------------------

def test_yaml_loads_without_error():
    assert "jurisdictions" in _config


def test_all_expected_jurisdiction_keys_present():
    expected = {"us", "az", "ut", "fl", "mi", "ma", "wa", "va", "pa", "ne", "la", "al"}
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
        for key in ("not_passage", "passage", "committee_passage"):
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
