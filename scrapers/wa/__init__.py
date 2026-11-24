from datetime import date

from openstates.scrape import State
from .events import WAEventScraper
from .bills import WABillScraper

settings = dict(SCRAPELIB_TIMEOUT=300)

# OPEN-819: leg.wa.gov lists the 2027-28 biennium, so it must be in the list below or every run
# fails the session-list check. It becomes the active session on the day the legislature
# convenes, 2027-01-11 ("The 2027 Regular Session convenes on January 11", leg.wa.gov, read
# 2026-11-23); until then 2025-2026 stays the only active one. Read once per run, so the first
# run on or after 2027-01-11 scrapes 2027-2028 (as Arizona's 2027, OPEN-632, and Georgia's
# 2027-28, OPEN-605).
SESSION_2027_28_START = "2027-01-11"
SESSION_2027_28_STARTED = date.today() >= date.fromisoformat(SESSION_2027_28_START)


class Washington(State):
    scrapers = {
        "events": WAEventScraper,
        "bills": WABillScraper,
    }
    legislative_sessions = [
        {
            "_scraped_name": "2009-10",
            "classification": "primary",
            "identifier": "2009-2010",
            "name": "2009-2010 Regular Session",
            "start_date": "2009-01-12",
            "end_date": "2010-03-11",
        },
        {
            "_scraped_name": "2011-12",
            "classification": "primary",
            "identifier": "2011-2012",
            "name": "2011-2012 Regular Session",
            "start_date": "2011-01-10",
            "end_date": "2012-03-08",
        },
        {
            "_scraped_name": "2013-14",
            "classification": "primary",
            "identifier": "2013-2014",
            "name": "2013-2014 Regular Session",
            "start_date": "2013-01-14",
            "end_date": "2014-03-14",
        },
        {
            "_scraped_name": "2015-16",
            "classification": "primary",
            "identifier": "2015-2016",
            "name": "2015-2016 Regular Session",
            "start_date": "2015-01-12",
            "end_date": "2016-03-10",
        },
        {
            "_scraped_name": "2017-18",
            "classification": "primary",
            "identifier": "2017-2018",
            "name": "2017-2018 Regular Session",
            "start_date": "2017-01-09",
            "end_date": "2018-03-08",
        },
        {
            "_scraped_name": "2019-20",
            "classification": "primary",
            "identifier": "2019-2020",
            "name": "2019-2020 Regular Session",
            "start_date": "2019-01-14",
            "end_date": "2020-03-12",
        },
        {
            "_scraped_name": "2021-22",
            "classification": "primary",
            "identifier": "2021-2022",
            "name": "2021-2022 Regular Session",
            "start_date": "2021-01-11",
            "end_date": "2022-03-10",
            "active": False,
        },
        {
            "_scraped_name": "2023-24",
            "classification": "primary",
            "identifier": "2023-2024",
            "name": "2023-2024 Regular Session",
            "start_date": "2023-01-09",
            "end_date": "2024-03-07",
            "active": False,
        },
        {
            "_scraped_name": "2025-26",
            "classification": "primary",
            "identifier": "2025-2026",
            "name": "2025-2026 Regular Session",
            "start_date": "2025-01-13",
            "end_date": "2026-03-06",
            "active": not SESSION_2027_28_STARTED,
        },
        {
            "_scraped_name": "2027-28",
            "classification": "primary",
            "identifier": "2027-2028",
            "name": "2027-2028 Regular Session",
            "start_date": SESSION_2027_28_START,
            # OPEN-819: the 2027 session's sine die, the last day the state constitution allows
            # (leg.wa.gov's draft 2027 cutoff calendar, read 2026-11-23). The biennium's end is
            # the 2028 session's sine die; replace this once leg.wa.gov publishes it.
            "end_date": "2027-04-25",
            "active": SESSION_2027_28_STARTED,
        },
    ]
    ignored_scraped_sessions = [
        "2007-08",
        "2005-06",
        "2003-04",
        "2001-02",
        "1999-00",
        "1997-98",
        "1995-96",
        "1993-94",
        "1991-92",
        "1989-90",
        "1987-88",
        "1985-86",
    ]

    def get_session_list(self):
        from utils.lxmlize import url_xpath

        result = url_xpath(
            "https://leg.wa.gov/",
            '//select[@id="biennium"]/option/text()',
        )
        return result
