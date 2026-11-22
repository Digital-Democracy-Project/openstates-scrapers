from openstates.scrape import State
from .bills import WYBillScraper
from .events import WYEventScraper


class Wyoming(State):
    scrapers = {
        "bills": WYBillScraper,
        "events": WYEventScraper,
    }
    # OPEN-752 (read 2026-11-22): names, types and dates mirror the legislature's own record.
    # The session menu on wyoleg.gov/Legislation/<year> names a General Session in odd years, a
    # Budget Session in even years (both regular) and a Special Session in 2020 and 2021 (and
    # 2004, before this list). Dates are the first and last numbered legislative day on
    # wyoleg.gov/Session/<year>/Archive ("Prior Session Calendars"; the same days are in
    # lsoservice.wyoleg.gov/api/Session, specialSessionValue 1 for the special sessions). A
    # session marked "special" here reads only that year's special-session bills (bills.py).
    legislative_sessions = [
        {
            "_scraped_name": "2011",
            "classification": "primary",
            "identifier": "2011",
            "name": "2011 General Session",
            "start_date": "2011-01-11",
            "end_date": "2011-03-08",
        },
        {
            "_scraped_name": "2012",
            "classification": "primary",
            "identifier": "2012",
            "name": "2012 Budget Session",
            "start_date": "2012-02-13",
            "end_date": "2012-03-09",
        },
        {
            "_scraped_name": "2013",
            "classification": "primary",
            "identifier": "2013",
            "name": "2013 General Session",
            "start_date": "2013-01-08",
            "end_date": "2013-03-05",
        },
        {
            "_scraped_name": "2014",
            "classification": "primary",
            "identifier": "2014",
            "name": "2014 Budget Session",
            "start_date": "2014-02-10",
            "end_date": "2014-03-07",
        },
        {
            "_scraped_name": "2015",
            "classification": "primary",
            "identifier": "2015",
            "name": "2015 General Session",
            "start_date": "2015-01-13",
            "end_date": "2015-03-11",
        },
        {
            "_scraped_name": "2016",
            "classification": "primary",
            "identifier": "2016",
            "name": "2016 Budget Session",
            "start_date": "2016-02-08",
            "end_date": "2016-03-04",
        },
        {
            "_scraped_name": "2017",
            "classification": "primary",
            "identifier": "2017",
            "name": "2017 General Session",
            "start_date": "2017-01-10",
            "end_date": "2017-03-08",
        },
        {
            "_scraped_name": "2018",
            "classification": "primary",
            "identifier": "2018",
            "name": "2018 Budget Session",
            "start_date": "2018-02-12",
            "end_date": "2018-03-15",
        },
        {
            "_scraped_name": "2019",
            "classification": "primary",
            "identifier": "2019",
            "name": "2019 General Session",
            "start_date": "2019-01-08",
            "end_date": "2019-02-28",
        },
        {
            "_scraped_name": "2020",
            "classification": "primary",
            "identifier": "2020",
            "name": "2020 Budget Session",
            "start_date": "2020-02-10",
            "end_date": "2020-03-12",
        },
        {
            "_scraped_name": "2020S1",
            "classification": "special",
            "identifier": "2020S1",
            "name": "2020 Special Session",
            "start_date": "2020-05-15",
            "end_date": "2020-05-16",
        },
        {
            "_scraped_name": "2021",
            "classification": "primary",
            "identifier": "2021",
            "name": "2021 General Session",
            "start_date": "2021-01-12",
            "end_date": "2021-04-07",
        },
        {
            "_scraped_name": "2021S1",
            "classification": "special",
            "identifier": "2021S1",
            "name": "2021 Special Session",
            "start_date": "2021-10-26",
            "end_date": "2021-11-03",
            "active": False,
        },
        {
            "_scraped_name": "2022",
            "classification": "primary",
            "identifier": "2022",
            "name": "2022 Budget Session",
            "start_date": "2022-02-14",
            "end_date": "2022-03-11",
            "active": False,
        },
        {
            "_scraped_name": "2023",
            "classification": "primary",
            "identifier": "2023",
            "name": "2023 General Session",
            "start_date": "2023-01-10",
            "end_date": "2023-03-03",
            "active": False,
        },
        {
            "_scraped_name": "2024",
            "classification": "primary",
            "identifier": "2024",
            "name": "2024 Budget Session",
            "start_date": "2024-02-12",
            "end_date": "2024-03-08",
            "active": False,
        },
        {
            "_scraped_name": "2025",
            "classification": "primary",
            "identifier": "2025",
            "name": "2025 General Session",
            "start_date": "2025-01-14",
            "end_date": "2025-03-06",
            "active": False,
        },
        {
            "_scraped_name": "2026",
            "classification": "primary",
            "identifier": "2026",
            "name": "2026 Budget Session",
            "start_date": "2026-02-09",
            "end_date": "2026-03-11",
            "active": True,
        },
    ]
    ignored_scraped_sessions = [
        "2010",
        "2009",
        "2008",
        "2007",
        "2006",
        "2005",
        "2004",
        "2003",
        "2002",
        "2001",
    ]

    def get_session_list(self):
        return [str(x) for x in range(2011, 2026)]
