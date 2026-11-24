"""OPEN-555 (PLAN-state-specific-handling Phase 4): per-state values read from ddp-open-states' jurisdictions.yaml.

Each reader takes the manifest's field and falls back to the old constant when the manifest, the state's entry or the
field is missing. Today's values are written out below by hand (the constants as they were before this change), so a
reader that returned anything else -- with the field, without it, or for a manifest with no entry for the state --
fails here. The values are read at import, so each manifest is loaded in a fresh interpreter (re-importing in this one
would re-apply fl/bills.py's URL patch and leave other tests holding stale classes).

OPEN-810: MA's Speaker table is gone (no member name in code); "Mr. Speaker" is named by the manifest only, through
utils/presiding_officers.py, and tested in test_ma_voter_names.py.
"""
import json
import os
import subprocess
import sys

import pytest
import yaml

SCRAPERS = os.path.join(os.path.dirname(__file__), "..", "scrapers")

# (module, attribute, state, manifest field, today's value, a different value)
READERS = [
    ("mi.bills", "MI_SCRAPELIB_RPM", "mi", "waf.requests_per_minute", 10, 4),
    ("fl.bills", "FLHOUSE_WAF_MAX_ATTEMPTS", "fl", "waf.max_attempts", 3, 5),
    (
        "fl.bills",
        "FL_COOLDOWN_AFTER_FAILURES",
        "fl",
        "waf.cooldown_after_failures",
        3,
        6,
    ),
    ("fl.bills", "FL_COOLDOWN_SECONDS", "fl", "waf.cooldown_s", 300, 60),
    ("ut", "_SESSION_LIST_MAX_ATTEMPTS", "ut", "scrape.session_list_attempts", 3, 4),
    (
        "ut",
        "_SESSION_LIST_BACKOFF_SECONDS",
        "ut",
        "scrape.session_list_backoff_s",
        2,
        7,
    ),
    ("nc.bills", "_BARE_KEY_SESSION", "nc", "votes.bare_key_session", "2025", "2027"),
]

_PROBE = """
import importlib, json, sys
out = {}
for module, attr in json.loads(sys.argv[1]):
    out[module + "." + attr] = getattr(importlib.import_module(module), attr)
nc = importlib.import_module("nc.bills")
out["nc_keys"] = [nc.vote_dedupe_key("2025", "[S]-1"), nc.vote_dedupe_key("2025E1", "[S]-1")]
print(json.dumps(out))
"""


NULL = object()


def _manifest(values):
    """A manifest whose entries hold each reader's field set to values[i] (None: the field left out; NULL: null)."""
    data = {}
    for (module, attr, state, field, *_), value in zip(READERS, values):
        entry = data.setdefault(state, {"name": state})
        if value is None:
            continue
        *blocks, leaf = field.split(".")
        node = entry
        for block in blocks:
            node = node.setdefault(block, {})
        node[leaf] = None if value is NULL else value
    return yaml.safe_dump(data)


def _read(tmp_path, manifest_text, env=None):
    path = tmp_path / "jurisdictions.yaml"
    if manifest_text is None:
        path = tmp_path / "absent.yaml"
    else:
        path.write_text(manifest_text)
    child_env = {k: v for k, v in os.environ.items() if k != "MI_SCRAPELIB_RPM"}
    child_env.update(DDP_JURISDICTIONS_MANIFEST=str(path), **(env or {}))
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps([[r[0], r[1]] for r in READERS])],
        cwd=SCRAPERS,
        env=child_env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _values(out):
    return [out[f"{r[0]}.{r[1]}"] for r in READERS]


TODAY = [r[4] for r in READERS]
OTHER = [r[5] for r in READERS]


@pytest.mark.parametrize(
    "case,text",
    [
        ("field present, today's values", _manifest(TODAY)),
        ("no manifest file", None),
        (
            "entries without the fields (a manifest from before OPEN-555)",
            _manifest([None] * len(READERS)),
        ),
        (
            "no entry for these states",
            yaml.safe_dump({"zz": {"name": "zz", "waf": {"max_attempts": 9}}}),
        ),
        ("every field null", _manifest([NULL] * len(READERS))),
    ],
)
def test_every_reader_returns_todays_value(tmp_path, case, text):
    out = _read(tmp_path, text)
    assert _values(out) == TODAY, case
    assert out["nc_keys"] == ["[S]-1", "2025E1-[S]-1"]


def test_every_reader_reads_the_manifest(tmp_path):
    assert _values(_read(tmp_path, _manifest(OTHER))) == OTHER


def test_mi_env_var_still_wins_over_the_manifest(tmp_path):
    out = _read(tmp_path, _manifest(OTHER), env={"MI_SCRAPELIB_RPM": "5"})
    assert out["mi.bills.MI_SCRAPELIB_RPM"] == 5


def test_fl_scraper_takes_its_cooldown_from_the_module_values():
    """scrape() copies the two module values onto the scraper, where the bill loop reads them."""
    with open(os.path.join(SCRAPERS, "fl", "bills.py")) as f:
        src = f.read()
    assert "self._max_consecutive_failures = FL_COOLDOWN_AFTER_FAILURES" in src
    assert "self._circuit_breaker_timeout = FL_COOLDOWN_SECONDS" in src
