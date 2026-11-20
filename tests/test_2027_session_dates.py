"""OPEN-659: the 2027 session dates the legislatures published (read 2026-11-20).

api-v3 counts a session as current from its start_date, so a wrong date shows a session as
current too early or too late. Florida: flsenate.gov, "The Regular Session convenes on Tuesday,
March 2, 2027" (a regular session lasts at most 60 consecutive days). Utah: le.utah.gov, "2027
General Session of the 67th Legislature January 19, 2027 to March 5, 2027".

The session lists are read from each __init__.py's source: importing the fl and ut packages
needs DDP's openstates-core (openstates.utils.ddp_manifest), which this test image lacks.
"""
import ast
import os

import pytest

SCRAPERS = os.path.join(os.path.dirname(__file__), "..", "scrapers")


def _session(state, identifier):
    tree = ast.parse(open(os.path.join(SCRAPERS, state, "__init__.py")).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            values = dict(zip(keys, node.values))
            ident = values.get("identifier")
            if isinstance(ident, ast.Constant) and ident.value == identifier:
                return {
                    k: v.value for k, v in values.items() if isinstance(v, ast.Constant)
                }
    raise AssertionError(f"{state} has no session {identifier}")


@pytest.mark.parametrize(
    "state,start,end",
    [("fl", "2027-03-02", "2027-04-30"), ("ut", "2027-01-19", "2027-03-05")],
)
def test_2027_dates_are_the_published_ones(state, start, end):
    session = _session(state, "2027")
    assert (session["start_date"], session["end_date"]) == (start, end)
    assert session["start_date"] <= session["end_date"]


def test_active_flags_unchanged():
    # Florida 2027 keeps being scraped (17 pre-filed bills); Utah 2027 has none filed yet
    assert _session("fl", "2027")["active"] is True
    assert _session("ut", "2027")["active"] is False
