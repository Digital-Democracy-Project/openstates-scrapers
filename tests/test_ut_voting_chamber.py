"""OPEN-622: Utah stores a chamber's floor vote line under the chamber that voted.

le.utah.gov's bill JSON gives each action an "owner": the office holding the bill after the action. For "House/ passed
3rd reading" that is the "Senate Secretary", so the scraper stored the House's passage under the Senate (930 of 1,260
passage lines on the replica, 2026-11-18), and the broker had to re-point it from the text (`_read_utah`). Concurrence
lines and conference "Final Passage" lines had the same fault, which kept their roll calls from pairing with their own
line. The fixtures are le.utah.gov's own action lists for HB 209, HB 136 and SB 98 (2026GS), as fetched by the
scraper, cut to the action fields.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from ut import Utah  # noqa: E402
from ut.bills import UTBillScraper, voting_chamber  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ut_open622")


class _Response:
    def __init__(self, content):
        self.content = content


def scraped_actions(filename):
    """The bill's actions as the scraper builds them from the fixture: (description, chamber, classification)."""
    scraper = UTBillScraper(Utah(), "/tmp/")
    scraper._start = None  # set by scrape(); a full (not incremental) scrape
    with open(os.path.join(FIXTURES, filename), "rb") as f:
        content = f.read()
    scraper.get = lambda url, verify=None: _Response(content)
    scraper.parse_html_vote = lambda *args, **kwargs: iter(
        []
    )  # the votes are not under test here
    bill = Bill(
        "HB 209",
        legislative_session="2026",
        chamber="lower",
        title="t",
        classification="bill",
    )
    list(
        scraper.scrape_bill_details_from_api(
            bill, "https://le.utah.gov/~2026/bills/static/X.html", "2026GS"
        )
    )
    # organization_id is a pseudo id, "~" + a JSON object: {"classification": "lower"}
    return [
        (
            a["description"],
            json.loads(a["organization_id"][1:])["classification"],
            a["classification"],
        )
        for a in bill.actions
    ]


def chamber_of(actions, description):
    found = [chamber for text, chamber, _ in actions if text == description]
    assert len(found) == 1, (description, found)
    return found[0]


def test_house_passage_owned_by_the_senate_secretary_is_stored_under_the_house():
    # HB 209: "House/ passed 3rd reading", owner "Senate Secretary", House roll call 64 (voteHouse H)
    actions = scraped_actions("HB0209-2026GS.json")
    assert chamber_of(actions, "House/ passed 3rd reading") == "lower"


def test_senate_suspension_passage_owned_by_the_house_clerk_is_stored_under_the_senate():
    # HB 209: "Senate/ passed 2nd & 3rd readings/ suspension", owner "Clerk of the House", Senate roll call 1657
    actions = scraped_actions("HB0209-2026GS.json")
    assert (
        chamber_of(actions, "Senate/ passed 2nd & 3rd readings/ suspension") == "upper"
    )


def test_senate_third_reading_owned_by_the_house_clerk_is_stored_under_the_senate():
    actions = scraped_actions("SB0098-2026GS.json")
    assert chamber_of(actions, "Senate/ passed 3rd reading") == "upper"


def test_a_passage_already_owned_by_its_own_chamber_stays_there():
    # SB 98: "House/ passed 3rd reading" is owned by the "House Speaker" -- already the House
    actions = scraped_actions("SB0098-2026GS.json")
    assert chamber_of(actions, "House/ passed 3rd reading") == "lower"


def test_concurrence_owned_by_the_senate_president_is_stored_under_the_house():
    # HB 209: "House/ concurs with Senate amendment", owner "Senate President", House roll call 1249
    actions = scraped_actions("HB0209-2026GS.json")
    assert chamber_of(actions, "House/ concurs with Senate amendment") == "lower"


def test_refusal_and_conference_final_passage_go_under_the_chamber_that_voted():
    # HB 136: "House/ refuse to concur ..." (owner Senate Secretary) and "House Conference Committee - Final Passage"
    # (owner Senate President; a 57-13-5 House roll call, 1419) are the House's; the Senate's own final passage
    # (owner "Conference Committee") is the Senate's.
    actions = scraped_actions("HB0136-2026GS.json")
    assert (
        chamber_of(actions, "House/ refuse to concur with Senate amendment") == "lower"
    )
    house_final = [
        c
        for text, c, _ in actions
        if text.startswith("House Conference Committee - Final Passage")
    ]
    senate_final = [
        c
        for text, c, _ in actions
        if text.startswith("Senate Conference Committee - Final Passage")
    ]
    assert house_final == ["lower"] and senate_final == ["upper"]
    assert (
        chamber_of(actions, "House/ substitute adoption failed") == "lower"
    )  # owner House calendar


def test_other_lines_keep_the_owner_chamber():
    # Only floor vote lines move. "House/ to Senate" (owner Senate Secretary) and the presiding officers' "signed by"
    # lines stay where the owner puts them.
    actions = scraped_actions("HB0209-2026GS.json")
    assert (
        chamber_of(actions, "Senate/ passed 2nd reading") == "upper"
    )  # owner Senate calendar
    to_senate = [c for text, c, _ in actions if text == "House/ to Senate"]
    assert to_senate and all(c == "upper" for c in to_senate)
    assert (
        chamber_of(actions, "Senate/ signed by President/ returned to House") == "lower"
    )


def test_only_the_chamber_changes_not_the_labels():
    actions = scraped_actions("HB0209-2026GS.json")
    labels = {text: cls for text, _, cls in actions}
    assert labels["House/ passed 3rd reading"] == ["passage"]
    assert (
        labels["Senate/ passed 2nd & 3rd readings/ suspension"] == []
    )  # core's classify_action adds passage


@pytest.mark.parametrize(
    "description, chamber",
    [
        ("House/ passed 3rd reading", "lower"),
        ("Senate/ passed 3rd reading", "upper"),
        ("Senate/ passed 2nd & 3rd readings/ suspension", "upper"),
        ("House/ passed 2nd & 3rd readings/ suspension", "lower"),
        ("House/ concurs with Senate amendment", "lower"),
        ("Senate/ concurs with House amendment", "upper"),
        ("House/ refuse to concur with Senate amendment", "lower"),
        ("Senate/ refuse to concur with House amendments", "upper"),
        ("House/ failed", "lower"),
        ("Senate/ failed", "upper"),
        ("House Conference Committee - Final Passage", "lower"),
        ("Senate Conference Committee - Final Passage", "upper"),
        ("Senate/ passed 2nd reading", None),
        ("House/ substitute adoption failed", None),
        ("House/ floor amendment failed", None),
        ("Senate/ signed by President/ returned to House", None),
        ("House/ to Senate", None),
        ("House Conference Committee Appointed", None),
        ("passed 3rd reading", None),
        ("", None),
        (None, None),
    ],
)
def test_voting_chamber(description, chamber):
    assert voting_chamber(description) == chamber
