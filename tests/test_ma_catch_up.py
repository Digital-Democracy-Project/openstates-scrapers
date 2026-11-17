"""OPEN-609: Massachusetts catch-up runs read the bills the journals, the bill list, Session Laws and hearings name.

Ramon (2026-11-17): "Build it now". Measured over 2026-09-21 to 11-15 (ddp-open-states
notes/ma-journal-change-signal-20261117.md): the four sources together name 98.3% of each week's changed bills, for
about 83 bills a week instead of all ~11,900. A run without a usable record, a run whose full walk is due, and a run
where any source fails or answers implausibly reads every bill instead: never a partial run.

The journal, month-index, Session Laws and hearing fixtures in tests/fixtures/ma_open609 are real malegislature.gov
files fetched 2026-11-17 (the Session Laws page trimmed to 50 of its 270 chapters, the hearing list to 12 events).
hj11122026.pdf is the House journal of 2026-11-12 as served; sj11122026_1100AM.txt is the Senate journal of that day
as `pdftotext -layout` prints it (the PDF is 1.9 MB).
"""
import datetime
import json
import os
import shutil
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates import settings  # noqa: E402
from openstates.exceptions import EmptyScrape  # noqa: E402
from openstates.scrape import Bill  # noqa: E402
from openstates.utils import convert_pdf  # noqa: E402

from ma import Massachusetts  # noqa: E402
from ma import catchup  # noqa: E402
from ma.bills import MABillScraper  # noqa: E402
from ma.votes import journal_date  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ma_open609")
SESSION = "194th"
SITE = "https://malegislature.gov"
TODAY = datetime.datetime.utcnow().date()
needs_pdftotext = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="needs pdftotext (poppler)"
)


def fixture(name, mode="r"):
    with open(os.path.join(FIXTURES, name), mode) as f:
        return f.read()


def house_text():
    return convert_pdf(os.path.join(FIXTURES, "hj11122026.pdf"), "text").decode()


# What the research parser (bin/parse.py, checked by reading every miss) recorded for these two journals.
HOUSE_1112 = {
    "H 4138", "H 5525", "H 5552", "H 5557", "H 5579", "H 5601", "H 5604", "H 5642", "H 5707", "H 5710",
    "H 5713", "H 5719", "S 1851", "S 2383",
}  # fmt: skip
SENATE_1112 = {
    "H 3366", "H 5515", "H 5552", "H 5601", "H 5695", "H 5716", "H 5717", "H 5718", "S 1132", "S 3300",
    "SD 4340", "SD 4349", "SD 4350", "SD 4351", "SD 4352", "SD 4353",
}  # fmt: skip


# --- the sources, on the real files ---


@needs_pdftotext
def test_the_house_list_form_wrapped_across_lines_names_every_bill():
    # "on House, Nos.   <margin note>\n5525, 5557, 5579 and 5642, an Order ... (House, No. 5719)."
    found = catchup.journal_bills(house_text())
    assert {"H 5525", "H 5557", "H 5579", "H 5642", "H 5719"} <= found
    assert found == HOUSE_1112


def test_the_senate_margin_docket_numbers_are_read():
    found = catchup.journal_bills(fixture("sj11122026_1100AM.txt"))
    # SD4349..SD4353 are the docket numbers printed beside the reports and the petition (no "Senate, No.")
    assert {"SD 4349", "SD 4350", "SD 4351", "SD 4352", "SD 4353", "SD 4340"} <= found
    assert found == SENATE_1112


def test_a_margin_note_does_not_join_the_next_lines_number():
    text = (
        "     By Mr. Ryan, for the committee, on House, Nos.                 Disability\n"
        "5525 and 5557, an Order.                                             pensions, 1234\n"
    )
    assert catchup.journal_bills(text) == {"H 5525", "H 5557"}


def test_a_number_hyphenated_across_a_line_break_is_one_number():
    assert catchup.journal_bills(
        "reported on Senate, No. 29-\n50, and House, No. 1."
    ) == {"S 2950", "H 1"}


def test_a_short_range_is_listed_and_a_wide_one_is_not():
    assert catchup.journal_bills("on Senate, Nos. 10 to 13, and House, No. 9.") == {
        "S 10", "S 11", "S 12", "S 13", "H 9",
    }  # fmt: skip
    assert catchup.journal_bills("Senate, Nos. 10 to 900") == {"S 10", "S 900"}


def test_the_session_laws_page_gives_the_bills_signed_since_the_day():
    html = fixture("sessionlaws_2026.html")
    signed, chapters = catchup.session_law_bills(
        html, "194", datetime.date(2026, 11, 1)
    )
    assert chapters == 50
    # the six chapters approved November 5 and 11, 2026
    assert signed == {"H 2926", "H 5345", "H 5358", "H 5399", "H 5435", "H 5497"}
    # "Senate, No. S.2563 A" (a reprint letter) is S 2563, signed June 12
    june, _ = catchup.session_law_bills(html, "194", datetime.date(2026, 6, 12))
    assert {"S 2563", "H 5470"} <= june
    assert "H 5375" not in june  # June 11
    # another session's bill is not this one's
    assert (
        catchup.session_law_bills(
            html.replace("/Bills/194/", "/Bills/193/"), "194", datetime.date(2026, 1, 1)
        )[0]
        == set()
    )


def test_a_hearing_gives_its_agenda_bills_and_dockets():
    assert catchup.hearing_bills(json.loads(fixture("hearing_5818.json")), "194") == {
        "H 5668", "HD 6309",
    }  # fmt: skip
    assert (
        catchup.hearing_bills(json.loads(fixture("hearing_5817.json")), "194") == set()
    )
    assert (
        catchup.hearing_bills(json.loads(fixture("hearing_5818.json")), "195") == set()
    )


def test_a_journal_date_comes_from_the_file_name():
    assert journal_date(SITE + "/Journal/House/194/hj11122026.pdf") == datetime.date(
        2026, 11, 12
    )
    assert journal_date(
        SITE + "/Journal/Senate/194/1167/sj11122026_1100AM.pdf"
    ) == datetime.date(2026, 11, 12)
    assert journal_date(SITE + "/Journal/House/194/2026/RollCalls") is None


# --- a catch-up run ---

START = "2026-11-16T03:00:00"  # since = 2026-10-26: the Oct and Nov journal pages, and later months if any
JOURNALS = {
    SITE + "/Journal/House/194/hj11122026.pdf": "house",
    SITE + "/Journal/Senate/194/1167/sj11122026_1100AM.pdf": "senate",
}
EMPTY_MONTH = '<html><body><table class="journalTable"></table></body></html>'
HEARINGS = json.loads(fixture("hearings.json"))
LAST_HEARINGS = {h["EventId"] for h in HEARINGS} - {5818, 5817}

BILL_LIST = [
    {"BillNumber": "H5525", "DocketNumber": "HD100"},  # the House journal
    {"BillNumber": None, "DocketNumber": "SD4349"},  # a Senate margin docket
    {
        "BillNumber": "H5435",
        "DocketNumber": "HD200",
    },  # signed 2026-11-11 (Session Laws)
    {
        "BillNumber": "H5668",
        "DocketNumber": "HD6309",
    },  # on hearing 5818, posted since the last run
    {"BillNumber": "H5720", "DocketNumber": None},  # new in the list since the last run
    {"BillNumber": "S900", "DocketNumber": "SD300"},  # the last run could not read it
    {"BillNumber": "H1", "DocketNumber": "HD1"},  # named by nothing
    {"BillNumber": "S2", "DocketNumber": "SD2"},  # named by nothing
]
LAST_LIST = {"H 5525", "HD 100", "SD 4349", "H 5435", "HD 200", "H 5668", "HD 6309", "S 900", "SD 300",
             "H 1", "HD 1", "S 2", "SD 2"}  # fmt: skip
CAUGHT_UP = [
    "H5525",
    "H5435",
    "H5668",
    "H5720",
    "SD4349",
    "S900",
]  # House first, as a full run


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode("utf-8", "replace")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CACHE_DIR", str(tmp_path))
    return tmp_path


def write_state(
    full_walk_on=None, hearings=LAST_HEARINGS, bills=LAST_LIST, retry=("S 900",)
):
    catchup.save_state(
        catchup.state_path(SESSION),
        set(bills),
        None if hearings is None else set(hearings),
        full_walk_on or TODAY - datetime.timedelta(days=7),
        set(retry),
    )


def make(
    overrides=None, texts=None, bill_list=BILL_LIST, unreadable=(), part_history=()
):
    """A scraper on the fake site: every page is a real fixture unless `overrides` says otherwise (url -> (status,
    body)); journal PDFs read as `texts` (url -> text). Bills in `unreadable` fail as the site fails them; bills in
    `part_history` are saved, but a page of their history failed (as action_pages records it)."""
    pages = {
        SITE
        + "/Journal/House/194/11-01-2026": (200, fixture("journal_House_11-2026.html")),
        SITE
        + "/Journal/Senate/194/11-01-2026": (
            200,
            fixture("journal_Senate_11-2026.html"),
        ),
        SITE + "/Laws/SessionLaws/Acts/2026": (200, fixture("sessionlaws_2026.html")),
        SITE + "/api/Hearings": (200, fixture("hearings.json")),
        SITE + "/api/Hearings/5818": (200, fixture("hearing_5818.json")),
        SITE + "/api/Hearings/5817": (200, fixture("hearing_5817.json")),
    }
    pages.update(overrides or {})
    s = MABillScraper(Massachusetts(), "/tmp/")
    s.bill_list = []
    s.requested = []

    def get(url, **kwargs):
        s.requested.append(url)
        if url in pages:
            return Response(*pages[url])
        if "/Journal/" in url:
            return Response(200, EMPTY_MONTH)  # a month with no sitting listed (yet)
        return Response(404, "not found")

    s.get = get
    s.scrape_bill_list = lambda session, start=None: s.bill_list.extend(
        dict(r) for r in bill_list
    )
    s.scrape_amendment_papers = mock.Mock()
    real = {
        "house": house_text() if shutil.which("pdftotext") else "",
        "senate": fixture("sj11122026_1100AM.txt"),
    }
    if texts is None:
        texts = {url: real[which] for url, which in JOURNALS.items()}
    s.journal_text = lambda url: s.requested.append(url) or texts.get(url, "")

    def scrape_bill(session, meta, chamber):
        number = meta["BillNumber"] or meta["DocketNumber"]
        if number in unreadable:
            return
        if number in part_history:
            s.failed_histories.add(s.bill_url(session, meta))
        yield Bill(number, legislative_session=session, chamber=chamber, title="An Act")

    s.scrape_bill = scrape_bill
    return s


def run(s, **kwargs):
    return [
        o.identifier for o in s.scrape(session=SESSION, **kwargs) if o._type == "bill"
    ]


def saved():
    with open(catchup.state_path(SESSION)) as f:
        return json.load(f)


@needs_pdftotext
def test_a_catch_up_run_reads_only_the_bills_the_sources_name(cache):
    write_state()
    s = make()
    assert run(s, start=START) == CAUGHT_UP
    # hearing 5818 and 5817 are new since the last run: both details are read, nothing else of the 12
    assert [u for u in s.requested if "/api/Hearings/" in u] == [
        SITE + "/api/Hearings/5817",
        SITE + "/api/Hearings/5818",
    ]
    s.scrape_amendment_papers.assert_called_once()


def test_a_bill_no_source_names_is_not_read(cache):
    # the selection is the sources' answer, not everything: when the House journal names another bill, H 5525 goes
    write_state()
    s = make(
        texts={
            u: (
                "On House, No. 77777."
                if w == "house"
                else fixture("sj11122026_1100AM.txt")
            )
            for u, w in JOURNALS.items()
        }
    )
    assert run(s, start=START) == [b for b in CAUGHT_UP if b != "H5525"]


@needs_pdftotext
def test_the_record_is_carried_to_the_next_run(cache):
    walked = TODAY - datetime.timedelta(days=7)
    write_state(full_walk_on=walked)
    run(make(unreadable=("H5435",)), start=START)
    state = saved()
    assert set(state["bills"]) == LAST_LIST | {"H 5720"}
    assert set(state["hearings"]) == {h["EventId"] for h in HEARINGS}
    assert (
        state["full_walk_on"] == walked.isoformat()
    )  # a catch-up run is not a full walk
    assert state["retry"] == ["H 5435"]  # S 900 was read this time; H 5435 was not


def test_a_quiet_run_is_an_empty_scrape_and_reads_no_bill_page(cache):
    write_state(retry=(), hearings={h["EventId"] for h in HEARINGS})
    s = make(
        texts={u: "On House, No. 77777." for u in JOURNALS},
        bill_list=[r for r in BILL_LIST if r["BillNumber"] not in ("H5720", "H5435")],
    )
    with pytest.raises(EmptyScrape):
        run(s, start=START)
    s.scrape_amendment_papers.assert_not_called()
    assert saved()["retry"] == []


# --- every way a run falls back to reading every bill ---

ALL = [r["BillNumber"] or r["DocketNumber"] for r in BILL_LIST]
ALL_IN_ORDER = [b for b in ALL if b.startswith("H")] + [
    b for b in ALL if b.startswith("S")
]

FALLBACKS = {
    "a journal month page fails": dict(overrides={SITE + "/Journal/Senate/194/11-01-2026": (500, "error")}),
    "the journals name no bill": dict(texts={u: "Met at eleven o'clock." for u in JOURNALS}),
    "no journal in the window": dict(texts={}, overrides={
        SITE + "/Journal/House/194/11-01-2026": (200, EMPTY_MONTH),
        SITE + "/Journal/Senate/194/11-01-2026": (200, EMPTY_MONTH),
    }),
    "the House journals name no bill": dict(texts={u: ("" if "/House/" in u else fixture("sj11122026_1100AM.txt")) for u in JOURNALS}),
    "no House journal in the window": dict(overrides={SITE + "/Journal/House/194/11-01-2026": (200, EMPTY_MONTH)}),
    "no Senate journal in the window": dict(overrides={SITE + "/Journal/Senate/194/11-01-2026": (200, EMPTY_MONTH)}),
    # an error status is a failed source whatever the body says
    "a journal month page answers 503 with a usable body": dict(
        overrides={SITE + "/Journal/House/194/11-01-2026": (503, fixture("journal_House_11-2026.html"))}
    ),
    "the Session Laws page fails": dict(overrides={SITE + "/Laws/SessionLaws/Acts/2026": (503, "busy")}),
    "the Session Laws page lists no chapter": dict(overrides={SITE + "/Laws/SessionLaws/Acts/2026": (200, "<html></html>")}),
    "the hearing list fails": dict(overrides={SITE + "/api/Hearings": (500, "error")}),
    "the hearing list is empty": dict(overrides={SITE + "/api/Hearings": (200, "[]")}),
    "a new hearing's page fails": dict(overrides={SITE + "/api/Hearings/5818": (404, "gone")}),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(FALLBACKS))
def test_a_source_that_fails_or_answers_empty_means_a_full_walk(cache, case):
    write_state()
    assert run(make(**FALLBACKS[case]), start=START) == ALL_IN_ORDER
    assert saved()["full_walk_on"] == TODAY.isoformat()


def test_a_failed_hearing_list_keeps_the_last_one_for_the_next_run(cache):
    write_state()
    run(make(**FALLBACKS["the hearing list fails"]), start=START)
    assert set(saved()["hearings"]) == LAST_HEARINGS


def test_a_journal_that_is_not_a_pdf_is_a_failed_source(cache, tmp_path):
    # the House journal comes back as an error page with status 200; the Senate's is read. Going on with the Senate's
    # bills alone would be a partial run.
    write_state()
    s = make()
    senate = s.journal_text
    page = tmp_path / "page.html"

    def urlretrieve(url):
        page.write_text("<html>Service Unavailable</html>")
        return str(page), Response(200, "")

    s.urlretrieve = urlretrieve
    s.journal_text = (
        lambda url: senate(url)
        if "/Senate/" in url
        else MABillScraper.journal_text(s, url)
    )
    assert run(s, start=START) == ALL_IN_ORDER
    assert not page.exists()


@needs_pdftotext
def test_a_journal_pdf_with_an_error_status_is_a_failed_source(cache, tmp_path):
    write_state()
    s = make()
    senate = s.journal_text
    pdf = tmp_path / "hj.pdf"

    def urlretrieve(url):
        pdf.write_bytes(fixture("hj11122026.pdf", "rb"))
        return str(pdf), Response(404, "")

    s.urlretrieve = urlretrieve
    s.journal_text = (
        lambda url: senate(url)
        if "/Senate/" in url
        else MABillScraper.journal_text(s, url)
    )
    assert run(s, start=START) == ALL_IN_ORDER


@needs_pdftotext
def test_a_journal_pdf_is_read(cache, tmp_path):
    s = make()
    pdf = tmp_path / "hj.pdf"

    def urlretrieve(url):
        pdf.write_bytes(fixture("hj11122026.pdf", "rb"))
        return str(pdf), Response(200, "")

    s.urlretrieve = urlretrieve
    assert catchup.journal_bills(MABillScraper.journal_text(s, "x")) == HOUSE_1112
    assert not pdf.exists()


RECORDS = {
    "no record (the first run with start=)": None,
    "an unreadable record": "{not json",
    "a full walk is due": dict(full_walk_on=TODAY - catchup.FULL_WALK_EVERY),
    "the last record has no hearing list": dict(hearings=None),
}


@pytest.mark.parametrize("case", sorted(RECORDS))
def test_without_a_usable_record_every_bill_is_read_and_a_record_is_written(
    cache, case
):
    record = RECORDS[case]
    if isinstance(record, dict):
        write_state(**record)
    elif isinstance(record, str):
        os.makedirs(os.path.dirname(catchup.state_path(SESSION)), exist_ok=True)
        with open(catchup.state_path(SESSION), "w") as f:
            f.write(record)
    s = make()
    assert run(s, start=START) == ALL_IN_ORDER
    state = saved()
    assert state["full_walk_on"] == TODAY.isoformat()
    assert set(state["bills"]) == LAST_LIST | {"H 5720"}


def test_a_full_walk_is_not_due_the_day_before(cache):
    write_state(
        full_walk_on=TODAY - catchup.FULL_WALK_EVERY + datetime.timedelta(days=1)
    )
    assert run(make(), start=START) != ALL_IN_ORDER


def test_an_invalid_start_is_a_full_walk(cache):
    write_state()
    assert run(make(), start="not-a-date") == ALL_IN_ORDER


PARTIAL = {
    "chamber=lower": (
        dict(chamber="lower"),
        [b for b in ALL_IN_ORDER if b.startswith("H")],
    ),
    "bill_no=H1": (dict(bill_no="H1"), ["H1"]),
    "scrape_chunk_number=1": (
        dict(scrape_chunk_number="1"),
        ["H5525", "H5435", "SD4349", "S900"],
    ),
}


@pytest.mark.parametrize("case", sorted(PARTIAL))
@pytest.mark.parametrize("start", [None, START])
def test_a_partial_run_is_as_before_and_leaves_the_record(cache, case, start):
    write_state()
    before = saved()
    s = make()
    partial, expected = PARTIAL[case]
    assert run(s, start=start, **partial) == expected
    assert not any("/Journal/" in u or "/api/Hearings" in u for u in s.requested)
    assert saved() == before


def test_a_run_without_start_reads_every_bill_and_writes_no_record(cache):
    s = make()
    assert run(s) == ALL_IN_ORDER
    assert s.requested == []
    assert not os.path.exists(catchup.state_path(SESSION))


# --- OPEN-568: a catch-up run still reads a paper and its real bill together ---


@pytest.mark.parametrize("named", ["S 3178", "H 5576", "S 3208"])
def test_a_catch_up_run_reads_the_whole_paper_group(cache, named):
    """The journals name one member of a paper group (S 3178 is the Senate redraft of H 5576, S 3208 an amendment
    to it): the run reads all three, so the roll call moved from the paper to H 5576 is sent again and the import
    deletes none of H 5576's votes (test_ma_paper_votes.deleted_by_import)."""
    paper_votes = pytest.importorskip("test_ma_paper_votes")
    write_state()
    s = paper_votes.make([paper_votes.SENATE_ROW])
    s.catch_up = lambda session, start, state: ({named}, LAST_HEARINGS)
    bills, votes = paper_votes.run(s, start=START)
    assert sorted(bills) == ["H5576", "S3178", "S3208"]
    assert len(paper_votes.on(votes, "H 5576")) == 1  # the vote moved from S 3178
    assert paper_votes.deleted_by_import(paper_votes.STORED, votes) == set()


def test_a_catch_up_run_naming_no_group_member_reads_none_of_it(cache):
    paper_votes = pytest.importorskip("test_ma_paper_votes")
    write_state()
    s = paper_votes.make([paper_votes.SENATE_ROW])
    s.catch_up = lambda session, start, state: ({"H 1"}, LAST_HEARINGS)
    bills, _ = paper_votes.run(s, start=START)
    assert bills == ["H1"]


def test_an_empty_bill_list_fails_the_run(cache):
    # review 21038: not a quiet week and not "no objects returned" (which the collector takes for a no-op): an error
    write_state()
    s = make(bill_list=[])
    with pytest.raises(ValueError, match="Documents list is empty"):
        run(s, start=START)
    assert not any("/Journal/" in u for u in s.requested)


def test_an_empty_bill_list_without_start_is_as_before(cache):
    assert run(make(bill_list=[])) == []


def test_a_bill_whose_history_only_partly_loaded_is_retried_next_run(cache):
    write_state()
    bills = run(make(part_history=("H5668",)), start=START)
    assert "H5668" in bills  # saved this run, with the history it got
    assert saved()["retry"] == ["H 5668"]


@needs_pdftotext
def test_one_failed_journal_of_a_chamber_whose_other_journals_read_is_a_full_walk(
    cache,
):
    # review 21038: the Senate has four journals since 10-26; the 11-09 one fails, the 11-12 one reads and names bills
    write_state()
    s = make()
    texts = {url: s.journal_text(url) for url in JOURNALS}
    failing = SITE + "/Journal/Senate/194/1166/sj11092026_1100AM.pdf"

    def journal_text(url):
        s.requested.append(url)
        if url == failing:
            raise ValueError("{} is not a PDF".format(url))
        return texts.get(url, "")

    s.journal_text = journal_text
    assert run(s, start=START) == ALL_IN_ORDER
    assert failing in s.requested


@needs_pdftotext
def test_a_journal_from_three_weeks_back_is_read(cache):
    # review 21038: START less 18 days (2026-10-29) is inside JOURNAL_LOOKBACK; a week's lookback would miss H 1
    write_state()
    house_oct = SITE + "/Journal/House/194/hj10292026.pdf"
    texts = {
        u: (house_text() if w == "house" else fixture("sj11122026_1100AM.txt"))
        for u, w in JOURNALS.items()
    }
    texts[house_oct] = "Mr. Smith, for the committee, reported on House, No. 1."
    s = make(
        texts=texts,
        overrides={
            SITE
            + "/Journal/House/194/10-01-2026": (
                200,
                fixture("journal_House_10-2026.html"),
            )
        },
    )
    assert "H1" in run(s, start=START)
    assert house_oct in s.requested
    # and nothing before the window is read
    assert SITE + "/Journal/House/194/hj10222026.pdf" not in s.requested


def test_a_journal_file_that_cannot_be_dated_is_a_failed_source(cache):
    write_state()
    page = fixture("journal_House_11-2026.html").replace(
        "hj11162026.pdf", "hj-special-session.pdf"
    )
    s = make(overrides={SITE + "/Journal/House/194/11-01-2026": (200, page)})
    assert run(s, start=START) == ALL_IN_ORDER
