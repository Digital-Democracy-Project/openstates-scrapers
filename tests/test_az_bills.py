"""Tests for OPEN-83: AZBillScraper's bill_no= targeting.

AZ's scrape() parses every bill_id straight out of the single, already-fetched
bill-list page (https://www.azleg.gov/bills/'s HBTable/SBTable rows) with no
extra request -- the real cost is scrape_bill(), which fires ~5 per-bill API
calls (BillStatusAction, DocType, BillSponsor, Keyword, BillStatusFloorAction).
bill_no= must filter rows *before* scrape_bill() is called, so untargeted bills
never pay that cost, while everything stays inside the single scrape() call
(no per-bill subprocess).

These tests mock scrape_bill and the two network fetches scrape() makes before
it ever reaches the per-bill loop (the initial cookie-priming GET and the
session-select POST) -- no real HTTP request is made.
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from az import Arizona  # noqa: E402
from az.bills import AZBillScraper  # noqa: E402
from openstates.scrape import Bill  # noqa: E402


SESSION = "57th-2nd-regular"
SESSION_ID = 130

BILL_LIST_HTML = """
<html><body>
<select>
<option value="{session_id}" selected="selected">57th Legislature - 2nd Regular</option>
</select>
<div name="HBTable"><tbody>
<tr><th><a href="#">HB2001</a></th></tr>
<tr><th><a href="#">HB2002</a></th></tr>
</tbody></div>
<div name="SBTable"><tbody>
<tr><th><a href="#">SB1075</a></th></tr>
<tr><th><a href="#">SB1076</a></th></tr>
</tbody></div>
</body></html>
""".format(session_id=SESSION_ID).encode("utf-8")


def make_scraper() -> AZBillScraper:
    scraper = AZBillScraper(Arizona(), "/tmp/")

    fake_response = mock.Mock()
    fake_response.content = BILL_LIST_HTML
    fake_response.cookies = {}

    scraper.get = mock.Mock(return_value=fake_response)
    scraper.post = mock.Mock(return_value=fake_response)
    scraper.scrape_bill = mock.Mock(side_effect=lambda *a, **kw: iter([]))

    return scraper


def scraped_bill_ids(scraper) -> list:
    # scrape_bill(chamber, session, bill_id, session_id, start_dt=start_dt)
    return [call.args[2] for call in scraper.scrape_bill.call_args_list]


# ── single-bill form ─────────────────────────────────────────────────────────

def test_scrape_single_bill_no_only_scrapes_matching_bill():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION, bill_no="HB2001"))

    assert scraped_bill_ids(scraper) == ["HB2001"]


# ── multi-bill, comma-separated, across chambers ────────────────────────────

def test_scrape_multi_bill_no_scrapes_both_matching_bills_across_chambers():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION, bill_no="HB2001,SB1075"))

    assert sorted(scraped_bill_ids(scraper)) == ["HB2001", "SB1075"]


# ── normalization: whitespace and case in the requested bill_no ────────────

def test_scrape_bill_no_normalizes_whitespace_and_case():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION, bill_no=" hb 2001 , sb1075"))

    assert sorted(scraped_bill_ids(scraper)) == ["HB2001", "SB1075"]


# ── regression guard: bill_no=None (full scrape) is unaffected ─────────────

def test_scrape_without_bill_no_scrapes_every_row():
    scraper = make_scraper()

    list(scraper.scrape(session=SESSION))

    assert sorted(scraped_bill_ids(scraper)) == [
        "HB2001",
        "HB2002",
        "SB1075",
        "SB1076",
    ]


# ── OPEN-123: warn when a requested bill_no matched nothing ─────────────────
#
# Before this, a typo or stale number in a targeted backfill scraped zero bills
# and exited cleanly -- indistinguishable from "that bill had nothing to
# recover". The matched set is accumulated across BOTH chamber tables before
# the diff, since a requested number only ever appears in one of them.


def capture_warnings(scraper) -> list:
    warnings = []
    scraper.warning = lambda msg: warnings.append(msg)
    return warnings


def test_scrape_warns_on_unmatched_bill_no():
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no="HB2001,HB4040"))

    assert any("HB4040" in msg for msg in warnings)
    assert not any("HB2001" in msg for msg in warnings)
    # VA's wording names the session, which is what makes the warning actionable
    # when a number is valid in one session but not the one being scraped.
    assert any(SESSION in msg for msg in warnings)


def test_scrape_does_not_warn_when_every_requested_bill_no_matched():
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no="HB2001,SB1075"))

    assert warnings == []


def test_scrape_does_not_warn_for_a_match_in_the_other_chamber_table():
    # A Senate target is only found while walking SBTable -- diffing per chamber
    # would warn about it during the House pass. Guards that regression.
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no="SB1075"))

    assert warnings == []


def test_scrape_does_not_warn_on_whitespace_or_case_difference():
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION, bill_no=" hb 2001 "))

    assert warnings == []


def test_scrape_without_bill_no_never_warns():
    # bill_no is unset on every scheduled production run -- that path must not
    # gain any new warning behaviour.
    scraper = make_scraper()
    warnings = capture_warnings(scraper)

    list(scraper.scrape(session=SESSION))

    assert warnings == []


# ── OPEN-404: per-voter "NV" mapping kept, version-note suffix held back ────
#
# openstates-scrapers #5807 did two things. The per-voter "NV" -> "not voting"
# mapping is kept. The " (<document Id>)" suffix on repeated DocumentName values
# is held back (it splits stored versions and defeats core's
# is_procedural_document for failed amendments), so same-named documents in one
# bill must still collapse into a single version, as they did before #5807.


def json_response(payload):
    resp = mock.Mock()
    resp.content = json.dumps(payload).encode("utf-8")
    resp.url = "https://apps.azleg.gov/api/BillStatusFloorAction?x=1"
    return resp


def floor_vote_page(votes):
    return [
        {
            "Action": "Do Pass",
            "ReportDate": "2026-02-10T10:00:00.000",
            "Ayes": 1,
            "Nays": 1,
            "Present": 1,
            "Absent": 0,
            "Excused": 0,
            "NotVoting": 2,
            "ReferralNumber": 1,
            "Votes": [
                {"Vote": code, "Legislator": {"FullName": name}}
                for code, name in votes
            ],
        }
    ]


def test_scrape_votes_maps_nv_to_not_voting_and_keeps_other_codes():
    scraper = make_scraper()
    bill = Bill("HB2001", legislative_session=SESSION, title="t", chamber="lower")
    scraper.get = mock.Mock(
        return_value=json_response(
            floor_vote_page(
                [
                    ("Y", "Yea Person"),
                    ("N", "Nay Person"),
                    ("NV", "Nv One"),
                    ("NV", "Nv Two"),
                    ("P", "Present Person"),
                    ("E", "Excused Person"),
                    ("A", "Absent Person"),
                ]
            )
        )
    )
    page = {"BillId": 1, "FloorHeaders": [{"BillStatusActionId": 9, "LegislativeBody": "H"}]}

    (vote,) = list(scraper.scrape_votes(bill, page))

    by_option = {}
    for v in vote.votes:
        by_option.setdefault(v["option"], []).append(v["voter_name"])
    assert by_option["not voting"] == ["Nv One", "Nv Two"]
    assert by_option["yes"] == ["Yea Person"]
    assert by_option["no"] == ["Nay Person"]
    assert sorted(by_option["other"]) == ["Absent Person", "Excused Person", "Present Person"]
    counts = {c["option"]: c["value"] for c in vote.counts}
    assert counts["not voting"] == 2
    assert counts["yes"] == 1 and counts["no"] == 1 and counts["other"] == 1


def test_same_named_documents_in_one_bill_get_no_id_suffix():
    scraper = make_scraper()
    bill = Bill("SB1290", legislative_session=SESSION, title="t", chamber="upper")
    name = "HOUSE - Commerce - Strike Everything"
    scraper.get = mock.Mock(
        return_value=json_response(
            [
                {
                    "DocumentGroupName": "Proposed Amendments",
                    "Documents": [
                        {"Id": 540990, "DocumentName": name, "HtmlPath": "", "PdfPath": "https://x/a.pdf"},
                        {"Id": 540993, "DocumentName": name, "HtmlPath": "", "PdfPath": "https://x/b.pdf"},
                    ],
                },
                {
                    "DocumentGroupName": "Adopted Amendments",
                    "Documents": [
                        {"Id": 541432, "DocumentName": name, "HtmlPath": "", "PdfPath": "https://x/c.pdf"},
                    ],
                },
            ]
        )
    )

    scraper.scrape_versions_and_documents(bill, 84816)

    # The pre-#5807 behaviour: one version, note unchanged, no "(<Id>)" suffix.
    assert [v["note"] for v in bill.versions] == [name]
    assert not any("(" in v["note"] for v in bill.versions)


def test_collapsed_same_named_documents_keep_every_link_in_the_one_version():
    """pm-review (OPEN-404): what the hold-back does and does not lose. Two documents with the
    same name collapse into ONE version (the pre-#5807 behaviour), but both documents' links stay
    on it, so neither is unreachable; only the version identity is shared."""
    scraper = make_scraper()
    bill = Bill("SB1290", legislative_session=SESSION, title="t", chamber="upper")
    name = "HOUSE - Commerce - Strike Everything"
    scraper.get = mock.Mock(
        return_value=json_response(
            [
                {
                    "DocumentGroupName": "Proposed Amendments",
                    "Documents": [
                        {"Id": 540990, "DocumentName": name, "HtmlPath": "", "PdfPath": "https://x/GetDocumentPdf/540990/a.pdf"},
                        {"Id": 540993, "DocumentName": name, "HtmlPath": "", "PdfPath": "https://x/GetDocumentPdf/540993/b.pdf"},
                    ],
                }
            ]
        )
    )

    scraper.scrape_versions_and_documents(bill, 84816)

    (version,) = bill.versions
    assert [link["url"] for link in version["links"]] == [
        "https://x/GetDocumentPdf/540990/a.pdf",
        "https://x/GetDocumentPdf/540993/b.pdf",
    ]
