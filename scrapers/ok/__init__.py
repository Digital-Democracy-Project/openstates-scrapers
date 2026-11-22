from openstates.scrape import State
from .bills import OKBillScraper
from .events import OKEventScraper


class Oklahoma(State):
    scrapers = {
        "events": OKEventScraper,
        "bills": OKBillScraper,
    }
    # OPEN-758: one regular session per year, as the journals ("First Regular Session of the
    # Sixtieth Legislature" in 2025, "Second Regular Session" in 2026) and the search form ("2025
    # Regular Session", "2026 Regular Session") name them, and each special session on its own.
    # Bills are numbered once per Legislature and carry over into its second year, whose list on
    # the form holds both years; sessions.py says which session each bill and roll call is filed
    # under (the Iowa rule, Ramon 2026-11-21: bills by filing year). Once a Legislature's second
    # year is in this list (with its code in OKBillScraper.meta_session_id), the first year's
    # scrape reads the second year's list.
    # Dates (OPEN-755, read 2026-11-22) are from the House and Senate journals (House:
    # former.okhouse.gov/Publications/HouseJournals.aspx, Senate: oksenate.gov/calendar/journals).
    # A session starts on its first legislative day (an odd year's January Organizational Day) and
    # ends on its official close as the journals record it (Ramon, 2026-11-22): the sine die day,
    # including one set by concurrent resolution after the last sitting. A special session that
    # simply expired with its Legislature ends on the day the first chamber formally closed it, or
    # the last day either chamber met if neither did. Each year's dates (OPEN-758, the same
    # journals) are cited on its entry. Special sessions keep their own dates, even where they
    # ran alongside a regular session. 2027 is from okhouse.gov/leg_deadlines. 2012SS1 is
    # unchecked: neither chamber lists a journal for it.
    legislative_sessions = [
        {
            # sine die under SCR 20 (5:00 p.m., May 27, 2011): HJ 2011 Day 60, SJ 2011-05-20
            "_scraped_name": "2011 Regular Session",
            "classification": "primary",
            "identifier": "2011",
            "name": "2011 Regular Session",
            "start_date": "2011-01-04",
            "end_date": "2011-05-27",
            "active": False,
        },
        {
            # HJ 2012 Day 1; sine die SJ 2012-05-25 (4:27 p.m.), HJ Day 65
            "_scraped_name": "2012 Regular Session",
            "classification": "primary",
            "identifier": "2012",
            "name": "2012 Regular Session",
            "start_date": "2012-02-06",
            "end_date": "2012-05-25",
            "active": False,
        },
        {
            "_scraped_name": "2012 Special Session",
            "classification": "special",
            "identifier": "2012SS1",
            "name": "2012 Special Session",
            "start_date": "2012-06-01",
            "end_date": "2012-06-02",
        },
        {
            # sine die under HCR 1022: HJ 2013 Day 65 and SJ 2013-05-24
            "_scraped_name": "2013 Regular Session",
            "classification": "primary",
            "identifier": "2013",
            "name": "2013 Regular Session",
            "start_date": "2013-01-08",
            "end_date": "2013-05-24",
            "active": False,
        },
        {
            # HJ 2014 Day 1; sine die SJ 2014-05-23, HJ Day 64
            "_scraped_name": "2014 Regular Session",
            "classification": "primary",
            "identifier": "2014",
            "name": "2014 Regular Session",
            "start_date": "2014-02-03",
            "end_date": "2014-05-23",
            "active": False,
        },
        {
            "_scraped_name": "2013 Special Session",
            "classification": "special",
            "identifier": "2013SS1",
            "name": "2013 Special Session",
            "start_date": "2013-09-03",
            "end_date": "2013-09-09",
        },
        {
            # sine die SJ 2015-05-22 (3:04 p.m.), HJ 2015 Day 64
            "_scraped_name": "2015 Regular Session",
            "classification": "primary",
            "identifier": "2015",
            "name": "2015 Regular Session",
            "start_date": "2015-01-06",
            "end_date": "2015-05-22",
            "active": False,
        },
        {
            # HJ 2016 Day 1; sine die SJ 2016-05-27 (12:09 p.m.), HJ Day 68
            "_scraped_name": "2016 Regular Session",
            "classification": "primary",
            "identifier": "2016",
            "name": "2016 Regular Session",
            "start_date": "2016-02-01",
            "end_date": "2016-05-27",
            "active": False,
        },
        {
            "_scraped_name": "2017 First Special Session",
            "classification": "special",
            "identifier": "2017SS1",
            "name": "2017 First Special Session",
            "start_date": "2017-09-25",
            "end_date": "2017-11-17",
        },
        {
            "_scraped_name": "2017 Second Special Session",
            "classification": "special",
            "identifier": "2017SS2",
            "name": "2017 Second Special Session",
            "start_date": "2017-12-18",
            "end_date": "2018-04-19",
        },
        {
            # sine die SJ 2017-05-26 (11:50 a.m.), HJ 2017 Day 66
            "_scraped_name": "2017 Regular Session",
            "classification": "primary",
            "identifier": "2017",
            "name": "2017 Regular Session",
            "start_date": "2017-01-03",
            "end_date": "2017-05-26",
            "active": False,
        },
        {
            # HJ 2018 Day 1; sine die SJ 2018-05-03 (7:22 p.m.), HJ Day 52
            "_scraped_name": "2018 Regular Session",
            "classification": "primary",
            "identifier": "2018",
            "name": "2018 Regular Session",
            "start_date": "2018-02-05",
            "end_date": "2018-05-03",
            "active": False,
        },
        {
            # sine die under SCR 5: SJ 2019-05-23, HJ 2019 Day 64
            "_scraped_name": "2019 Regular Session",
            "classification": "primary",
            "identifier": "2019",
            "name": "2019 Regular Session",
            "start_date": "2019-01-08",
            "end_date": "2019-05-31",
            "active": False,
        },
        {
            "_scraped_name": "2020 First Special Session",
            "classification": "special",
            "identifier": "2020SS1",
            "name": "2020 First Special Session",
            "start_date": "2020-04-06",
            "end_date": "2020-05-30",
        },
        {
            "_scraped_name": "2020 Regular Session",
            "classification": "primary",
            "identifier": "2020",
            "name": "2020 Regular Session",
            "start_date": "2020-02-03",
            "end_date": "2020-05-29",
        },
        {
            "_scraped_name": "2021 Regular Session",
            "classification": "primary",
            "identifier": "2021",
            "name": "2021 Regular Session",
            "start_date": "2021-01-05",
            "end_date": "2021-05-27",
        },
        {
            "_scraped_name": "2022 Regular Session",
            "classification": "primary",
            "identifier": "2022",
            "name": "2022 Regular Session",
            "start_date": "2022-02-07",
            "end_date": "2022-05-27",
            "active": False,
        },
        {
            "_scraped_name": "2021 First Special Session",
            "classification": "special",
            "identifier": "2021SS1",
            "name": "2021 First Special Session",
            "start_date": "2021-11-15",
            "end_date": "2021-11-26",
            "active": False,
        },
        {
            "_scraped_name": "2022 Second Special Session",
            "classification": "special",
            "identifier": "2022SS2",
            "name": "2022 Second Special Session",
            "start_date": "2022-05-18",
            "end_date": "2022-10-14",
            "active": False,
        },
        {
            "_scraped_name": "2022 Third Special Session",
            "classification": "special",
            "identifier": "2022SS3",
            "name": "2022 Third Special Session",
            "start_date": "2022-06-13",
            "end_date": "2022-06-15",
            "active": False,
        },
        {
            "_scraped_name": "2023 Regular Session",
            "classification": "primary",
            "identifier": "2023",
            "name": "2023 Regular Session",
            "start_date": "2023-01-03",
            "end_date": "2023-05-26",
            "active": False,
        },
        {
            "_scraped_name": "2023 First Special Session",
            "classification": "special",
            "identifier": "2023S1",
            "name": "2023 First Special Session",
            "start_date": "2023-05-17",
            "end_date": "2023-07-31",
            "active": False,
        },
        {
            "_scraped_name": "2023 Second Special Session",
            "classification": "special",
            "identifier": "2023S2",
            "name": "2023 Second Special Session",
            "start_date": "2023-10-03",
            "end_date": "2023-10-03",
            "active": False,
        },
        {
            "_scraped_name": "2024 Regular Session",
            "classification": "primary",
            "identifier": "2024",
            "name": "2024 Regular Session",
            "start_date": "2024-02-05",
            "end_date": "2024-05-30",
            "active": False,
        },
        {
            "_scraped_name": "2024 Third Special Session",
            "classification": "special",
            "identifier": "2024S3",
            "name": "2024 Third Special Session",
            "start_date": "2024-01-29",
            "end_date": "2024-05-20",
            "active": False,
        },
        {
            "_scraped_name": "2024 Fourth Special Session",
            "classification": "special",
            "identifier": "2024S4",
            "name": "2024 Fourth Special Session",
            "start_date": "2024-06-12",
            "end_date": "2024-07-15",
            "active": False,
        },
        {
            "_scraped_name": "2025 Regular Session",
            "classification": "primary",
            "identifier": "2025",
            "name": "2025 Regular Session",
            "start_date": "2025-01-07",
            "end_date": "2025-05-30",
            "active": True,
        },
        {
            "_scraped_name": "2026 Regular Session",
            "classification": "primary",
            "identifier": "2026",
            "name": "2026 Regular Session",
            "start_date": "2026-02-02",
            "end_date": "2026-05-14",
            "active": True,
        },
        {
            "_scraped_name": "2027 Regular Session",
            "classification": "primary",
            "identifier": "2027",
            "name": "2027 Regular Session",
            "start_date": "2027-01-05",
            "end_date": "2027-05-28",
            "active": False,
        },
    ]
    ignored_scraped_sessions = [
        "2021 Regular Session - Web",
        "2020 Second Special Session",
        "2020 Regular Session (web)",
        "2010 Regular Session",
        "2009 Regular Session",
        "2008 Regular Session",
        "2007 Regular Session",
        "2006 Second Special Session",
        "2006 Regular Session",
        "2005 Special Session",
        "2005 Regular Session",
        "2004 Special Session",
        "2004 Regular Session",
        "2003 Regular Session",
        "2002 Regular Session",
        "2001 Special Session",
        "2001 Regular Session",
        "2000 Regular Session",
        "1999 Special Session",
        "1999 Regular Session",
        "1998 Regular Session",
        "1997 Regular Session",
        "1996 Regular Session",
        "1995 Regular Session (web)",
        "1995 Regular Session",
        "1994 Second Special Session",
        "1994 First Special Session",
        "1994 Regular Session",
        "1993 Regular Session",
    ]

    def get_session_list(self):
        from utils import url_xpath

        sessions = url_xpath(
            "https://webapps.oklegislature.gov/WebApplication3/WebForm1.aspx",
            "//select[@name='cbxSessionId']/option/text()",
            verify=False,
        )
        # OK Sometimes appends (Mainsys) to their session listings
        sessions = [
            s.replace("(Mainsys)", "").replace("(PROD)", "").strip() for s in sessions
        ]
        return sessions
