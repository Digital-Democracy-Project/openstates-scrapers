import pytest
import scrapelib
from openstates.scrape import Bill
from spatula import URL
from spatula.pages import HandledError

from nv.bills import BillStub, BillTabDetail, ExhibitTabText


# OPEN-935 (upstream openstates-scrapers #5926): one HTTP error on a bill's Overview or
# Exhibits tab must not end the scrape. spatula calls process_error_response from
# _fetch_data, outside the try/except SkipItem in _to_items, so a SkipItem raised there
# stops the run. Logging only lets spatula raise its own HandledError and go on.


class _Failing(URL):
    def get_response(self, scraper):
        raise scrapelib.HTTPError(type("R", (), {"status_code": 404, "url": "x", "text": ""})())


def _bill_stub():
    return BillStub(
        "https://www.leg.state.nv.us/App/NELIS/REL/81st2021/Bill/7262/Overview",
        "AB20",
        "81",
        "81st2021",
        ["test subject"],
    )


def test_overview_http_error_is_handled_not_skipped(caplog):
    page = BillTabDetail(_bill_stub(), source=_Failing("https://example.invalid/o"))
    with caplog.at_level("WARNING"):
        with pytest.raises(HandledError):
            page._fetch_data(None)
    assert "Encountered error fetching Bill Overview for AB20" in caplog.text


def test_exhibits_http_error_is_handled_not_skipped(caplog):
    bill = Bill("AB 20", "81", "t", chamber="lower", classification="bill")
    page = ExhibitTabText(bill, source=_Failing("https://example.invalid/e"))
    with caplog.at_level("WARNING"):
        with pytest.raises(HandledError):
            page._fetch_data(None)
    assert "Encountered error fetching Exhibits tab" in caplog.text
