import re
from urllib.parse import parse_qs, urlparse
import pytz
import dateutil
import lxml
from utils.events import match_coordinates
from collections.abc import Generator
from openstates.scrape import Scraper, Event
from openstates.exceptions import EmptyScrape, ScrapeError
from openstates.utils.cookie_provider import WafBlockDetected
from ._waf_circuit_breaker import MIWafCircuitBreakerMixin
from .bills import mi_waf_get, MIResilientScraperMixin


class MIEventScraper(MIResilientScraperMixin, MIWafCircuitBreakerMixin, Scraper):
    _tz = pytz.timezone("US/Eastern")
    current_page = None
    verify = False

    def scrape(self):
        url = "https://legislature.mi.gov/Committees/Meetings?sortBy=Calendar"
        # Unlike scrape_event_page() below, this fetch happens exactly once per run (not in
        # a per-item loop), so there's nothing to count to MAX_CONSECUTIVE_WAF_BLOCKS against
        # -- a block surviving mi_waf_get's own retry here means the run can't start at all,
        # so abort immediately (OPEN-22 AC7) instead of letting WafBlockDetected propagate
        # uncaught, as it did before this fix.
        try:
            page = mi_waf_get(
                lambda cookies: self.get(url, cookies=cookies, verify=False)
            ).content
        except WafBlockDetected as e:
            raise ScrapeError(
                "MI event scrape aborted: WAF block detected even after cookie re-warm "
                "fetching the committee calendar page -- legislature.mi.gov is likely "
                "blocking this run entirely (OPEN-18)"
            ) from e
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)

        if not page.xpath(
            "//table[contains(@class,'calendar')]//a[contains(@href,'/Committees/Meeting')]/@href"
        ):
            raise EmptyScrape

        for link in page.xpath(
            "//table[contains(@class,'calendar')]//a[contains(@href,'/Committees/Meeting')]/@href"
        ):
            yield from self.scrape_event_page(link)

    def scrape_event_page(self, url) -> Generator[Event]:
        status = "tentative"

        try:
            page = mi_waf_get(
                lambda cookies: self.get(url, cookies=cookies, verify=False)
            ).content
        except WafBlockDetected as e:
            self._register_waf_block_or_abort(
                e,
                item_label=f"event page ({url})",
                scrape_label="MI event scrape",
                fetch_description="fetching event pages",
            )
            return
        self._register_waf_success()

        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)

        self.current_page = page

        title = self.table_cell("Committee(s)")

        chair = self.table_cell("Chair")
        clerk = self.table_cell("Clerk")

        if "sen." in chair.lower():
            chamber = "Senate"
        elif "rep." in chair.lower():
            chamber = "House"
        chair = chair.replace("Rep. ", "").replace("Sen. ", "").strip()

        where = self.table_cell("Location")
        if where == "":
            where = "See Agenda"

        date = self.table_cell("Date")
        time = self.table_cell("Time")

        if "cancelled" in date.lower():
            status = "cancelled"
            date = date.replace("Cancelled", "")

        if "cancelled" in time.lower():
            status = "cancelled"
            time = time.replace("Cancelled", "")

        when = dateutil.parser.parse(f"{date} {time}")
        when = self._tz.localize(when)

        event = Event(
            name=title,
            start_date=when,
            location_name=where,
            status=status,
        )
        event.add_source(url)

        for com in title.split("joint meeting with"):
            event.add_participant(f"{chamber} {com.strip()}", "organization")

        event.add_participant(chair, "person", note="chair")
        event.add_participant(clerk, "person", note="clerk")

        agenda = self.table_cell("Agenda")

        event.add_agenda_item(agenda)

        matches = re.findall(r"([HRSB]{2}\s\d+)", agenda)
        for match in matches:
            event.add_bill(match)

        match_coordinates(
            event,
            {
                "Binsfeld Office Building": ("42.73204", "-84.55507"),
                "House Office Building": ("42.73444", "-84.55348"),
                "Capitol Building": ("42.73360", "-84.5554"),
            },
        )
        meeting_id = "".join(parse_qs(urlparse(url).query)["meetingID"])
        event.dedupe_key = meeting_id
        yield event

    def table_cell(self, header: str):
        xpath = f"//div[@class='formLeft' and contains(text(),'{header}')]/following-sibling::div[@class='formRight']"
        return self.current_page.xpath(f"string({xpath})").strip()
