import re
from utils import url_xpath
from openstates.scrape import State
from .bills import IABillScraper
from .votes import IAVoteScraper
from .events import IAEventScraper

settings = {"SCRAPELIB_RPM": 30}


class Iowa(State):
    scrapers = {
        "bills": IABillScraper,
        "votes": IAVoteScraper,
        "events": IAEventScraper,
    }
    legislative_sessions = [
        {
            "_scraped_name": "General Assembly: 84",
            "classification": "primary",
            "identifier": "2011-2012",
            "name": "2011-2012 Regular Session",
            "start_date": "2011-01-10",
            "end_date": "2012-05-09",
        },
        {
            "_scraped_name": "General Assembly: 85",
            "classification": "primary",
            "identifier": "2013-2014",
            "name": "2013-2014 Regular Session",
            "start_date": "2013-01-14",
            "end_date": "2014-05-02",
        },
        {
            "_scraped_name": "General Assembly: 86",
            "classification": "primary",
            "identifier": "2015-2016",
            "name": "2015-2016 Regular Session",
            "start_date": "2015-01-12",
            "end_date": "2016-04-29",
        },
        {
            "_scraped_name": "General Assembly: 87",
            "classification": "primary",
            "identifier": "2017-2018",
            "name": "2017-2018 Regular Session",
            "start_date": "2017-01-09",
            "end_date": "2018-05-05",
        },
        {
            "_scraped_name": "General Assembly: 88",
            "classification": "primary",
            "identifier": "2019-2020",
            "name": "2019-2020 Regular Session",
            "start_date": "2019-01-14",
            "end_date": "2020-06-14",
        },
        {
            "_scraped_name": "General Assembly: 89",
            "classification": "primary",
            "identifier": "2021-2022",
            "name": "2021-2022 Regular Session",
            "start_date": "2021-01-11",
            "end_date": "2022-05-24",
            "active": False,
        },
        {
            "_scraped_name": "General Assembly: 90",
            "classification": "primary",
            "identifier": "2023-2024",
            "name": "2023-2024 Regular Session",
            "start_date": "2023-01-09",
            "end_date": "2024-04-19",
            "active": False,
        },
        {
            "_scraped_name": "General Assembly: 91",
            "classification": "primary",
            "identifier": "2025-2026",
            "name": "2025-2026 Regular Session",
            "start_date": "2025-01-13",
            "end_date": "2026-05-03",
            "active": True,
            "extras": {"ordinal": 91},
        },
        {
            # OPEN-744: meets on the second Monday of January (Iowa Constitution Art. III,
            # Sec. 2), so 2027-01-11, the day after General Assembly 91 ends on the site's
            # list. The end date is the scheduled one, the 100th calendar day of the second
            # session (Iowa Code Sec. 2.10(1)) from 2028-01-10; replace it with the sine die in
            # the journals once the session adjourns. Switched on when its bills appear.
            "_scraped_name": "General Assembly: 92",
            "classification": "primary",
            "identifier": "2027-2028",
            "name": "2027-2028 Regular Session",
            "start_date": "2027-01-11",
            "end_date": "2028-04-18",
            "active": False,
            "extras": {"ordinal": 92},
        },
    ]
    # OPEN-744: Iowa's extraordinary sessions (2021-10-05 and 2021-10-28 in General Assembly 89,
    # 2023-07-11 in 90, 2026-10-02 in 91) are not sessions of their own here. legis.iowa.gov
    # numbers their bills in the General Assembly's sequence (HF 2801 in 91), lists them on the
    # General Assembly's own bill list and files their journals in its journal list, the pages
    # the bills and votes scrapers read; so they are scraped as part of their General Assembly.
    ignored_scraped_sessions = [
        "Legislative Assembly: 86",
        "General Assembly: 83",
        "General Assembly: 82",
        "General Assembly: 81",
        "General Assembly: 80",
        "General Assembly: 79",
        "General Assembly: 79",
        "General Assembly: 78",
        "General Assembly: 78",
        "General Assembly: 77",
        "General Assembly: 77",
        "General Assembly: 76",
    ]

    def get_session_list(self):
        sessions = url_xpath(
            "https://www.legis.iowa.gov/legislation/findLegislation",
            "//section[@class='grid_6']//li/a/text()[normalize-space()]",
        )

        return [
            x[0]
            for x in filter(
                lambda x: x != [],
                [re.findall(r"^.*Assembly: [0-9]+", session) for session in sessions],
            )
        ]
