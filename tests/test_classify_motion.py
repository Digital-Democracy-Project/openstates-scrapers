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
    expected = {"us", "az", "ut", "fl", "mi", "ma", "wa", "va"}
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
    ("Final Passage", ["passage"]),
])
def test_ut_passage(text, expected):
    assert classify_motion("ut", text) == expected


@pytest.mark.parametrize("text", [
    "House/ passed 2nd reading",
    "Senate/ passed 2nd reading",
    "Senate/ concurs with House amendment",
    "House/ second reading",
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
])
def test_mi_passage(text, expected):
    assert classify_motion("mi", text) == expected


@pytest.mark.parametrize("text", [
    "HOUSE AMENDMENT(S) CONCURRED IN ROLL CALL # 116",
    "Conference Report adopted ROLL CALL # 5",
    "SENATE CONCURRED WITH HOUSE AMENDMENTS ROLL CALL # 200",
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
])
def test_va_passage(text, expected):
    assert classify_motion("va", text) == expected


@pytest.mark.parametrize("text", [
    "Reported from Finance and Appropriations",
    "Subcommittee recommends reporting",
    "Constitutional reading dispensed (on 2nd reading)",
])
def test_va_not_passage(text):
    assert classify_motion("va", text) == []
