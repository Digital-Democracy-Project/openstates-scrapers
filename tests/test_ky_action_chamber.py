"""OPEN-852: a Kentucky bill action is filed under the chamber that took it.

parse_actions read the chamber from a marker at the end of the line ("to Rules (S)", "received in House") and filed
every other line under the bill's own chamber, so the second chamber's "1st reading", "3rd reading, passed 32-6" and
"veto overridden" were filed as the first chamber's. Only the signature line "enrolled, signed by President of the
Senate" reached the other chamber, which is why a bill could reach "Passed both chambers" only through it (OPEN-845).

The action lists are apps.legislature.ky.gov's own, 2026RS, as stored (description, date) on the Mac replica. The
expected chamber of each line was read off the bill's history: the chamber that received the bill last, or the one the
line names. Every tally line agrees with the chamber of the stored roll call with the same date and tally (OPEN-688
files roll calls by the PDF page's own header), noted beside it.
"""
import os
import sys

import lxml.html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402
from ky.bills import KYBillScraper  # noqa: E402

HB_10 = [
    ("01/16/26", "introduced in House", "lower"),
    ("01/16/26", "to Committee on Committees (H)", "lower"),
    ("01/27/26", "to State Government (H)", "lower"),
    (
        "02/12/26",
        "reported favorably, 1st reading, to Calendar with Committee Substitute (1) and Committee Amendment (1-title)",
        "lower",
    ),
    ("02/13/26", "2nd reading, to Rules", "lower"),
    (
        "02/17/26",
        "posted for passage in the Regular Orders of the Day for Wednesday, February 18 2026",
        "lower",
    ),
    (
        "02/18/26",
        "3rd reading, passed 78-18 with Committee Substitute (1) and  Committee Amendment (1-title)",
        "lower",
    ),
    ("02/19/26", "received in Senate", "upper"),
    ("02/19/26", "to Committee on Committees (S)", "upper"),
    ("03/16/26", "to State & Local Government (S)", "upper"),
    ("03/24/26", "taken from State & Local Government (S)", "upper"),
    ("03/24/26", "1st reading", "upper"),
    ("03/24/26", "returned to State & Local Government (S)", "upper"),
    (
        "03/25/26",
        "reported favorably, 2nd reading, to Rules with Committee Substitute (1) and Committee Amendment (1-title)",
        "upper",
    ),
    (
        "03/25/26",
        "posted for passage in the Regular Orders of the Day for Thursday, March 26 2026",
        "upper",
    ),
    (
        "03/26/26",
        "3rd reading, passed 32-6 with Committee Substitute (1) and  Committee Amendment (1-title)",
        "upper",
    ),
    ("03/27/26", "received in House", "lower"),
    ("03/27/26", "to Rules (H)", "lower"),
    (
        "03/31/26",
        "posted for passage for concurrence in Senate Committee Substitute (1) and  Committee Amendment (1-title)",
        "lower",
    ),
    (
        "03/31/26",
        "House refused to concur in Senate Committee Substitute (1) and  Committee Amendment (1-title)",
        "lower",
    ),
    ("03/31/26", "received in Senate", "upper"),
    ("03/31/26", "to Rules (S)", "upper"),
    ("03/31/26", "taken from Rules", "upper"),
    ("03/31/26", "posted for passage for receding from Senate", "upper"),
    (
        "03/31/26",
        "Senate refused to recede from Committee Substitute (1) and  Committee Amendment (1-title)",
        "upper",
    ),
    ("03/31/26", "Conference Committee appointed in House and Senate", "upper"),
    ("04/01/26", "Conference Committee report filed in House and Senate", "upper"),
    ("04/01/26", "Conference Committee report adopted in House and Senate", "upper"),
    ("04/01/26", "Free Conference Committee appointed in House and Senate", "upper"),
    ("04/01/26", "Free Conference Committee report filed in House and Senate", "upper"),
    (
        "04/01/26",
        "posted for passage for consideration of Free Conference Conference Committee Report",
        "upper",
    ),
    ("04/01/26", "Free Conference Committee report adopted in Senate", "upper"),
    ("04/01/26", "passed 32-5", "upper"),
    ("04/01/26", "received in House", "lower"),
    ("04/01/26", "to Rules (H)", "lower"),
    ("04/01/26", "taken from Rules", "lower"),
    (
        "04/01/26",
        "posted for passage for consideration of Free Conference  Committee Report",
        "lower",
    ),
    ("04/01/26", "Free Conference Committee report adopted in House", "lower"),
    ("04/01/26", "passed 72-17", "lower"),
    ("04/01/26", "enrolled, signed by Speaker of the House", "lower"),
    ("04/01/26", "enrolled, signed by President of the Senate", "upper"),
    ("04/01/26", "delivered to Governor", "lower"),
    ("04/13/26", "Vetoed", "lower"),
    ("04/14/26", "received in House", "lower"),
    ("04/14/26", "to Rules (H)", "lower"),
    ("04/14/26", "taken from Rules", "lower"),
    ("04/14/26", "posted for consideration of Governor's veto", "lower"),
    ("04/14/26", "veto overridden", "lower"),
    ("04/14/26", "passed 79-19", "lower"),
    ("04/14/26", "received in Senate", "upper"),
    ("04/14/26", "to Rules (S)", "upper"),
    ("04/14/26", "posted for passage for consideration of Governor's veto", "upper"),
    ("04/14/26", "veto overridden", "upper"),
    ("04/14/26", "passed 32-6", "upper"),
    ("04/14/26", "received in House", "lower"),
    ("04/14/26", "enrolled, signed by Speaker of the House", "lower"),
    ("04/14/26", "enrolled, signed by President of the Senate", "upper"),
    ("04/14/26", "delivered to Secretary of State (Acts Ch. 178)", "lower"),
]
SB_10 = [
    ("01/08/26", "introduced in Senate", "upper"),
    ("01/08/26", "to Committee on Committees (S)", "upper"),
    ("01/12/26", "to State & Local Government (S)", "upper"),
    ("01/14/26", "reported favorably, 1st reading, to Calendar", "upper"),
    ("01/15/26", "2nd reading, to Rules", "upper"),
    (
        "01/16/26",
        "posted for passage in the Regular Orders of the Day for Tuesday, January 20, 2026",
        "upper",
    ),
    ("01/20/26", "3rd reading, passed 36-0-1", "upper"),
    ("01/21/26", "received in House", "lower"),
    (
        "03/13/26",
        "to Elections, Const. Amendments & Intergovernmental Affairs (H)",
        "lower",
    ),
    ("03/26/26", "reported favorably, 1st reading, to Calendar", "lower"),
    ("03/26/26", "floor amendments (1) and (2-title) filed", "lower"),
    ("03/27/26", "2nd reading, to Rules", "lower"),
    ("04/01/26", "taken from Rules", "lower"),
    ("04/01/26", "placed in the Orders of the Day", "lower"),
    ("04/01/26", "floor amendment (1) adopted", "lower"),
    (
        "04/01/26",
        "3rd reading, passed 82-12 with Floor Amendment (1) and  Floor Amendment (2-title)",
        "lower",
    ),
    ("04/01/26", "received in Senate", "upper"),
    ("04/01/26", "to Rules (S)", "upper"),
    ("04/01/26", "taken from Rules", "upper"),
    (
        "04/01/26",
        "posted for passage for concurrence in House Floor Amendment (1) and  Floor Amendment (2-title)",
        "upper",
    ),
    (
        "04/01/26",
        "Senate concurred in Floor Amendment (1) and  Floor Amendment (2-title)",
        "upper",
    ),
    ("04/01/26", "passed 36-1", "upper"),
    ("04/01/26", "enrolled, signed by President of the Senate", "upper"),
    ("04/01/26", "enrolled, signed by Speaker of the House", "lower"),
    ("04/01/26", "delivered to Secretary of State (Acts Ch. 12)", "upper"),
]
SCR_9 = [
    ("01/06/26", "introduced in Senate", "upper"),
    ("01/06/26", "to Committee on Committees (S)", "upper"),
    ("01/12/26", "to Health Services (S)", "upper"),
    ("01/14/26", "reported favorably, 1st reading, to Calendar", "upper"),
    ("01/15/26", "2nd reading, to Rules", "upper"),
    (
        "01/16/26",
        "posted for passage in the Regular Orders of the Day for Tuesday, January 20, 2026",
        "upper",
    ),
    ("01/20/26", "passed over and retained in the Orders of the Day", "upper"),
    ("01/21/26", "3rd reading, adopted 37-0", "upper"),
    ("01/22/26", "received in House", "lower"),
    ("01/22/26", "to Committee on Committees (H)", "lower"),
    ("02/25/26", "to Health Services (H)", "lower"),
    ("02/26/26", "reported favorably, 1st reading, to Calendar", "lower"),
    ("02/27/26", "2nd reading, to Rules", "lower"),
    (
        "03/18/26",
        "posted for passage in the Regular Orders of the Day for Thursday, March 19 2026",
        "lower",
    ),
    ("03/27/26", "floor amendment (1) filed", "lower"),
    ("03/31/26", "floor amendments (2) and (3-title) filed", "lower"),
    ("04/01/26", "floor amendment (2) adopted", "lower"),
    (
        "04/01/26",
        "3rd reading, adopted 88-0 with Floor Amendment (2) and  Floor Amendment (3-title)",
        "lower",
    ),
    ("04/01/26", "received in Senate", "upper"),
    ("04/01/26", "to Rules (S)", "upper"),
    ("04/01/26", "taken from Rules", "upper"),
    (
        "04/01/26",
        "posted for passage for concurrence in House Floor Amendment (2) and  Floor Amendment (3-title)",
        "upper",
    ),
    (
        "04/01/26",
        "Senate concurred in Floor Amendment (2) and  Floor Amendment (3-title)",
        "upper",
    ),
    ("04/01/26", "passed 36-0", "upper"),
    ("04/01/26", "enrolled, signed by President of the Senate", "upper"),
    ("04/01/26", "enrolled, signed by Speaker of the House", "lower"),
    ("04/02/26", "delivered to Governor", "upper"),
    ("04/13/26", "signed by Governor (Acts Ch. 139)", "upper"),
]


def page_of(actions):
    """The bill page's action table: one row per date, one <li> per action, in the page's order."""
    rows = []
    for date, text, _ in actions:
        if rows and rows[-1][0] == date:
            rows[-1][1].append(text)
        else:
            rows.append((date, [text]))
    body = "".join(
        "<tr><th>%s</th><td><ul>%s</ul></td></tr>"
        % (date, "".join("<li>%s</li>" % t for t in texts))
        for date, texts in rows
    )
    return lxml.html.fromstring(
        '<html><body><a id="actions"></a><div><table><tbody>%s</tbody></table></div></body></html>'
        % body
    )


def filed(actions, bill_chamber, tmp_path):
    scraper = KYBillScraper({"name": "Kentucky"}, str(tmp_path))
    bill = Bill("X 1", legislative_session="2026RS", chamber=bill_chamber, title="t")
    scraper.parse_actions(page_of(actions), bill, bill_chamber)
    # the chamber is stored as a pseudo id: ~{"classification": "upper"}
    return [
        (a["description"], a["organization_id"].split('"')[-2], a["classification"])
        for a in bill.actions
    ]


def check(actions, bill_chamber, tmp_path):
    got = filed(actions, bill_chamber, tmp_path)
    assert [(text, chamber) for text, chamber, _ in got] == [
        (text, chamber) for _, text, chamber in actions
    ]
    return got


def test_house_bill_with_senate_stage_conference_and_override(tmp_path):
    got = check(HB_10, "lower", tmp_path)
    passages = [(text, chamber) for text, chamber, cls in got if "passage" in cls]
    # roll calls stored for HB 10: 78-18 House, 32-6 Senate (03-26), 32-5 Senate and 72-17 House (04-01),
    # 79-19 House and 32-6 Senate (04-14)
    assert [p for p in passages if not p[0].startswith("enrolled")] == [
        (
            "3rd reading, passed 78-18 with Committee Substitute (1) and  Committee Amendment (1-title)",
            "lower",
        ),
        (
            "3rd reading, passed 32-6 with Committee Substitute (1) and  Committee Amendment (1-title)",
            "upper",
        ),
        ("passed 32-5", "upper"),
        ("passed 72-17", "lower"),
        ("passed 79-19", "lower"),
        ("passed 32-6", "upper"),
    ]


def test_senate_bill_with_house_stage_and_concurrence(tmp_path):
    got = check(SB_10, "upper", tmp_path)
    # roll calls stored for SB 10: 36-0 Senate (01-20), 82-12 House and 36-1 Senate (04-01)
    assert [
        (t, c) for t, c, cls in got if "passage" in cls and not t.startswith("enrolled")
    ] == [
        ("3rd reading, passed 36-0-1", "upper"),
        (
            "3rd reading, passed 82-12 with Floor Amendment (1) and  Floor Amendment (2-title)",
            "lower",
        ),
        ("passed 36-1", "upper"),
    ]


def test_resolution_adopted_in_both_chambers(tmp_path):
    got = check(SCR_9, "upper", tmp_path)
    # roll calls stored for SCR 9: 37-0 Senate (01-21), 88-0 House and 36-0 Senate (04-01). A resolution's roll call
    # reads "adopted", and "passed over and retained" is a bill skipped on the agenda, not a passage.
    assert [
        (t, c) for t, c, cls in got if "passage" in cls and not t.startswith("enrolled")
    ] == [
        ("3rd reading, adopted 37-0", "upper"),
        (
            "3rd reading, adopted 88-0 with Floor Amendment (2) and  Floor Amendment (3-title)",
            "lower",
        ),
        ("passed 36-0", "upper"),
    ]


def test_a_chamber_named_mid_line_is_not_who_acted(tmp_path):
    # the House is asked to concur in the Senate's substitute: the House's line
    actions = [
        ("02/19/26", "received in Senate", "upper"),
        ("03/26/26", "3rd reading, passed 32-6 with Committee Substitute (1)", "upper"),
        ("03/27/26", "received in House", "lower"),
        (
            "03/31/26",
            "posted for passage for concurrence in Senate Committee Substitute (1)",
            "lower",
        ),
        (
            "03/31/26",
            "House refused to concur in Senate Committee Substitute (1)",
            "lower",
        ),
        ("03/31/26", "received in Senate", "upper"),
        ("03/31/26", "Senate refused to recede from Committee Substitute (1)", "upper"),
    ]
    check(actions, "lower", tmp_path)


def test_a_resolutions_second_roll_call_is_its_passage(tmp_path):
    # the stored roll calls for these lines are each chamber's passage ("Final Passage", "Adopt HJR 25"), 100 lines
    # in 2026RS; "adopted by voice vote" was already passage
    scraper = KYBillScraper({"name": "Kentucky"}, str(tmp_path))
    assert scraper.classify_action("adopted 36-0") == "passage"
    assert scraper.classify_action("3rd reading, adopted 37-0") == [
        "reading-3",
        "passage",
    ]
    assert scraper.classify_action("adopted with Committee Substitute (1)") == "passage"
    assert scraper.classify_action("floor amendment (2) adopted") is None
    assert (
        scraper.classify_action("passed over and retained in the Orders of the Day")
        is None
    )
