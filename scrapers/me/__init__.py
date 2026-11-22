from utils import url_xpath
from openstates.scrape import State
from .bills import MEBillScraper
from .events import MEEventScraper


class Maine(State):
    scrapers = {
        "bills": MEBillScraper,
        "events": MEEventScraper,
    }
    # OPEN-747: Maine names each session of a two-year Legislature on its own, and these mirror it:
    # its First and Second Regular Sessions and each special session it held ("132nd Legislature,
    # First Special Session" in the title of the bill's text and status page; "132nd MAINE
    # LEGISLATURE / FIRST SPECIAL SESSION-2025" on the printed bill). Regular and special sessions
    # are separate, each with its own dates (Ramon 2026-11-21: "regular session and special session
    # are two different things. don't ever mix their dates together"). Every start and end is the
    # "Convened" and "Adjourned" day on the session's Legislative Statistics page in the Laws of
    # Maine (lldc.mainelegislature.org/Open/Laws/<year>/..._LegStats_<session>.pdf, read
    # 2026-11-21; the 122nd's Second Regular Session, which has no such page, from the title page
    # of its volume). LawMakerWeb keeps one bill list per Legislature (`extras.legislature`),
    # shared by all its sessions; sessions.py says which session each bill and roll call belongs to.
    legislative_sessions = [
        # 121st Legislature: Open/Laws/2003/
        {
            "_scraped_name": "121st Legislature",
            "classification": "primary",
            "identifier": "121R1",
            "name": "121st Legislature, First Regular Session",
            "start_date": "2002-12-04",
            "end_date": "2003-06-14",
            "extras": {"legislature": 121},
        },
        {
            "classification": "special",
            "identifier": "121S1",
            "name": "121st Legislature, First Special Session",
            "start_date": "2003-08-21",
            "end_date": "2003-08-22",
            "extras": {"legislature": 121},
        },
        {
            "_scraped_name": "121st Legislature",
            "classification": "primary",
            "identifier": "121R2",
            "name": "121st Legislature, Second Regular Session",
            "start_date": "2004-01-07",
            "end_date": "2004-01-30",
            "extras": {"legislature": 121},
        },
        {
            "classification": "special",
            "identifier": "121S2",
            "name": "121st Legislature, Second Special Session",
            "start_date": "2004-02-03",
            "end_date": "2004-04-30",
            "extras": {"legislature": 121},
        },
        # 122nd Legislature: Open/Laws/2005/
        {
            "_scraped_name": "122nd Legislature",
            "classification": "primary",
            "identifier": "122R1",
            "name": "122nd Legislature, First Regular Session",
            "start_date": "2004-12-01",
            "end_date": "2005-03-30",
            "extras": {"legislature": 122},
        },
        {
            "classification": "special",
            "identifier": "122S1",
            "name": "122nd Legislature, First Special Session",
            "start_date": "2005-04-04",
            "end_date": "2005-06-18",
            "extras": {"legislature": 122},
        },
        {
            "classification": "special",
            "identifier": "122S2",
            "name": "122nd Legislature, Second Special Session",
            "start_date": "2005-07-29",
            "end_date": "2005-07-29",
            "extras": {"legislature": 122},
        },
        {
            "_scraped_name": "122nd Legislature",
            "classification": "primary",
            "identifier": "122R2",
            "name": "122nd Legislature, Second Regular Session",
            "start_date": "2006-01-04",
            "end_date": "2006-05-24",
            "extras": {"legislature": 122},
        },
        # 123rd Legislature: Open/Laws/2007/
        {
            "_scraped_name": "123rd Legislature",
            "classification": "primary",
            "identifier": "123R1",
            "name": "123rd Legislature, First Regular Session",
            "start_date": "2006-12-06",
            "end_date": "2007-06-21",
            "extras": {"legislature": 123},
        },
        {
            "_scraped_name": "123rd Legislature",
            "classification": "primary",
            "identifier": "123R2",
            "name": "123rd Legislature, Second Regular Session",
            "start_date": "2008-01-02",
            "end_date": "2008-03-31",
            "extras": {"legislature": 123},
        },
        {
            "classification": "special",
            "identifier": "123S1",
            "name": "123rd Legislature, First Special Session",
            "start_date": "2008-04-01",
            "end_date": "2008-04-18",
            "extras": {"legislature": 123},
        },
        # 124th Legislature: Open/Laws/2009/
        {
            "_scraped_name": "124th Legislature",
            "classification": "primary",
            "identifier": "124R1",
            "name": "124th Legislature, First Regular Session",
            "start_date": "2008-12-03",
            "end_date": "2009-06-13",
            "extras": {"legislature": 124},
        },
        {
            "_scraped_name": "124th Legislature",
            "classification": "primary",
            "identifier": "124R2",
            "name": "124th Legislature, Second Regular Session",
            "start_date": "2010-01-06",
            "end_date": "2010-04-12",
            "extras": {"legislature": 124},
        },
        # 125th Legislature: Open/Laws/2011/
        {
            "_scraped_name": "125th Legislature",
            "classification": "primary",
            "identifier": "125R1",
            "name": "125th Legislature, First Regular Session",
            "start_date": "2010-12-01",
            "end_date": "2011-06-29",
            "extras": {"legislature": 125},
        },
        {
            "classification": "special",
            "identifier": "125S1",
            "name": "125th Legislature, First Special Session",
            "start_date": "2011-09-27",
            "end_date": "2011-09-27",
            "extras": {"legislature": 125},
        },
        {
            "_scraped_name": "125th Legislature",
            "classification": "primary",
            "identifier": "125R2",
            "name": "125th Legislature, Second Regular Session",
            "start_date": "2012-01-04",
            "end_date": "2012-05-31",
            "extras": {"legislature": 125},
        },
        # 126th Legislature: Open/Laws/2013/
        {
            "_scraped_name": "126th Legislature",
            "classification": "primary",
            "identifier": "126R1",
            "name": "126th Legislature, First Regular Session",
            "start_date": "2012-12-05",
            "end_date": "2013-07-10",
            "extras": {"legislature": 126},
        },
        {
            "classification": "special",
            "identifier": "126S1",
            "name": "126th Legislature, First Special Session",
            "start_date": "2013-08-29",
            "end_date": "2013-08-29",
            "extras": {"legislature": 126},
        },
        {
            "_scraped_name": "126th Legislature",
            "classification": "primary",
            "identifier": "126R2",
            "name": "126th Legislature, Second Regular Session",
            "start_date": "2014-01-08",
            "end_date": "2014-05-02",
            "extras": {"legislature": 126},
        },
        # 127th Legislature: Open/Laws/2015/
        {
            "_scraped_name": "127th Legislature",
            "classification": "primary",
            "identifier": "127R1",
            "name": "127th Legislature, First Regular Session",
            "start_date": "2014-12-03",
            "end_date": "2015-07-16",
            "extras": {"legislature": 127},
        },
        {
            "_scraped_name": "127th Legislature",
            "classification": "primary",
            "identifier": "127R2",
            "name": "127th Legislature, Second Regular Session",
            "start_date": "2016-01-06",
            "end_date": "2016-04-29",
            "extras": {"legislature": 127},
        },
        # 128th Legislature: Open/Laws/2017/
        {
            "_scraped_name": "128th Legislature",
            "classification": "primary",
            "identifier": "128R1",
            "name": "128th Legislature, First Regular Session",
            "start_date": "2016-12-07",
            "end_date": "2017-08-02",
            "extras": {"legislature": 128},
        },
        {
            "classification": "special",
            "identifier": "128S1",
            "name": "128th Legislature, First Special Session",
            "start_date": "2017-10-23",
            "end_date": "2017-11-06",
            "extras": {"legislature": 128},
        },
        {
            "_scraped_name": "128th Legislature",
            "classification": "primary",
            "identifier": "128R2",
            "name": "128th Legislature, Second Regular Session",
            "start_date": "2018-01-03",
            "end_date": "2018-05-02",
            "extras": {"legislature": 128},
        },
        {
            "classification": "special",
            "identifier": "128S2",
            "name": "128th Legislature, Second Special Session",
            "start_date": "2018-06-19",
            "end_date": "2018-09-13",
            "extras": {"legislature": 128},
        },
        # 129th Legislature: Open/Laws/2019/
        {
            "_scraped_name": "129th Legislature",
            "classification": "primary",
            "identifier": "129R1",
            "name": "129th Legislature, First Regular Session",
            "start_date": "2018-12-05",
            "end_date": "2019-06-20",
            "extras": {"legislature": 129},
        },
        {
            "classification": "special",
            "identifier": "129S1",
            "name": "129th Legislature, First Special Session",
            "start_date": "2019-08-26",
            "end_date": "2019-08-26",
            "extras": {"legislature": 129},
        },
        {
            "_scraped_name": "129th Legislature",
            "classification": "primary",
            "identifier": "129R2",
            "name": "129th Legislature, Second Regular Session",
            "start_date": "2020-01-08",
            "end_date": "2020-03-17",
            "extras": {"legislature": 129},
        },
        # 130th Legislature: Open/Laws/2021/
        {
            "_scraped_name": "130th Legislature",
            "classification": "primary",
            "identifier": "130R1",
            "name": "130th Legislature, First Regular Session",
            "start_date": "2020-12-02",
            "end_date": "2021-03-30",
            "active": False,
            "extras": {"legislature": 130},
        },
        {
            "classification": "special",
            "identifier": "130S1",
            "name": "130th Legislature, First Special Session",
            "start_date": "2021-04-28",
            "end_date": "2021-07-19",
            "active": False,
            "extras": {"legislature": 130},
        },
        {
            "classification": "special",
            "identifier": "130S2",
            "name": "130th Legislature, Second Special Session",
            "start_date": "2021-09-29",
            "end_date": "2021-09-29",
            "active": False,
            "extras": {"legislature": 130},
        },
        {
            "_scraped_name": "130th Legislature",
            "classification": "primary",
            "identifier": "130R2",
            "name": "130th Legislature, Second Regular Session",
            "start_date": "2022-01-05",
            "end_date": "2022-05-09",
            "active": False,
            "extras": {"legislature": 130},
        },
        # 131st Legislature: Open/Laws/2023/
        {
            "_scraped_name": "131st Legislature",
            "classification": "primary",
            "identifier": "131R1",
            "name": "131st Legislature, First Regular Session",
            "start_date": "2022-12-07",
            "end_date": "2023-03-30",
            "active": False,
            "extras": {"legislature": 131},
        },
        {
            "classification": "special",
            "identifier": "131S1",
            "name": "131st Legislature, First Special Session",
            "start_date": "2023-04-05",
            "end_date": "2023-07-26",
            "active": False,
            "extras": {"legislature": 131},
        },
        {
            "_scraped_name": "131st Legislature",
            "classification": "primary",
            "identifier": "131R2",
            "name": "131st Legislature, Second Regular Session",
            "start_date": "2024-01-03",
            "end_date": "2024-05-10",
            "active": False,
            "extras": {"legislature": 131},
        },
        # 132nd Legislature: Open/Laws/2025/
        {
            "_scraped_name": "132nd Legislature",
            "classification": "primary",
            "identifier": "132R1",
            "name": "132nd Legislature, First Regular Session",
            "start_date": "2024-12-04",
            "end_date": "2025-03-21",
            "active": True,
            "extras": {"legislature": 132},
        },
        {
            "classification": "special",
            "identifier": "132S1",
            "name": "132nd Legislature, First Special Session",
            "start_date": "2025-03-25",
            "end_date": "2025-06-25",
            "active": True,
            "extras": {"legislature": 132},
        },
        {
            "_scraped_name": "132nd Legislature",
            "classification": "primary",
            "identifier": "132R2",
            "name": "132nd Legislature, Second Regular Session",
            "start_date": "2026-01-07",
            "end_date": "2026-04-29",
            "active": True,
            "extras": {"legislature": 132},
        },
    ]
    ignored_scraped_sessions = ["2001-2002"]

    def get_session_list(self):
        sessions = url_xpath(
            "https://www.mainelegislature.org/LawMakerWeb/advancedsearch.asp",
            '//select[@name="LegSession"]/option/text()',
        )
        return sessions
