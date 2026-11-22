"""OPEN-745: every Iowa bill and roll call is filed under its own session: an extraordinary
session or one year's regular session, never under the other.

legis.iowa.gov keeps one bill list and one pair of journal lists per General Assembly, so every
session of it reads the same lists and keeps only its own (scrapers/ia/sessions.py):

* a bill goes to an extraordinary session when its first dated action falls from the day after
  the legislature last sat to the extraordinary session's day: HF 2801 was introduced on
  2026-10-02; HCR 10, the 2023 session's business resolution, was filed on 2023-07-07, four days
  before the session convened (its filing is recorded in the 2023-07-11 House journal, H.J.
  1051). Otherwise it goes to the regular session of the year of its first dated action (Ramon
  2026-11-21: "bills by filing year"): HCR 12, the 2021 adjournment resolution, filed on that
  year's sine die day, stays in 2021, and HF 1003, introduced 2025-04-10 and passed in May 2026,
  stays in 2025 with its 2026 actions. A bill with no dated action follows the companion the site
  lists for it (Ramon 2026-11-21): SCR 8, HCR 10's Senate twin, whose history page says "Data
  not available", goes to 2023s1 with HCR 10;
* a journal, with every roll call in it, goes to the extraordinary session that sat on its date,
  else to the regular session of its year, and each roll call is linked to its bill wherever in
  the General Assembly the bill is filed (HF 1003's 2026 roll call reaches the 2025 bill). Either
  year's scrape brings both years' roll calls, each filed under its own year.

The fixtures (tests/fixtures/ia_open745/) are the site's own pages, saved 2026-11-21:

* history_<ga>_<bill>.html: legislation/billTracking/billHistory?billName=<bill>&ga=<ga>, cut to
  its action table (what the scraper reads); SCR 8's is the whole page without its scripts,
  because it holds HCR 10's history too, below its own empty one;
* journals_house_91_1.html: legislation/journals/house?ga=91&session=1, cut to three journals;
* house_20261002_hf2801.txt: the House journal of 2026-10-02
  (docs/publications/HJNL/20261002_HJNL.pdf, pdftotext -layout), cut to the roll call on HF 2801.

The journal lists are OPEN-744's (tests/fixtures/ia_open744/), and the regular-session roll call
is OPEN-699's (HF 1003 in the House journal of 2026-05-02, HR 3 in that of 2025-02-13).
"""
import os
import re
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ia  # noqa: E402
import ia.votes  # noqa: E402
from ia.bills import IABillScraper  # noqa: E402
from ia.votes import IAVoteScraper  # noqa: E402
from openstates.exceptions import EmptyScrape  # noqa: E402
from openstates.utils import get_pseudo_id  # noqa: E402

TESTS = os.path.dirname(__file__)
FIXTURES = os.path.join(TESTS, "fixtures", "ia_open745")
LISTS = os.path.join(TESTS, "fixtures", "ia_open744")
JOURNALS = {
    "20261002_HJNL.pdf": os.path.join(FIXTURES, "house_20261002_hf2801.txt"),
    "20260502_HJNL.pdf": os.path.join(
        TESTS, "fixtures", "ia_open699", "house_20260502_hf1003_concur.txt"
    ),
    "20250213_HJNL.pdf": os.path.join(
        TESTS, "fixtures", "ia_open699", "house_20250213_hr3.txt"
    ),
}


class _Response:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200


def sessions_of(ga):
    """Every Iowa session filed under General Assembly `ga` on the site."""
    return [
        s["identifier"]
        for s in ia.Iowa.legislative_sessions
        if str(s["extras"]["ordinal"]) == ga
    ]


class OfflineBill(IABillScraper):
    """The real scrape_bill() over a saved billHistory page."""

    def __init__(self, tmp_path):
        super().__init__(ia.Iowa(), str(tmp_path))

    def get(self, url, **kwargs):
        if "billHistory" in url:
            bill = re.search(r"billName=([^&]+)", url).group(1).replace(" ", "")
            ga = re.search(r"ga=(\d+)", url).group(1)
            name = "history_{}_{}.html".format(ga, bill)
            with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
                return _Response(f.read())
        # the BillBook sidebar and its subject list: nothing the session decision reads
        return _Response("<html><body></body></html>")


# General Assembly, bill, its companion on the site's bill list, the session it belongs to, and
# why
BILLS = [
    (
        "91",
        "HF 2801",
        "SF 2508",
        "2026s1",
        "introduced in the 2026 Extraordinary Session",
    ),
    ("91", "HF 2800", "SF 2507", "2026", "introduced in the 2026 regular session"),
    ("91", "HF 1003", None, "2025", "introduced in 2025, carried over, passed in 2026"),
    (
        "90",
        "HF 732",
        "SF 579",
        "2023s1",
        "introduced in the 2023 Extraordinary Session",
    ),
    (
        "90",
        "HCR 10",
        "SCR 8",
        "2023s1",
        "filed 2023-07-07 for the session of 2023-07-11",
    ),
    ("90", "SCR 8", "HCR 10", "2023s1", "no dated action; its companion HCR 10's"),
    ("89", "SF 620", None, "2021s1", "introduced in the 2021 Extraordinary Session"),
    (
        "89",
        "HF 902",
        "SF 622",
        "2021s2",
        "introduced in the 2021 Second Extraordinary Session",
    ),
    ("89", "HCR 12", None, "2021", "filed on the 2021 regular session's sine die day"),
]


@pytest.mark.parametrize(
    "ga,bill_id,companion,owner,why",
    BILLS,
    ids=["{} {}".format(b[0], b[1]) for b in BILLS],
)
def test_a_bill_is_filed_under_its_own_session_only(
    tmp_path, ga, bill_id, companion, owner, why
):
    candidates = sessions_of(ga)
    assert owner in candidates and len(candidates) > 1
    chamber = "lower" if bill_id[0] == "H" else "upper"
    url = "https://www.legis.iowa.gov/legislation/BillBook?ga={}&ba={}".format(
        ga, bill_id.replace(" ", "")
    )
    for session in candidates:
        scraper = OfflineBill(tmp_path)
        bills = list(
            scraper.scrape_bill(
                chamber,
                session,
                ga,
                bill_id,
                url,
                "A bill for an act",
                "SOMEONE",
                companion=companion,
            )
        )
        if session == owner:
            assert [(b.identifier, b.legislative_session) for b in bills] == [
                (bill_id, owner)
            ], why
            # carried-over and later actions stay on the bill
            if bill_id == "HF 1003":
                years = {str(a["date"])[:4] for a in bills[0].actions}
                assert years == {"2025", "2026"}
            elif bill_id != "SCR 8":
                assert bills[0].actions
        else:
            assert bills == [], "{} scraped under {} ({})".format(bill_id, session, why)


def test_a_bill_with_no_dated_action_and_no_companion_is_in_no_session(tmp_path):
    # SCR 8 without the companion the site lists for it: nothing to place it by
    for session in sessions_of("90"):
        scraper = OfflineBill(tmp_path)
        url = "https://www.legis.iowa.gov/legislation/BillBook?ga=90&ba=SCR8"
        assert (
            list(scraper.scrape_bill("upper", session, "90", "SCR 8", url, "x", "y"))
            == []
        )


def test_prefiled_bills_go_to_the_newest_regular_session_only(tmp_path, monkeypatch):
    # bills pre-filed for the next regular session stay out of an extraordinary session's
    # scrape and out of the earlier year's
    read = []

    class Scraper(IABillScraper):
        def scrape_prefiles(self, session):
            read.append(session)
            return iter(())

        def get(self, url, **kwargs):
            return _Response("<html></html>")

    empty = "<table id='sortableTable'><tbody></tbody></table>"
    monkeypatch.setattr(
        requests.Session, "get", lambda self, url, **kw: _Response(empty)
    )
    for session in ("2026s1", "2025", "2026"):
        list(Scraper(ia.Iowa(), str(tmp_path)).scrape(session=session))
    assert read == ["2026"]


class OfflineVotes(IAVoteScraper):
    """The real scrape() over the saved House journal lists of General Assembly 91."""

    def __init__(self, tmp_path, monkeypatch):
        super().__init__(ia.Iowa(), str(tmp_path))

        def convert_pdf(filename, type):
            path = JOURNALS.get(filename.rsplit("/", 1)[1])
            if path is None:
                return b""
            with open(path, "rb") as f:
                return f.read()

        monkeypatch.setattr(ia.votes, "convert_pdf", convert_pdf)

    def get(self, url, params=None, **kwargs):
        name = "journals_{}_{}_{}.html".format(
            url.rsplit("/", 1)[1], params["ga"], params["session"]
        )
        path = os.path.join(LISTS, name)
        if not os.path.exists(path):
            path = os.path.join(FIXTURES, name)
        if not os.path.exists(path):
            return _Response("<html></html>")
        with open(path, encoding="utf-8") as f:
            return _Response(f.read())

    def urlretrieve(self, url, **kwargs):
        return url, None


def roll_calls(tmp_path, monkeypatch, session):
    scraper = OfflineVotes(tmp_path, monkeypatch)
    try:
        votes = list(scraper.scrape(chamber="lower", session=session))
    except EmptyScrape:
        votes = []
    return [
        (
            v.bill.split('"identifier": "')[1].split('"')[0],
            v.legislative_session,
            str(v.start_date)[:10],
            v.sources[0]["url"].rsplit("/", 1)[1],
            get_pseudo_id(v.bill)["legislative_session__identifier__in"],
        )
        for v in votes
    ]


def test_an_extraordinary_roll_call_is_filed_under_its_session(tmp_path, monkeypatch):
    assembly = ["2025", "2026", "2026s1"]
    assert roll_calls(tmp_path, monkeypatch, "2026s1") == [
        ("HF 2801", "2026s1", "2026-10-02", "20261002_HJNL.pdf", assembly)
    ]


def test_a_regular_roll_call_is_filed_under_its_year(tmp_path, monkeypatch):
    votes = roll_calls(tmp_path, monkeypatch, "2026")
    # HF 1003 is filed under 2025 (introduced 2025-04-10); its 2026 roll call is filed under
    # 2026 and looks its bill up in the whole General Assembly, so it reaches the 2025 bill
    assembly = ["2025", "2026", "2026s1"]
    hf1003 = ("HF 1003", "2026", "2026-05-02", "20260502_HJNL.pdf", assembly)
    assert hf1003 in votes
    # a 2025 journal's roll call is brought by the 2026 scrape too, filed under 2025
    hr3 = ("HR 3", "2025", "2025-02-13", "20250213_HJNL.pdf", assembly)
    assert hr3 in votes
    assert {v[1] for v in votes} == {"2025", "2026"}
    # the extraordinary session's roll call is not read again under the regular session
    assert "HF 2801" not in [v[0] for v in votes]
    assert "20261002_HJNL.pdf" not in [v[3] for v in votes]
    # and the 2025 scrape brings the same roll calls, still filed under 2026: core's vote import
    # deletes a bill's stored roll calls that the same import does not bring, so either year
    # scraped alone keeps a carried-over bill's roll calls of both years
    assert roll_calls(tmp_path, monkeypatch, "2025") == votes
