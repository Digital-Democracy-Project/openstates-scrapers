"""OPEN-642 (PLAN-companion-lineage §5.2): Florida's own links between bills.

* The "Related Bills" table: "Identical" is a companion; "Similar", "Compare", "Linked" and any other word are
  related (Ramon, D1 2026-11-19: "Identical only"). The legislature's word is kept as the label (OPEN-640).
* The history line "companion bill(s) passed, see CS/HB 1145 (Ch. 2025-144)" makes a companion link labelled
  "companion bill(s) passed" (D3).
* The table writes a bill as "S 318" without its type, so the full identifier comes from the session's bill list
  (BillIdList); a row not in that list is skipped, never guessed.

The rows below are copied from flsenate.gov's own bill pages (read 2026-11-21), trimmed to the columns the scraper
reads plus "Last Action", which names other bills' companions and must not be read as this bill's.
"""
import collections
import os
import sys

import lxml.html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.scrape import Bill  # noqa: E402

from fl.bills import (  # noqa: E402
    BillDetail,
    BillIdList,
    BillList,
    _fl_bill_key,
)


def _page(identifier, session, history_rows="", related_rows="", bill_ids=None):
    bill = Bill(identifier, session, "title", chamber="lower", classification="bill")
    bill._fl_bill_ids = bill_ids or {}
    page = BillDetail(bill)
    page.root = lxml.html.fromstring(
        "<html><body>"
        f"<div id='tabBodyBillHistory'><table><tbody>{history_rows}</tbody></table></div>"
        f"<div class='tabbody' id='tabBodyRelatedBills'><table class='tbl'><tbody>{related_rows}</tbody></table></div>"
        "</body></html>"
    )
    return page


def _links(bill):
    return sorted(
        (
            r["identifier"],
            r["legislative_session"],
            r["relation_type"],
            r["ddp_relation_label"],
        )
        for r in bill.related_bills
    )


def _history(text, date="6/16/2025"):
    return f"<tr><td>{date}</td><td></td><td>{text}</td></tr>"


# 2025 CS/HB 1145 (Workforce Education): one Identical row, two Compare rows, and its own history line naming the
# companion that passed ("CS/CS/CS HB 1105", written with a space before HB).
HB1145_RELATED = """
<tr> <td> <a href="/Session/Bill/2025/742">S 742</a> <span>(c1)</span> </td> <td>Workforce Education</td> <td class="centertext">Simon</td> <td class="centertext">Identical</td> <td> Last Action: 4/29/2025 S Laid on Table, companion bill(s) passed, see CS/HB 1145 (Ch. 2025-144), CS/CS/CS/HB 1105 (Ch. 2025-109) -SJ 608 </td> </tr>
<tr> <td> <a href="/Session/Bill/2025/1105">H 1105</a> <span>(er)</span> </td> <td>Education</td> <td class="centertext">Careers &amp; Workforce Subcommittee</td> <td class="centertext">Compare</td> <td> Last Action: 6/2/2025 Chapter No. 2025-109, companion bill(s) passed, see CS/HB 1145 (Ch. 2025-144) </td> </tr>
<tr> <td> <a href="/Session/Bill/2025/140">S 140</a> <span>(c2)</span> </td> <td>Charter Schools</td> <td class="centertext">Gaetz</td> <td class="centertext">Compare</td> <td> Last Action: 6/16/2025 H Died on Second Reading Calendar, companion bill(s) passed, see CS/CS/CS/HB 1105 (Ch. 2025-109), CS/HB 1145 (Ch. 2025-144) </td> </tr>
"""
HB1145_HISTORY = _history(
    ' • Chapter No. <a href="http://laws.flrules.org/2025/144">2025-144</a>, companion bill(s) passed, see CS/CS/CS '
    '<a href="/Session/Bill/2025/1105">HB 1105</a> (Ch. <a href="http://laws.flrules.org/2025/109">2025-109</a>)<br>'
)
IDS_2025 = {
    ("S", "742"): "SB 742",
    ("H", "1105"): "HB 1105",
    ("S", "140"): "SB 140",
    ("S", "318"): "SJR 318",
}


def test_identical_is_a_companion_and_compare_is_related_with_the_legislatures_word():
    page = _page("HB 1145", "2025", related_rows=HB1145_RELATED, bill_ids=IDS_2025)

    page.process_related_bills()

    assert _links(page.input) == [
        ("HB 1105", "2025", "related", "Compare"),
        ("SB 140", "2025", "related", "Compare"),
        ("SB 742", "2025", "companion", "Identical"),
    ]


def test_the_history_line_names_the_companion_that_passed():
    page = _page("HB 1145", "2025", history_rows=HB1145_HISTORY)

    page.process_history()

    assert _links(page.input) == [
        ("HB 1105", "2025", "companion", "companion bill(s) passed")
    ]


def test_process_page_reads_both_and_never_the_last_action_column():
    # The "Last Action" column names other bills' companions (CS/HB 1145 itself, among others): read through
    # process_page, only the four links above come out.
    page = _page("HB 1145", "2025", HB1145_HISTORY, HB1145_RELATED, IDS_2025)

    list(page.process_page())

    assert _links(page.input) == [
        ("HB 1105", "2025", "companion", "companion bill(s) passed"),
        ("HB 1105", "2025", "related", "Compare"),
        ("SB 140", "2025", "related", "Compare"),
        ("SB 742", "2025", "companion", "Identical"),
    ]


def test_the_table_bill_gets_its_full_identifier_from_the_session_list():
    # 2025 CS/HJR 1215's Identical row says "S 318"; the Senate's bill is SJR 318, not SB 318.
    related = (
        '<tr> <td> <a href="/Session/Bill/2025/318">S 318</a> <span>(c1)</span> </td> <td>Ad Valorem Tax Exemption</td>'
        ' <td class="centertext">Truenow</td> <td class="centertext">Identical</td> <td> Last Action: 6/16/2025 S Died'
        " on Calendar, companion bill(s) passed, see CS/HJR 1215 (Passed) </td> </tr>"
    )
    page = _page("HJR 1215", "2025", related_rows=related, bill_ids=IDS_2025)

    page.process_related_bills()

    assert _links(page.input) == [("SJR 318", "2025", "companion", "Identical")]


def test_a_row_missing_from_the_session_list_is_skipped_not_guessed(caplog):
    page = _page(
        "HB 1145",
        "2025",
        related_rows=HB1145_RELATED,
        bill_ids={("S", "742"): "SB 742"},
    )

    with caplog.at_level("WARNING"):
        page.process_related_bills()

    assert _links(page.input) == [("SB 742", "2025", "companion", "Identical")]
    assert (
        sum(
            "not found in session 2025's bill list" in r.message for r in caplog.records
        )
        == 2
    )


def test_linked_and_similar_are_related_and_every_bill_named_in_the_line_is_a_companion():
    # 2024 CS/SB 7016 (Health Care): "Linked" and "Similar" rows; its chapter-law line names five companions.
    related = (
        '<tr> <td> <a href="/Session/Bill/2024/322">S 322</a> <span>(er)</span> </td> <td>Public Records and'
        ' Meetings</td> <td class="centertext">Burton</td> <td class="centertext">Linked</td> <td> Last Action:'
        " 3/22/2024 Chapter No. 2024-13 </td> </tr>"
        '<tr> <td> <a href="/Session/Bill/2024/1549">H 1549</a> <span>(c2)</span> </td> <td>Health Care</td>'
        ' <td class="centertext">Health Care Appropriations Subcommittee</td> <td class="centertext">Similar</td>'
        " <td> Last Action: 2/21/2024 H Laid on Table </td> </tr>"
    )
    history = _history(
        ' • Chapter No. <a href="http://laws.flrules.org/2024/15">2024-15</a>, companion bill(s) passed, see'
        ' <a href="/Session/Bill/2024/322">SB 322</a> (Ch. <a href="x">2024-13</a>), <a href="/Session/Bill/2024/975">'
        'CS/CS/HB 975</a> (Ch. <a href="x">2024-243</a>), <a href="/Session/Bill/2024/7021">CS/CS/HB 7021</a> (Ch.'
        ' <a href="x">2024-245</a>), <a href="/Session/Bill/2024/1600">CS/SB 1600</a> (Ch. <a href="x">2024-274</a>),'
        ' <a href="/Session/Bill/2024/2518">SB 2518</a> (Ch. <a href="x">2024-227</a>)<br>',
        date="3/22/2024",
    )
    page = _page(
        "SB 7016",
        "2024",
        history,
        related,
        {("S", "322"): "SB 322", ("H", "1549"): "HB 1549"},
    )

    page.process_history()
    page.process_related_bills()

    label = "companion bill(s) passed"
    assert _links(page.input) == [
        ("HB 1549", "2024", "related", "Similar"),
        ("HB 7021", "2024", "companion", label),
        ("HB 975", "2024", "companion", label),
        ("SB 1600", "2024", "companion", label),
        ("SB 2518", "2024", "companion", label),
        ("SB 322", "2024", "companion", label),
        ("SB 322", "2024", "related", "Linked"),
    ]


def test_actions_that_name_no_companion_make_no_link():
    history = "".join(
        [
            _history(" • Laid on Table -SJ 608"),
            _history(" • Died in Rules"),
            _history(" • Read 3rd time; Passed (Vote: 38 Yeas / 0 Nays)"),
            _history(" • Substituted CS/HB 1145; Laid on Table, refer to CS/HB 1145"),
            _history(
                " • Chapter No. 2025-144, companion bill(s) passed, see (Ch. 2025-144)"
            ),
        ]
    )
    page = _page("SB 742", "2025", history_rows=history)

    page.process_history()

    assert page.input.related_bills == []


def test_wording_variants_special_sessions_and_repeats():
    # Seen on the replica: "companion bills", a capital "Companion", extra spaces, ";", and special-session
    # numbers written "5001-E" or "5001E" (stored as "HB 5001E"); a bill named on two lines is linked once.
    history = "".join(
        [
            _history(
                " • Laid on Table; Companion bills passed,  see  SB 2508-E (Ch. 2026-231)"
            ),
            _history(
                " • Died in Appropriations, companion bill(s) passed, see HB 5001E (Ch. 2026-232)"
            ),
            _history(
                " • Laid on Table, companion bill(s) passed, see HB 5001-E (Ch. 2026-232), HB 5003-E (Ch. 2026-233)"
            ),
        ]
    )
    page = _page("SB 2500E", "2026E", history_rows=history)

    page.process_history()

    label = "companion bill(s) passed"
    assert _links(page.input) == [
        ("HB 5001E", "2026E", "companion", label),
        ("HB 5003E", "2026E", "companion", label),
        ("SB 2508E", "2026E", "companion", label),
    ]


def test_a_bill_never_links_to_itself():
    page = _page(
        "HB 1145",
        "2025",
        history_rows=_history(
            " • companion bill(s) passed, see CS/HB 1145 (Ch. 2025-144)"
        ),
    )

    page.process_history()

    assert page.input.related_bills == []


def test_the_bill_key_is_chamber_and_number_whatever_the_type():
    assert _fl_bill_key("SJR 318") == ("S", "318")
    assert _fl_bill_key("S 318") == ("S", "318")
    assert _fl_bill_key("HB 11A") == ("H", "11")
    assert _fl_bill_key("SPB 7016") == ("S", "7016")


def test_bill_id_list_reads_the_identifier_and_bill_list_hands_the_map_on():
    root = lxml.html.fromstring(
        "<table><tbody><tr><th><a href='/Session/Bill/2025/318'>SJR 318</a></th>"
        "<td>Ad Valorem Tax Exemption</td><td>x</td><td>6/16/2025</td></tr></tbody></table>"
    )
    anchor = root.xpath("//th/a")[0]
    assert BillIdList({"session": "2025"}).process_item(anchor) == "SJR 318"

    page = BillList(
        {
            "session": "2025",
            "house_session_number": "104",
            "start": None,
            "bill_nos": None,
            "matched_bill_nos": set(),
            "subjects": collections.defaultdict(set),
            "bill_ids": IDS_2025,
        }
    )
    detail = page.process_item(anchor)
    assert detail.input._fl_bill_ids is IDS_2025


def test_a_special_session_row_resolves_by_chamber_and_number():
    # 2025C SB 2-C (Immigration): the row reads "H 1C" and links /Session/Bill/2025C/1C; the House's bill is HB 1C.
    related = (
        '<tr> <td> <a href="/Session/Bill/2025C/1C">H 1C</a> </td> <td>Immigration</td>'
        ' <td class="centertext">x</td> <td class="centertext">Identical</td> <td> Last Action: x </td> </tr>'
    )
    page = _page("SB 2C", "2025C", related_rows=related, bill_ids={("H", "1"): "HB 1C"})

    page.process_related_bills()

    assert _links(page.input) == [("HB 1C", "2025C", "companion", "Identical")]


def test_a_row_whose_link_disagrees_with_its_text_is_skipped(caplog):
    # Text says S 742, but the link points at 740, into another session, or nowhere: none is guessed.
    related = (
        '<tr> <td> <a href="/Session/Bill/2025/740">S 742</a> </td> <td>x</td> <td>x</td>'
        " <td>Identical</td> <td>x</td> </tr>"
        '<tr> <td> <a href="/Session/Bill/2024/742">S 742</a> </td> <td>x</td> <td>x</td>'
        " <td>Identical</td> <td>x</td> </tr>"
        '<tr> <td> <a href="">S 742</a> </td> <td>x</td> <td>x</td> <td>Identical</td> <td>x</td> </tr>'
        "<tr> <td> <a>S 742</a> </td> <td>x</td> <td>x</td> <td>Identical</td> <td>x</td> </tr>"
    )
    bill_ids = {("S", "742"): "SB 742", ("S", "740"): "SB 740"}
    page = _page("HB 1145", "2025", related_rows=related, bill_ids=bill_ids)

    with caplog.at_level("WARNING"):
        page.process_related_bills()

    assert page.input.related_bills == []
    assert sum("link skipped" in r.message for r in caplog.records) == 4
