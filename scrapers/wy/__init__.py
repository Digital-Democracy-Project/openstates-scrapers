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
    # 2004, before this list). Start dates are the first numbered legislative day on
    # wyoleg.gov/Session/<year>/Archive ("Prior Session Calendars"; the same days are in
    # lsoservice.wyoleg.gov/api/Session, specialSessionValue 1 for the special sessions). A
    # session marked "special" here reads only that year's special-session bills (bills.py).
    # OPEN-756 (Ramon 2026-11-22: the end is the official close, including one set by motion or
    # resolution after the last sitting): every session, the 2020 and 2021 special sessions
    # included, closed on its last day with identical motions in both houses ("CLOSING OF
    # SESSION") that "if no such time is established before December 31, <year>, ... [the
    # session] is adjourned sine die effective at 12:00 o'clock noon on that date"; none was
    # recalled (2026's close holds unless it is recalled before then). So each ends on December
    # 31 of its year. Sources: the House and Senate Journals,
    # wyoleg.gov/<year>/HouseDigest.pdf and SenateDigest.pdf to 2022 (the 2020 and 2021 special
    # sessions are in the next year's file), wyoleg.gov/<year>/HouseJournal.pdf and
    # SenateJournal.pdf from 2023.
    legislative_sessions = [
        {
            "_scraped_name": "2011",
            "classification": "primary",
            "identifier": "2011",
            "name": "2011 General Session",
            "start_date": "2011-01-11",
            "end_date": "2011-12-31",
        },
        {
            "_scraped_name": "2012",
            "classification": "primary",
            "identifier": "2012",
            "name": "2012 Budget Session",
            "start_date": "2012-02-13",
            "end_date": "2012-12-31",
        },
        {
            "_scraped_name": "2013",
            "classification": "primary",
            "identifier": "2013",
            "name": "2013 General Session",
            "start_date": "2013-01-08",
            "end_date": "2013-12-31",
        },
        {
            "_scraped_name": "2014",
            "classification": "primary",
            "identifier": "2014",
            "name": "2014 Budget Session",
            "start_date": "2014-02-10",
            "end_date": "2014-12-31",
        },
        {
            "_scraped_name": "2015",
            "classification": "primary",
            "identifier": "2015",
            "name": "2015 General Session",
            "start_date": "2015-01-13",
            "end_date": "2015-12-31",
        },
        {
            "_scraped_name": "2016",
            "classification": "primary",
            "identifier": "2016",
            "name": "2016 Budget Session",
            "start_date": "2016-02-08",
            "end_date": "2016-12-31",
        },
        {
            "_scraped_name": "2017",
            "classification": "primary",
            "identifier": "2017",
            "name": "2017 General Session",
            "start_date": "2017-01-10",
            "end_date": "2017-12-31",
        },
        {
            "_scraped_name": "2018",
            "classification": "primary",
            "identifier": "2018",
            "name": "2018 Budget Session",
            "start_date": "2018-02-12",
            "end_date": "2018-12-31",
        },
        {
            "_scraped_name": "2019",
            "classification": "primary",
            "identifier": "2019",
            "name": "2019 General Session",
            "start_date": "2019-01-08",
            "end_date": "2019-12-31",
        },
        {
            "_scraped_name": "2020",
            "classification": "primary",
            "identifier": "2020",
            "name": "2020 Budget Session",
            "start_date": "2020-02-10",
            "end_date": "2020-12-31",
        },
        {
            "_scraped_name": "2020S1",
            "classification": "special",
            "identifier": "2020S1",
            "name": "2020 Special Session",
            "start_date": "2020-05-15",
            "end_date": "2020-12-31",
        },
        {
            "_scraped_name": "2021",
            "classification": "primary",
            "identifier": "2021",
            "name": "2021 General Session",
            "start_date": "2021-01-12",
            "end_date": "2021-12-31",
        },
        {
            "_scraped_name": "2021S1",
            "classification": "special",
            "identifier": "2021S1",
            "name": "2021 Special Session",
            "start_date": "2021-10-26",
            "end_date": "2021-12-31",
            "active": False,
        },
        {
            "_scraped_name": "2022",
            "classification": "primary",
            "identifier": "2022",
            "name": "2022 Budget Session",
            "start_date": "2022-02-14",
            "end_date": "2022-12-31",
            "active": False,
        },
        {
            "_scraped_name": "2023",
            "classification": "primary",
            "identifier": "2023",
            "name": "2023 General Session",
            "start_date": "2023-01-10",
            "end_date": "2023-12-31",
            "active": False,
        },
        {
            "_scraped_name": "2024",
            "classification": "primary",
            "identifier": "2024",
            "name": "2024 Budget Session",
            "start_date": "2024-02-12",
            "end_date": "2024-12-31",
            "active": False,
        },
        {
            "_scraped_name": "2025",
            "classification": "primary",
            "identifier": "2025",
            "name": "2025 General Session",
            "start_date": "2025-01-14",
            "end_date": "2025-12-31",
            "active": False,
        },
        {
            "_scraped_name": "2026",
            "classification": "primary",
            "identifier": "2026",
            "name": "2026 Budget Session",
            "start_date": "2026-02-09",
            "end_date": "2026-12-31",
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
