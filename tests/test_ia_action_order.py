"""OPEN-894: Iowa stores each bill's actions oldest first by date.

The billHistory page lists actions in the journal's order, where an "Explanation of vote" dated
days later sits among earlier days' actions (310 of 4,206 Iowa bills step backwards). The bill
keeps the actions oldest first, and a day keeps the journal's order (stable sort), as Maine
(OPEN-839), Hawaii (OPEN-823) and Wyoming (OPEN-780) do.

The fixture is the site's own page for HF 767 of the 91st General Assembly (2025), saved
2026-11-25 as served: the journal lists "Explanation of vote" of April 3 between March 27's
actions.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import ia  # noqa: E402
import lxml.html  # noqa: E402
from ia.bills import IABillScraper  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ia_open894")
PAGE = "history_91_HF767.html"


class _Response:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200


class OfflineBill(IABillScraper):
    def __init__(self, tmp_path):
        super().__init__(ia.Iowa(), str(tmp_path))

    def get(self, url, **kwargs):
        if "billHistory" in url:
            with open(os.path.join(FIXTURES, PAGE), encoding="utf-8") as f:
                return _Response(f.read())
        return _Response("<html><body></body></html>")


def journal_rows():
    """(date, text) of every action row, read from the saved page in its own order."""
    with open(os.path.join(FIXTURES, PAGE), encoding="utf-8") as f:
        page = lxml.html.fromstring(f.read())
    rows = []
    for tr in page.xpath("//table[contains(@class, 'billActionTable')][1]/tbody/tr"):
        date = tr.xpath("string(td[contains(text(), ', 20')])").strip()
        if date:
            text = re.sub(r"\s+", " ", tr.xpath("string(td[3])")).strip()
            # the scraper drops the journal page it ends with ("H.J. 864.")
            text = re.sub(r"(H|S)\.J\.\s+\d+\.$", "", text).strip()
            rows.append((date, text))
    return rows


def scraped_actions(tmp_path):
    url = "https://www.legis.iowa.gov/legislation/BillBook?ga=91&ba=HF767"
    (bill,) = OfflineBill(tmp_path).scrape_bill(
        "lower", "2025", "91", "HF 767", url, "A bill for an act", "SOMEONE"
    )
    return bill.actions


def test_the_saved_journal_does_step_backwards():
    # the fixture is a real backward-dated bill, so the tests below can fail
    from datetime import datetime

    dates = [datetime.strptime(d, "%B %d, %Y") for d, _ in journal_rows()]
    assert dates != sorted(dates)


def test_actions_are_stored_oldest_first(tmp_path):
    dates = [str(a["date"]) for a in scraped_actions(tmp_path)]
    assert dates == sorted(dates)
    assert dates[0] == "2025-03-05" and dates[-1] == "2025-06-06"


def test_no_action_is_added_or_dropped(tmp_path):
    from datetime import datetime

    expected = sorted(
        (str(datetime.strptime(d, "%B %d, %Y").date()), t) for d, t in journal_rows()
    )
    got = sorted((str(a["date"]), a["description"]) for a in scraped_actions(tmp_path))
    assert got == expected


def test_a_day_keeps_the_journals_order(tmp_path):
    stored = [
        a["description"]
        for a in scraped_actions(tmp_path)
        if str(a["date"]) == "2025-03-27"
    ]
    journal = [t for d, t in journal_rows() if d == "March 27, 2025"]
    assert stored == journal and len(stored) == 6
    assert stored[0].startswith("Point of order")
    assert stored[-1].startswith("Immediate message")
