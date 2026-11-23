"""OPEN-801: Montana's versions were named by their file name ("HB0017_1.pdf"), which has no stage.

openstates-core's note_stage() had no stage for any of them: 294 of the 294 versions of the 2027
pre-filing scrape (Mac replica, 2026-11-23). The legislature names each text's file after the bill
and its version number, and the drafted bill after its LC number. What each one is, read from the
texts themselves (first_lines.txt) and the bills API's actions (2026-11-23):

* "SB0260_1.pdf": the bill as introduced ("SB 260.1", "INTRODUCED BY G. HERTZ ...").
* "SB0260_2.pdf" ... "_4.pdf": the bill reprinted after an amendment ("SB0260.2"; _2 after the Senate
  committee report, _3 after the House committee report, _4 after a House 2nd reading amendment).
* "SB0260_X.pdf": the enrolled act ("AN ACT PROVIDING FOR ...").
* "LC0382.pdf" (getBillLcs): the drafted bill before introduction ("_____ BILL NO. _____").
* "SB0260_X(3).pdf": a later upload of the same version.
* getBillAmendments and getBillOther: amendments ("SB0260.001.001_Amendments-in-Context_...") and
  the governor's veto papers ("HB0002GovVeto.pdf"), which are not texts of the bill.

tests/fixtures/mt_open801/document_responses.json holds the legislature's own answers (saved
2026-11-23, each document cut to its id, file name and date; HB 2's 255 amendment papers cut to
the first five) for 2025 SB 260, HB 477, SB 1, SB 116, HB 2, and 2027 HB 16 with its LC draft.
"""
import json
import os
import sys

import pytest
import scrapelib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from mt.bills import MTBillScraper, version_name  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from openstates.utils.version_ordering import (  # noqa: E402
    STAGE_AMENDMENT,
    STAGE_FINAL_PASSAGE,
    STAGE_INTRODUCED,
    STAGE_UNKNOWN,
    note_stage,
    version_sort_key,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "mt_open801")
CONTENT = "https://api.legmt.gov/docs/v1/documents/getContent?documentId="

with open(os.path.join(FIXTURES, "document_responses.json"), encoding="utf-8") as f:
    SAVED = json.load(f)


class _Resp:
    def __init__(self, data, status=200, url=None):
        self.data, self.status_code, self.url, self.text = data, status, url, ""

    def json(self):
        return self.data


def _scraper(session_ord, mt_session_id):
    asked = []

    def get(url):
        asked.append(url)
        answer = SAVED.get(url)
        if answer is None or answer["status"] != 200:
            raise scrapelib.HTTPError(_Resp(None, 404, url))
        return _Resp(answer["body"])

    scraper = MTBillScraper.__new__(MTBillScraper)
    scraper.session_ord, scraper.mt_session_id = session_ord, mt_session_id
    scraper.get = get
    return scraper, asked


def _bill(identifier, session="2025"):
    return Bill(identifier, legislative_session=session, chamber="upper", title="t")


def _files(url):
    return {d["fileName"]: d["id"] for d in SAVED[url]["body"]}


def _url(endpoint, bill_type, number, ordinal=69, session="20251"):
    return (
        f"https://api.legmt.gov/docs/v1/documents/getBill{endpoint}?legislatureOrdinal={ordinal}"
        f"&sessionOrdinal={session}&billType={bill_type}&billNumber={number}"
    )


@pytest.mark.parametrize(
    ("file_name", "name"),
    [
        ("SB0260_1.pdf", "Introduced"),
        ("SB0260_2.pdf", "Amended Version 2"),
        ("SB0260_3.pdf", "Amended Version 3"),
        ("SB0260_4.pdf", "Amended Version 4"),
        ("HB0477_5.pdf", "Amended Version 5"),
        ("SB0260_X.pdf", "Enrolled"),
        # before 2021 the enrolled file's letter is lower case (2017 HB0217_x.pdf, mt_open750)
        ("HB0217_x.pdf", "Enrolled"),
        ("HB0016_1.pdf", "Introduced"),
        ("LC0382.pdf", "Bill Draft"),
        # later uploads of a version are that version
        ("SB0260_1(5).pdf", "Introduced"),
        ("SB0260_2(15).pdf", "Amended Version 2"),
        ("SB0260_X(17).pdf", "Enrolled"),
        # HB 2's own file names (the budget bill) say no version number: they keep their names
        ("HB0002.002.004.pdf", "HB0002.002.004.pdf"),
        ("HB0002.AP.003.pdf", "HB0002.AP.003.pdf"),
        ("HB0002_0.pdf", "HB0002_0.pdf"),
        # (core's generic "veto" rule gives this one a stage already)
        ("HB0002_X-pre_veto.pdf", "HB0002_X-pre_veto.pdf"),
    ],
)
def test_version_name_from_the_file_name(file_name, name):
    assert version_name(file_name) == name


@pytest.mark.parametrize(
    ("name", "stage"),
    [
        ("Bill Draft", (STAGE_INTRODUCED, -1.0)),
        ("Introduced", (STAGE_INTRODUCED, 0.0)),
        ("Amended Version 2", (STAGE_AMENDMENT, 2.0)),
        ("Amended Version 5", (STAGE_AMENDMENT, 5.0)),
        ("Enrolled", (STAGE_FINAL_PASSAGE, 0.0)),
    ],
)
def test_every_name_has_its_stage_in_core(name, stage):
    assert note_stage(name) == stage


def test_sb260_versions_by_stage_with_every_upload_as_a_link():
    scraper, asked = _scraper(69, "20251")
    bill = _bill("SB 260")
    scraper.scrape_versions(bill, "SB", 260)
    assert asked == [_url(e, "SB", 260) for e in ("Versions", "Amendments", "Other")]

    files = _files(_url("Versions", "SB", 260))
    by_name = {v["note"]: [link["url"] for link in v["links"]] for v in bill.versions}
    assert list(by_name) == [
        "Introduced",
        "Amended Version 2",
        "Amended Version 3",
        "Amended Version 4",
        "Enrolled",
    ]
    for name, prefix in [
        ("Introduced", "SB0260_1"),
        ("Amended Version 2", "SB0260_2"),
        ("Amended Version 3", "SB0260_3"),
        ("Amended Version 4", "SB0260_4"),
        ("Enrolled", "SB0260_X"),
    ]:
        expected = sorted(
            CONTENT + str(i) for f, i in files.items() if f.startswith(prefix)
        )
        assert sorted(by_name[name]) == expected
        assert CONTENT + str(files[prefix + ".pdf"]) in by_name[name]
    # every file of getBillVersions is linked, once
    assert sum(len(v) for v in by_name.values()) == len(files) == 57

    # the amendment papers are documents, named by their file
    amendments = _files(_url("Amendments", "SB", 260))
    assert {d["note"]: d["links"][0]["url"] for d in bill.documents} == {
        f: CONTENT + str(i) for f, i in amendments.items()
    }


def test_veto_papers_and_letters_are_documents():
    scraper, _ = _scraper(69, "20251")
    bill = _bill("HB 477")
    scraper.scrape_versions(bill, "HB", 477)
    other = _files(_url("Other", "HB", 477))
    assert set(other) == {
        "25.05.02 - Ltr. to Speaker Ler, President Regier - HB 477 (1).pdf",
        "HB0477GovVeto.pdf",
    }
    notes = {d["note"] for d in bill.documents}
    assert set(other) <= notes
    assert not set(other) & {v["note"] for v in bill.versions}
    assert [v["note"] for v in bill.versions] == [
        "Introduced",
        "Amended Version 2",
        "Amended Version 3",
        "Amended Version 4",
        "Amended Version 5",
        "Enrolled",
    ]


def test_2027_prefiled_bill_and_its_draft():
    scraper, asked = _scraper(70, "20271")
    bill = _bill("HB 16", "2027")
    scraper.scrape_versions(bill, "HB", 16)
    scraper.scrape_lc_versions(bill, "LC0382")
    assert asked[-1] == (
        "https://api.legmt.gov/docs/v1/documents/getBillLcs?legislatureOrdinal=70"
        "&sessionOrdinal=20271&lcnumber=LC0382"
    )
    assert [
        (v["note"], [link["url"] for link in v["links"]]) for v in bill.versions
    ] == [
        ("Introduced", [CONTENT + "16809565"]),
        ("Bill Draft", [CONTENT + "16602072"]),
    ]
    assert bill.documents == []


@pytest.mark.parametrize(
    ("bill_type", "number", "true_order"),
    [
        # the legislature's own numbering: 1, 2, ..., then X (each later number printed later)
        (
            "SB",
            260,
            [
                "Introduced",
                "Amended Version 2",
                "Amended Version 3",
                "Amended Version 4",
                "Enrolled",
            ],
        ),
        (
            "HB",
            477,
            [
                "Introduced",
                "Amended Version 2",
                "Amended Version 3",
                "Amended Version 4",
                "Amended Version 5",
                "Enrolled",
            ],
        ),
        # _3 was printed at enrolling and is the enrolled text itself (byte-identical to _X)
        ("SB", 1, ["Introduced", "Amended Version 2", "Amended Version 3", "Enrolled"]),
        # no _3; _4 and _5 carry the governor's amendments, and later uploads of _X the act as signed
        (
            "SB",
            116,
            [
                "Introduced",
                "Amended Version 2",
                "Amended Version 4",
                "Amended Version 5",
                "Enrolled",
            ],
        ),
    ],
)
def test_2025_versions_rank_in_the_legislatures_order(bill_type, number, true_order):
    scraper, _ = _scraper(69, "20251")
    bill = _bill(f"{bill_type} {number}")
    scraper.scrape_versions(bill, bill_type, number)
    names = [v["note"] for v in bill.versions]
    assert sorted(names) == sorted(true_order)
    for stored in (names, names[::-1], ["Bill Draft"] + names[::-1]):
        ranked = sorted(
            stored, key=lambda n: version_sort_key(n, "", [], None, "Montana")
        )
        assert ranked == [n for n in ["Bill Draft"] + true_order if n in stored]


def test_no_version_of_these_bills_is_without_a_stage_except_hb2s_own_files():
    unknown = []
    for bill_type, number in [
        ("SB", 260),
        ("HB", 477),
        ("SB", 1),
        ("SB", 116),
        ("HB", 2),
    ]:
        scraper, _ = _scraper(69, "20251")
        bill = _bill(f"{bill_type} {number}")
        scraper.scrape_versions(bill, bill_type, number)
        unknown += [
            v["note"]
            for v in bill.versions
            if note_stage(v["note"])[0] == STAGE_UNKNOWN
        ]
    assert sorted(unknown) == [
        "HB0002.002.004.pdf",
        "HB0002.003.002.pdf",
        "HB0002.004.002.pdf",
        "HB0002.005.003.pdf",
        "HB0002.AP.003.pdf",
        "HB0002_0(1).pdf",
        "HB0002_0.pdf",
    ]


def test_a_versions_last_link_is_its_newest_upload():
    # A version's later uploads can hold a later text: SB 116's _X was enrolled on 2025-04-03, then the governor's
    # amendments were adopted, and its newest upload "SB0116_X(30).pdf" (2025-08-05) is the act with them (its title
    # no longer revises the "NUMBER OF THE MEMBERS", pdftotext of both, 2026-11-23). core takes a version's
    # last link by URL as its text (openstates-core text_extract._version_document_order, OPEN-578); that must be the
    # newest upload. (In the 2025 getBillVersions answers it is, for 2,824 of the 2,826 versions with later uploads.)
    scraper, _ = _scraper(69, "20251")
    bill = _bill("SB 116")
    scraper.scrape_versions(bill, "SB", 116)
    docs = SAVED[_url("Versions", "SB", 116)]["body"]
    for version in bill.versions:
        prefix = {"Introduced": "_1", "Enrolled": "_X"}.get(version["note"])
        if prefix is None:
            prefix = "_" + version["note"].rsplit(" ", 1)[1]
        uploads = [d for d in docs if d["fileName"].startswith("SB0116" + prefix)]
        newest = max(uploads, key=lambda d: d["date"])
        assert max(link["url"] for link in version["links"]) == CONTENT + str(
            newest["id"]
        )
    (enrolled,) = [v for v in bill.versions if v["note"] == "Enrolled"]
    assert len(enrolled["links"]) > 1


def test_a_missing_folder_is_still_no_data():
    # getBillVersions answers 404 for a bill with no folder: no versions, the scrape goes on
    scraper, _ = _scraper(70, "20271")
    bill = _bill("HB 9999", "2027")
    scraper.scrape_versions(bill, "HB", 9999)
    scraper.scrape_lc_versions(bill, "LC9999")
    assert bill.versions == [] and bill.documents == []
