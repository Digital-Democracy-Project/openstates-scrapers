"""Tests for OPEN-718: Maryland's veto overrides and Senate consent calendars.

1. Every veto-override roll call was skipped ("vetoed" in its header). The skip was added in 2021
   (37c0b904a) for 2021RS votes on 2020 bills, which would have landed on 2021's bill of the same
   number. An override is now recorded on the bill of the session it was vetoed in, by that
   session's run: a regular session's run also reads the year's special sessions for their
   overrides (2025S1 holds 38, 2026S1 holds 4), and the special session's own run leaves them out.
2. A Senate third-reading consent calendar lists several bills; the roll call was recorded on one.
   It is now one vote per bill, with the same tallies and members, each with its own key.

The fixtures are real roll-call PDFs (mgaleg.maryland.gov/<session>/votes/<chamber>/<seq>.pdf,
read 2026-11-20) as pdftotext -layout gives them, which is what convert_pdf(type="text") returns.
The bills and tallies below were read off the PDFs by hand.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import md.votes  # noqa: E402
from md.votes import MDVoteScraper, final_vote_only, vote_classification  # noqa: E402
from openstates.scrape import VoteEvent  # noqa: E402

FIXTURES = [
    os.path.join(os.path.dirname(__file__), "fixtures", name)
    for name in ("md_open718", "md_open700")
]


def _fixture_text(url):
    # ".../2025S1/votes/house/0024.pdf" -> "2025s1_house_0024.txt"
    session, _, chamber, seq = url.lower().rsplit("/", 4)[-4:]
    name = f"{session}_{chamber}_{seq.replace('.pdf', '.txt')}"
    for directory in FIXTURES:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    raise FileNotFoundError(name)


@pytest.fixture(autouse=True)
def offline_pdfs(monkeypatch):
    def convert_pdf(filename, type="xml"):
        assert type == "text"
        return _fixture_text(filename)

    monkeypatch.setattr(md.votes, "convert_pdf", convert_pdf)


def url(session, chamber, seq):
    return f"https://mgaleg.maryland.gov/{session}/votes/{chamber}/{seq}.pdf"


class _Votes(MDVoteScraper):
    """The real scraper over saved PDFs; `site` maps a session code to its roll-call URLs."""

    def __init__(self, site=None):
        self.warnings = []
        self.site = site or {}
        self.codes_requested = []

    def urlretrieve(self, url):
        return url, None

    def warning(self, msg, *args):
        self.warnings.append(msg)

    def vote_urls(self, chamber, session_code):
        self.codes_requested.append(session_code)
        return self.site.get(session_code, [])


def _counts(v):
    return {c["option"]: c["value"] for c in v.counts}


def _session_of_bill(v):
    # the bill pseudo id names the session the importer looks the bill up in
    return "2025" if '"2025"' in v.bill else "2026" if '"2026"' in v.bill else v.bill


# (session, chamber, seq, bill, yes, no): every header shape seen
OVERRIDES = [
    (
        "2025S1",
        "house",
        "0024",
        "HB 270",
        111,
        23,
    ),  # "CALENDAR OF VETOED HOUSE BILLS NO. 2"
    ("2025S1", "house", "0034", "SB 587", 93, 35),  # "2025 VETOED SENATE BILL"
    ("2025S1", "senate", "0005", "SB 121", 42, 1),  # "2025 Vetoed Senate Bill"
    ("2025S1", "senate", "0018", "HB 56", 43, 0),  # "2025 Vetoed House Bills"
    (
        "2026S1",
        "house",
        "1727",
        "HB 862",
        99,
        30,
    ),  # "HB 862  Calendar of Vetoed House Bills"
    ("2026S1", "house", "1754", "SB 426", 134, 0),  # "SB 426  VETOED SENATE BILL"
    ("2026S1", "senate", "1392", "SB 426", 44, 0),  # "2026 Vetoed Senate Bills"
    ("2026S1", "senate", "1393", "HB 862", 33, 11),  # "2026 Vetoed House Bills"
]


@pytest.mark.parametrize("session,chamber,seq,bill,yes,no", OVERRIDES)
def test_override_is_recorded_on_the_vetoed_sessions_bill(
    session, chamber, seq, bill, yes, no
):
    year = session[:4]
    votes = _Votes().scrape_vote(url(session, chamber, seq), year, overrides_only=True)
    assert len(votes) == 1
    v = votes[0]
    assert v.bill_identifier == bill
    assert v.legislative_session == year
    assert _session_of_bill(v) == year
    assert (_counts(v)["yes"], _counts(v)["no"]) == (yes, no)
    assert v.result == ("pass" if yes > no else "fail")
    assert v.motion_classification == ["passage"]
    assert v.motion_text.startswith("Shall the Bill pass notwithstanding")
    assert v.organization == (
        '~{"classification": "%s"}' % {"house": "lower", "senate": "upper"}[chamber]
    )
    assert len(v.votes) == sum(_counts(v).values())


@pytest.mark.parametrize("session,chamber,seq,bill,yes,no", OVERRIDES)
def test_special_sessions_own_run_leaves_the_override_to_the_regular_run(
    session, chamber, seq, bill, yes, no
):
    scraper = _Votes()
    assert scraper.scrape_vote(url(session, chamber, seq), session.lower()) == []
    assert bill in scraper.warnings[0]


def test_override_of_a_prior_sessions_bill_is_still_skipped():
    # what the 2021 check was for: 2021RS House 0012 votes on 2020's HB 1488
    # ("SPECIAL ORDER CALENDAR - 2020 VETOED HOUSE BILL"); 2021's HB 1488 is another bill
    scraper = _Votes()
    assert scraper.scrape_vote(url("2021RS", "house", "0012"), "2021") == []
    assert "2020" in scraper.warnings[0]


def test_regular_run_reads_its_special_sessions_for_overrides_only():
    site = {
        "2026rs": [url("2026RS", "house", "0076")],  # HB 3 third reading
        "2026s1": [
            url("2026S1", "house", "1727"),  # override of 2026's HB 862
            url("2026S1", "house", "1748"),  # 2026S1's own HB 2100, an amendment
            url("2026S1", "house", "1742"),  # 2026S1's own HB 2100, a ruling
        ],
    }
    scraper = _Votes(site)
    votes = list(scraper.scrape(chamber="lower", session="2026"))
    assert [(v.bill_identifier, v.motion_classification) for v in votes] == [
        ("HB 3", ["passage"]),
        ("HB 862", ["passage"]),
    ]
    assert all(v.legislative_session == "2026" for v in votes)
    # it stops at the first special session with no session days
    assert scraper.codes_requested == ["2026rs", "2026s1", "2026s2"]


def test_special_session_run_keeps_its_own_bills_and_reads_no_other_session():
    site = {"2026s1": [url("2026S1", "house", n) for n in ("1727", "1748", "1742")]}
    scraper = _Votes(site)
    votes = list(scraper.scrape(chamber="lower", session="2026s1"))
    assert [(v.bill_identifier, v.motion_classification) for v in votes] == [
        ("HB 2100", ["amendment"]),
        ("HB 2100", []),
    ]
    assert scraper.codes_requested == ["2026s1"]


def _roll_call(key, motion, bill="HB 862", chamber="lower"):
    v = VoteEvent(
        motion_text=motion,
        start_date="2026-04-01",
        classification=vote_classification(motion),
        result="pass",
        legislative_session="2026",
        bill=bill,
        chamber=chamber,
    )
    v.dedupe_key = key
    return v


def test_override_pairs_after_the_regular_sessions_roll_calls():
    # a special session numbers its roll calls from 1 again: 2025S1 #24 comes after 2025RS #1500,
    # so a reconsidered third reading in the regular session does not unlabel the override
    override = _roll_call(
        url("2025S1", "house", "0024"),
        "Shall the Bill pass notwithstanding the objections of the Chief Executive?",
    )
    recon = _roll_call(
        url("2025RS", "house", "1500"), "On Third Reading (Reconsidered) (Amend)"
    )
    final_vote_only([override, recon])
    assert override.motion_classification == ["passage"]
    assert recon.motion_classification == ["passage"]


# (seq, bills in the order listed, yes, no, not voting, absent)
CONSENT = [
    (
        "0838",  # two lines of bills
        "HB 135 HB 211 HB 228 HB 300 HB 320 HB 399 HB 569 HB 595 HB 606 HB 610 HB 678 HB 735 "
        "HB 742 HB 744 HB 783 HB 789 HB 846 HB 889 HB 929 HB 1102 HB 1138 HB 1194",
        43,
        0,
        2,
        2,
    ),
    ("1361", "HB 503 HB 591 HB 668", 43, 0, 4, 0),
]


@pytest.mark.parametrize("seq,bills,yes,no,nv,absent", CONSENT)
def test_consent_calendar_is_a_vote_on_each_bill(seq, bills, yes, no, nv, absent):
    source = url("2026RS", "senate", seq)
    votes = _Votes().scrape_vote(source, "2026")
    assert [v.bill_identifier for v in votes] == [
        f"HB {n}" for n in bills.replace("HB ", "").split()
    ]
    first = votes[0]
    for v in votes:
        assert _counts(v) == {
            "yes": yes,
            "no": no,
            "not voting": nv,
            "excused": 0,
            "absent": absent,
        }
        assert v.votes == first.votes
        assert len(v.votes) == yes + no + nv + absent
        assert v.motion_classification == ["passage"]
        assert v.motion_text == first.motion_text
        assert v.dedupe_key == f"{source}#{v.bill_identifier}"
        assert v.sources == [{"url": source, "note": ""}]
    assert len({v.dedupe_key for v in votes}) == len(votes)


def test_consent_calendar_votes_survive_the_chamber_pairing():
    site = {
        "2026rs": [url("2026RS", "senate", "0838"), url("2026RS", "senate", "1361")],
        "2026s1": [url("2026S1", "senate", "1392")],
    }
    votes = list(_Votes(site).scrape(chamber="upper", session="2026"))
    assert len(votes) == 22 + 3 + 1
    assert all(v.motion_classification == ["passage"] for v in votes)
    assert len({v.dedupe_key for v in votes}) == len(votes)
