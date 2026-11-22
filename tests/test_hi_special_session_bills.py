"""OPEN-751: the measures of Hawaii's two-chamber special sessions are read from the legislature's
own PDFs (hi/special_measures.py), and land in their OPEN-748 special session.

A special session numbers its measures from 1 again and the site's measure pages hold only the
regular measures, so SB 1 of the Second Special Session of 2013 (marriage equality) and the regular
SB 1 of 2013 (the Public Land Development Corporation) are two different bills.

The fixtures (tests/fixtures/hi_open751/), all saved 2026-11-21 from data.capitol.hawaii.gov:

* splsession2013b.html: the listing of /sessions/splsession2013b/, the session's document folder;
* senate-journal-2013-2ss.json.gz and house-journal-2013-2ss.json.gz: the text of
  /sessions/journal/Senate/2013/Senate_Journal_2013_2nd_Special_Session.pdf and
  /sessions/journal/House/2013/HJournal_Final_2SS_2013_Days_.pdf, page by page, as
  special_measures.xml_pages() reads pdftohtml's output (each page a list of lines, left column
  first);
* house-journal-2013-2ss-page7.xml: pdftohtml's output for page 7 of the House journal, which
  holds the list of H.B. Nos. 6 to 12 in its right column;
* SB1-2013.html: the regular SB 1 of 2013's measure page
  (session/archives/measure_indiv_Archives.aspx?billtype=SB&billnumber=1&year=2013), scripts,
  styles and hidden form fields removed.

The roll calls expected below are typed from the journals' own pages, not from the scraper:
Senate journal p. 19 (Third Reading, October 30, 2013): "Ayes, 20. Noes, 4 (Gabbard, Kim, Kouchi,
Slom). Excused, 1 (Wakai)."; p. 56 (Final Reading, November 12): "Ayes, 19. Noes, 4 (Gabbard, Kim,
Kouchi, Slom). Excused, 2 (Dela Cruz, Taniguchi)."; House journal p. 89 (Second Reading, November
6): "Ayes, 30: ... Noes, 18: ... Excused, 3: Cabanilla, Cachola and Choy."; p. 186 (Third
Reading, November 8): "Ayes, 30: ... Noes, 19: ... Excused, 2: Cabanilla and Choy."
"""
import gzip
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import hi  # noqa: E402
from hi import special_measures as sm  # noqa: E402
from hi.bills import HIBillScraper  # noqa: E402
from openstates.exceptions import EmptyScrape  # noqa: E402
from openstates.scrape import Bill, VoteEvent  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hi_open751")
SESSION = "2013 Second Special Session"
FOLDER = sm.DATA + sm.SOURCES[SESSION]["folder"]
JOURNALS = {
    side: [sm.DATA + p for p in sm.SOURCES[SESSION][side]]
    for side in ("upper", "lower")
}

HOUSE_AYES = (
    "Belatti, Brower, Coffman, Evans, Hanohano, Hashem, Ichiyama, Ing, Kawakami, Kobayashi, "
    "Lee, Lowen, Luke, McKelvey, Mizuno, Morikawa, Nakashima, Nishimoto, Ohno, Onishi, Rhoads, "
    "Saiki, Say, Souki, Takai, Takayama, Takumi, Thielen, Wooley, Yamashita"
).split(", ")
HOUSE_NOES_THIRD = (
    "Aquino, Awana, Cachola, Carroll, Cullen, Fale, Fukumoto, Har, Ito, Johanson, Jordan, "
    "Matsumoto, McDermott, Oshiro, Tokioka, Tsuji, Ward, Woodson, Yamane"
).split(", ")
JOURNAL_DAYS_2013 = [
    "2013-10-28", "2013-10-29", "2013-10-30", "2013-10-31", "2013-11-01", "2013-11-04",
    "2013-11-05", "2013-11-06", "2013-11-07", "2013-11-08", "2013-11-12",
]  # fmt: skip


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def journal(name):
    with gzip.open(os.path.join(FIX, name), "rt", encoding="utf-8") as f:
        return sm.journal_days(json.load(f))


MEASURES = sm.folder_measures(read("splsession2013b.html"))
DAYS = {
    "upper": journal("senate-journal-2013-2ss.json.gz"),
    "lower": journal("house-journal-2013-2ss.json.gz"),
}
EVENTS = {side: sm.measure_events(DAYS[side], side, set(MEASURES)) for side in DAYS}


def scraper():
    s = object.__new__(HIBillScraper)
    s.jurisdiction = hi.Hawaii()
    s.short_ids = {}
    s.members = None
    s.logger = logging.getLogger("test")
    s.warnings = []
    s.info = s.error = s.logger.info
    s.warning = s.warnings.append
    return s


def special(key, events=EVENTS, s=None):
    s = s or scraper()
    out = list(s.special_bill(SESSION, key, MEASURES[key], events, FOLDER, JOURNALS))
    bills = [o for o in out if isinstance(o, Bill)]
    votes = [o for o in out if isinstance(o, VoteEvent)]
    return bills, votes


def chamber(vote):
    return get_pseudo_id(vote.organization)["classification"]


def tally(vote):
    counts = {c["option"]: c["value"] for c in vote.counts}
    names = {}
    for v in vote.votes:
        names.setdefault(v["option"], []).append(v["voter_name"])
    return counts, names


def test_the_folder_lists_the_sessions_bills_and_resolutions():
    assert sorted(MEASURES, key=lambda k: (k[0], int(k[1]))) == (
        [("HB", str(n)) for n in range(1, 13)]
        + [("HR", str(n)) for n in range(1, 11)]
        + [("SB", "1")]
        + [("SR", str(n)) for n in range(1, 4)]
    )  # the GMs and the JC are nominations, not measures the scraper files
    sb1 = MEASURES[("SB", "1")]
    assert [name for name, _ in sb1["versions"]] == ["SB1", "HD1"]
    assert sb1["versions"][1][1] == FOLDER + "SB1_HD1_.PDF"
    documents = [name for name, _ in sb1["documents"]]
    assert documents[:2] == ["Floor Amendment 4", "Floor Amendment 5"]
    assert documents[-2:] == [
        "House Standing Committee Report 4",
        "Senate Standing Committee Report 1",
    ]
    # "HR5_%20.PDF": the space in the site's file name does not lose the resolution
    assert MEASURES[("HR", "5")]["introduced"].endswith("HR5_%20.PDF")


def test_a_two_column_page_is_read_one_column_at_a_time():
    with open(os.path.join(FIX, "house-journal-2013-2ss-page7.xml"), "rb") as f:
        (page,) = sm.xml_pages(f.read())
    # the list of bills in the right column reads number, title, introducer, in that order
    at = page.index("H. B. Nos.")
    assert page[at + 1 : at + 3] == [
        '6 "A BILL FOR AN ACT RELATING TO CIVIL LIBERTIES."',
        "Introduced by: Representative Jordan.",
    ]
    # and the left column's sentences are not cut by it
    left = " ".join(page[: page.index("H. B. Nos.")])
    assert (
        "presented a report (Stand. Com. Rep. No. 1) recommending that H.B. No. 1"
        in left
    )


def test_each_sitting_day_is_dated_from_its_heading():
    for side in ("upper", "lower"):
        assert [str(d) for d, _ in DAYS[side]] == JOURNAL_DAYS_2013


def test_sb1_lands_in_its_special_session_with_its_passage_roll_calls():
    (bill,), votes = special(("SB", "1"))
    assert bill.legislative_session == SESSION
    assert bill.identifier == "SB1"
    assert bill.title == "RELATING TO EQUAL RIGHTS."
    assert [s["name"] for s in bill.sponsorships] == ["Galuteria"]
    assert [v["note"] for v in bill.versions] == ["SB1", "SB1_HD1"]
    actions = [(a["date"], a["description"]) for a in bill.actions]
    for expected in [
        ("2013-10-28", "Introduced and Passed First Reading"),
        ("2013-10-28", "Referred to Committee on Judiciary and Labor"),
        ("2013-10-29", "Passed Second Reading"),
        ("2013-10-30", "Passed Third Reading"),
        ("2013-10-30", "Received from Senate"),
        ("2013-10-30", "Passed First Reading"),
        ("2013-11-06", "Passed Second Reading"),
        ("2013-11-08", "Passed Third Reading"),
        ("2013-11-12", "Agreed to House amendments"),
        ("2013-11-12", "Passed Final Reading"),
    ]:
        assert expected in actions
    # the House's message returning SB 1 to the Senate reports the House's action, which the
    # House journal records: it is not a second "Received" in the Senate
    assert not [d for d, desc in actions if desc == "Received from House"]
    # every action is dated within the special session (2013-10-28 to 11-12)
    assert all("2013-10-28" <= d <= "2013-11-12" for d, _ in actions)

    got = {(chamber(v), v.start_date): v for v in votes}
    assert set(got) == {
        ("upper", "2013-10-30"),
        ("upper", "2013-11-12"),
        ("lower", "2013-11-06"),
        ("lower", "2013-11-08"),
    }
    for v in votes:
        assert v.legislative_session == SESSION
        assert get_pseudo_id(v.bill) == {
            "identifier": "SB1",
            "legislative_session__identifier": SESSION,
            "from_organization__classification": "upper",
        }
        assert v.result == "pass"

    senate_third = got[("upper", "2013-10-30")]
    assert senate_third.motion_text == "Passed Third Reading"
    assert senate_third.motion_classification == ["passage"]
    counts, names = tally(senate_third)
    assert counts == {"yes": 20, "no": 4, "not voting": 1}
    assert names == {
        "no": ["Gabbard", "Kim", "Kouchi", "Slom"],
        "not voting": ["Wakai"],
    }

    counts, names = tally(got[("upper", "2013-11-12")])
    assert got[("upper", "2013-11-12")].motion_classification == ["passage"]
    assert counts == {"yes": 19, "no": 4, "not voting": 2}
    assert names["not voting"] == ["Dela Cruz", "Taniguchi"]

    house_second = got[("lower", "2013-11-06")]
    assert house_second.motion_text == "Passed Second Reading"
    assert house_second.motion_classification == []  # not passage
    counts, names = tally(house_second)
    assert counts == {"yes": 30, "no": 18, "not voting": 3}
    assert names["not voting"] == ["Cabanilla", "Cachola", "Choy"]

    house_third = got[("lower", "2013-11-08")]
    assert house_third.motion_classification == ["passage"]
    counts, names = tally(house_third)
    assert counts == {"yes": 30, "no": 19, "not voting": 2}
    assert names == {
        "yes": HOUSE_AYES,
        "no": HOUSE_NOES_THIRD,
        "not voting": ["Cabanilla", "Choy"],
    }


def test_the_regular_sb1_of_2013_does_not():
    page = read("SB1-2013.html")
    s = scraper()
    s.get = lambda url, **kw: type("Response", (), {"text": page})
    url = (
        "https://www.capitol.hawaii.gov/session/archives/measure_indiv_Archives.aspx?"
        "billtype=SB&billnumber=1&year=2013"
    )
    out = list(s.scrape_bill("2013 Regular Session", "upper", "bill", url))
    (regular,) = [o for o in out if isinstance(o, Bill)]
    assert regular.legislative_session == "2013 Regular Session"
    assert regular.title == "RELATING TO THE PUBLIC LAND DEVELOPMENT CORPORATION."
    # nothing on its page falls in the special session, so none of it moves there
    for v in out:
        if isinstance(v, VoteEvent):
            assert v.legislative_session == "2013 Regular Session"
    assert not any("2013-10-28" <= a["date"] <= "2013-11-12" for a in regular.actions)
    # and the special session's SB 1 carries none of the regular bill's history
    (sb1,), _ = special(("SB", "1"))
    regular_actions = {(a["date"], a["description"]) for a in regular.actions}
    assert not regular_actions & {(a["date"], a["description"]) for a in sb1.actions}
    assert sb1.title != regular.title


def test_a_house_bill_and_resolutions():
    (hb3,), votes = special(("HB", "3"))
    assert (
        hb3.title == "MAKING AN APPROPRIATION TO THE HAWAII HEALTH SYSTEMS CORPORATION."
    )
    assert [s["name"] for s in hb3.sponsorships] == [
        "Souki"
    ]  # "Representative Souki, by request"
    assert [v["note"] for v in hb3.versions] == ["HB3", "HB3_HD1"]
    # "passed Third Reading by a vote of 47 ayes, with Representatives Awana, Choy, Ito and Yamane
    # being excused." (House, October 31); the Senate's roll call of November 5 prints
    # "Ayes, 20; Ayes with Reservations (Thielen). Noes, 1 (Slom). Excused, 4 (...)"
    by_chamber = {tally(v)[0]["yes"]: tally(v) for v in votes}
    assert by_chamber[47] == (
        {"yes": 47, "no": 0, "not voting": 4},
        {"not voting": ["Awana", "Choy", "Ito", "Yamane"]},
    )
    assert by_chamber[20] == (
        {"yes": 20, "no": 1, "not voting": 4},
        {
            "no": ["Slom"],
            "not voting": ["Gabbard", "Ruderman", "Shimabukuro", "Solomon"],
            "yes": ["Thielen"],
        },
    )
    # H.R. No. 5 "was not adopted"; H.R. No. 2 "was laid on the table"
    (hr5,), _ = special(("HR", "5"))
    assert [a["description"] for a in hr5.actions] == ["Offered", "Failed adoption"]
    assert hr5.actions[1]["classification"] == ["failure"]
    (hr2,), _ = special(("HR", "2"))
    assert [a["description"] for a in hr2.actions] == ["Offered", "Laid on the table"]
    assert [s["name"] for s in hr2.sponsorships] == ["McDermott"]


def test_a_roll_call_whose_names_do_not_match_its_counts_is_left_out():
    # the journal's tally, with one count changed
    assert (
        sm._tally(
            "upper",
            "Ayes, 20. Noes, 3 (Gabbard, Kim, Kouchi, Slom). Excused, 1 (Wakai).",
        )
        is None
    )
    assert sm._tally(
        "upper", "Ayes, 20. Noes, 4 (Gabbard, Kim, Kouchi, Slom). Excused, 1 (Wakai)."
    )
    house = "Ayes, 30: {}. Noes, 19: {}. Excused, 2: Cabanilla and Choy.".format(
        ", ".join(HOUSE_AYES[:-1]) + " and " + HOUSE_AYES[-1],
        ", ".join(HOUSE_NOES_THIRD[:-1]) + " and " + HOUSE_NOES_THIRD[-1],
    )
    assert sm._tally("lower", house)["yes"] == 30
    assert sm._tally("lower", house.replace("Ayes, 30", "Ayes, 31")) is None
    # through the scraper: the roll call is dropped with a warning, the bill and its other roll
    # calls stay
    days = [
        (d, t.replace("Ayes, 20. Noes, 4 (Gabbard", "Ayes, 20. Noes, 5 (Gabbard"))
        for d, t in DAYS["upper"]
    ]
    changed = {
        "upper": sm.measure_events(days, "upper", set(MEASURES)),
        "lower": EVENTS["lower"],
    }
    s = scraper()
    (bill,), votes = special(("SB", "1"), changed, s)
    assert len(votes) == 3
    assert any("does not read cleanly" in w for w in s.warnings)
    assert "2013-10-30" not in {v.start_date for v in votes if chamber(v) == "upper"}


def test_a_measure_that_cannot_be_titled_stops_the_scrape():
    # the ticket: "If a whole bill cannot be read reliably, stop and ask"
    events = {side: dict(EVENTS[side]) for side in EVENTS}
    sb1 = dict(events["upper"][("SB", "1")])
    sb1["titles"] = sb1["titles"] + [("upper", "RELATING TO SOMETHING ELSE.")]
    events["upper"][("SB", "1")] = sb1
    with pytest.raises(ValueError, match="two titles"):
        special(("SB", "1"), events)
    for side in events:
        untitled = dict(events[side][("SB", "1")])
        untitled["titles"] = []
        events[side][("SB", "1")] = untitled
    with pytest.raises(ValueError, match="no journal gives its title"):
        special(("SB", "1"), events)


def test_a_measure_without_its_introduced_text_stops_the_scrape():
    listing = read("splsession2013b.html")
    assert listing.count('/sessions/splsession2013b/SB1_.pdf"') == 1
    with pytest.raises(
        ValueError, match="SB1: files in the folder but no introduced text"
    ):
        sm.folder_measures(listing.replace('/sessions/splsession2013b/SB1_.pdf"', '"'))


def test_the_houses_counted_votes():
    # S.B. No. 4 of the Special Session of 2017, House journal, September 1, 2017
    text = (
        " by a vote of 31 ayes to 15 noes, with Representatives Kobayashi, Onishi, Oshiro, San "
        "Buenaventura and Woodson voting aye with reservations, with Representatives Brower, "
        "Cachola, Creagan, DeCoite, Evans, Kong, Lowen, McKelvey, Quinlan, Say, Thielen, Todd, "
        "Tokioka, Tupola and Ward voting no, and with Representatives Choy, Har, Hashem, "
        "Matsumoto and Nishimoto being excused. At 1:52 o'clock p.m., ..."
    )
    vote = sm._house_count(text)
    assert (vote["yes"], vote["no"], vote["excused"]) == (31, 15, 5)
    voters = dict(vote["voters"][i][::-1] for i in range(len(vote["voters"])))
    assert voters["San Buenaventura"] == "yes"
    assert voters["Ward"] == "no"
    assert voters["Nishimoto"] == "not voting"
    # 15 noes printed, 14 named: not read
    assert (
        sm._house_count(text.replace("Tupola and Ward", "and Tupola")) == "unreadable"
    )


def test_only_the_two_chamber_special_sessions_are_read():
    assert set(sm.SOURCES) == {
        "2013 Second Special Session",
        "2016 Second Special Session",
        "2017 Special Session",
        "2021 Special Session",
    }
    specials = {
        s["identifier"]
        for s in hi.Hawaii.legislative_sessions
        if s["classification"] == "special"
    }
    assert set(sm.SOURCES) <= specials
    s = scraper()
    s.get = lambda url, **kw: pytest.fail(f"unexpected request {url}")
    with pytest.raises(EmptyScrape):
        list(
            s.scrape(session="2019 Special Session")
        )  # the Senate alone, confirmations


def test_a_special_session_scrape_reads_its_folder_and_journals(monkeypatch):
    # the PDFs are stood in for by their saved text (pdftohtml is not run here)
    pages = {}
    for side, name in (("upper", "senate"), ("lower", "house")):
        with gzip.open(
            os.path.join(FIX, f"{name}-journal-2013-2ss.json.gz"), "rt"
        ) as f:
            pages[JOURNALS[side][0]] = json.load(f)
    monkeypatch.setattr(sm, "pdf_bytes_xml", lambda content: content)
    monkeypatch.setattr(sm, "xml_pages", lambda url: pages[url])
    s = scraper()
    requested = []

    def get(url, **kw):
        assert kw == {}  # TLS verification stays on
        requested.append(url)
        text = read("splsession2013b.html") if url == FOLDER else ""
        return type("Response", (), {"text": text, "content": url})

    s.get = get
    out = list(s.scrape(session=SESSION))
    assert requested == [FOLDER, JOURNALS["upper"][0], JOURNALS["lower"][0]]
    assert all(
        u.startswith("https://data.capitol.hawaii.gov/sessions/") for u in requested
    )
    bills = [o for o in out if isinstance(o, Bill)]
    assert len(bills) == 26
    assert all(b.legislative_session == SESSION for b in bills)
    for o in out:
        o.validate()
    # a journal that does not read as this session's sitting days stops the scrape
    other = {
        JOURNALS["upper"][0]: pages[JOURNALS["upper"][0]][:2]
    }  # the cover pages only
    monkeypatch.setattr(sm, "xml_pages", lambda url: other.get(url, pages[url]))
    with pytest.raises(ValueError, match="not within 2013 Second Special Session"):
        list(s.scrape(session=SESSION))
    monkeypatch.setattr(sm, "xml_pages", lambda url: pages[url])
    # a chamber's scrape takes only its own measures
    upper = [
        o for o in s.scrape(session=SESSION, chamber="upper") if isinstance(o, Bill)
    ]
    assert sorted(b.identifier for b in upper) == ["SB1", "SR1", "SR2", "SR3"]
