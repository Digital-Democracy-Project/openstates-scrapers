import lxml.html
import requests
from openstates.scrape import State
from .events import HIEventScraper
from .bills import HIBillScraper

settings = dict(SCRAPELIB_TIMEOUT=300)


class Hawaii(State):
    scrapers = {
        "bills": HIBillScraper,
        "events": HIEventScraper,
    }
    # OPEN-748: each session as the legislature's journals name it, with the dates they give
    # (data.capitol.hawaii.gov/sessions/journal/<Senate|House>/<year>/): a regular session a year
    # (2011 and 2012 too, as the site's archive lists them; they were one entry before) and every
    # special session since 2011, 27 in all, each convened and adjourned on its own days (Ramon
    # 2026-11-21: "regular session and special session are two different things. don't ever mix
    # their dates together"). Both chambers sat in four (2013 Second, 2016 Second, 2017, 2021);
    # the rest were the Senate alone, confirming appointments. Special sessions have no site year:
    # the site's lists and measure pages hold only regular measures (sessions.py, OPEN-751).
    legislative_sessions = [
        {
            # "Regular Session of 2011, Convened Wednesday, January 19, 2011, Adjourned Thursday,
            # May 5, 2011" (journals/Senate/2011/Senate_Journal_2011_Regular_Session.pdf)
            "_scraped_name": "2011",
            "classification": "primary",
            "identifier": "2011 Regular Session",
            "name": "2011 Regular Session",
            "start_date": "2011-01-19",
            "end_date": "2011-05-05",
        },
        {
            # "Special Session of 2011": convened 2011-08-31, adjourned 2011-09-01 (Senate journal)
            # journals/Senate/2011/Senate_Journal_2011_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2011 Special Session",
            "name": "2011 Special Session",
            "start_date": "2011-08-31",
            "end_date": "2011-09-01",
            "active": False,
        },
        {
            # "Regular Session of 2012, Convened Wednesday, January 18, 2012, Adjourned Thursday,
            # May 3, 2012" (journals/Senate/2012/Senate_Journal_2012_Regular_Session.pdf)
            "_scraped_name": "2012",
            "classification": "primary",
            "identifier": "2012 Regular Session",
            "name": "2012 Regular Session",
            "start_date": "2012-01-18",
            "end_date": "2012-05-03",
        },
        {
            # "Special Session of 2012": convened 2012-06-28, adjourned 2012-06-29 (Senate journal)
            # journals/Senate/2012/Senate_Journal_2012_Special Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2012 Special Session",
            "name": "2012 Special Session",
            "start_date": "2012-06-28",
            "end_date": "2012-06-29",
            "active": False,
        },
        {
            "_scraped_name": "2013",
            "classification": "primary",
            "identifier": "2013 Regular Session",
            "name": "2013 Regular Session",
            "start_date": "2013-01-16",
            # OPEN-793: both journals' 60th day, Thursday, May 2, 2013: adjourned sine die
            "end_date": "2013-05-02",
        },
        {
            # "Special Session of 2013": convened 2013-08-05, adjourned 2013-08-06 (Senate journal)
            # journals/Senate/2013/Senate_Journal_2013_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2013 Special Session",
            "name": "2013 Special Session",
            "start_date": "2013-08-05",
            "end_date": "2013-08-06",
            "active": False,
        },
        {
            # "Second Special Session of 2013": convened 2013-10-28, adjourned 2013-11-12 (Senate journal)
            # journals/Senate/2013/Senate_Journal_2013_2nd_Special_Session.pdf
            # both chambers; House journal: HJournal_Final_2SS_10-28-13 to 11-12-13
            "classification": "special",
            "identifier": "2013 Second Special Session",
            "name": "2013 Second Special Session",
            "start_date": "2013-10-28",
            "end_date": "2013-11-12",
            "active": False,
        },
        {
            "_scraped_name": "2014",
            "classification": "primary",
            "identifier": "2014 Regular Session",
            "name": "2014 Regular Session",
            "start_date": "2014-01-15",
            # OPEN-793: both journals' 60th day, Thursday, May 1, 2014: adjourned sine die
            "end_date": "2014-05-01",
        },
        {
            # "Special Session of 2014": convened 2014-10-22, adjourned 2014-10-23 (Senate journal)
            # journals/Senate/2014/Senate_Journal_2014_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2014 Special Session",
            "name": "2014 Special Session",
            "start_date": "2014-10-22",
            "end_date": "2014-10-23",
            "active": False,
        },
        {
            "_scraped_name": "2015",
            "classification": "primary",
            "identifier": "2015 Regular Session",
            "name": "2015 Regular Session",
            "start_date": "2015-01-21",
            "end_date": "2015-05-07",
        },
        {
            # "Special Session of 2015": convened 2015-11-05, adjourned 2015-11-06 (Senate journal)
            # journals/Senate/2015/Senate_Journal_2015_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2015 Special Session",
            "name": "2015 Special Session",
            "start_date": "2015-11-05",
            "end_date": "2015-11-06",
            "active": False,
        },
        {
            "_scraped_name": "2016",
            "classification": "primary",
            "identifier": "2016 Regular Session",
            "name": "2016 Regular Session",
            "start_date": "2016-01-20",
            "end_date": "2016-05-05",
        },
        {
            # "Special Session of 2016": convened 2016-06-23, adjourned 2016-06-24 (Senate journal)
            # journals/Senate/2016/Senate_Journal_2016_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2016 Special Session",
            "name": "2016 Special Session",
            "start_date": "2016-06-23",
            "end_date": "2016-06-24",
            "active": False,
        },
        {
            # "Second Special Session of 2016": convened 2016-07-12, adjourned 2016-07-20 (Senate journal)
            # journals/Senate/2016/Senate_Journal_2016_2nd_Special_Session.pdf
            # both chambers; House journal: "SECOND SPECIAL SESSION OF 2016" (July 12 to 20, 2016)
            "classification": "special",
            "identifier": "2016 Second Special Session",
            "name": "2016 Second Special Session",
            "start_date": "2016-07-12",
            "end_date": "2016-07-20",
            "active": False,
        },
        {
            # "Third Special Session of 2016": convened 2016-09-13, adjourned 2016-09-14 (Senate journal)
            # journals/Senate/2016/Senate_Journal_2016_3rd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2016 Third Special Session",
            "name": "2016 Third Special Session",
            "start_date": "2016-09-13",
            "end_date": "2016-09-14",
            "active": False,
        },
        {
            "_scraped_name": "2017",
            "classification": "primary",
            "identifier": "2017 Regular Session",
            "name": "2017 Regular Session",
            "start_date": "2017-01-18",
            "end_date": "2017-05-04",
        },
        {
            # "Special Session of 2017": convened 2017-08-28, adjourned 2017-09-01 (Senate journal)
            # journals/Senate/2017/Senate_Journal_2017_1st_Special_Session.pdf
            # both chambers; House journal: "2017 HJournal Final 4 Special Session" (08-28 to 09-01)
            "classification": "special",
            "identifier": "2017 Special Session",
            "name": "2017 Special Session",
            "start_date": "2017-08-28",
            "end_date": "2017-09-01",
            "active": False,
        },
        {
            # "Second Special Session of 2017": convened 2017-09-25, adjourned 2017-09-26 (Senate journal)
            # journals/Senate/2017/Senate_Journal_2017_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2017 Second Special Session",
            "name": "2017 Second Special Session",
            "start_date": "2017-09-25",
            "end_date": "2017-09-26",
            "active": False,
        },
        {
            # "Third Special Session of 2017": convened 2017-11-14, adjourned 2017-11-15 (Senate journal)
            # journals/Senate/2017/Senate_Journal_2017_3rd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2017 Third Special Session",
            "name": "2017 Third Special Session",
            "start_date": "2017-11-14",
            "end_date": "2017-11-15",
            "active": False,
        },
        {
            "_scraped_name": "2018",
            "classification": "primary",
            "identifier": "2018 Regular Session",
            "name": "2018 Regular Session",
            # OPEN-793: both journals' first day, Wednesday, January 17, 2018
            "start_date": "2018-01-17",
            "end_date": "2018-05-03",
        },
        {
            # "Special Session of 2018": convened 2018-07-09, adjourned 2018-07-10 (Senate journal)
            # journals/Senate/2018/Senate_Journal_2018_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2018 Special Session",
            "name": "2018 Special Session",
            "start_date": "2018-07-09",
            "end_date": "2018-07-10",
            "active": False,
        },
        {
            # "Second Special Session of 2018": convened 2018-10-24, adjourned 2018-10-25 (Senate journal)
            # journals/Senate/2018/Senate_Journal_2018_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2018 Second Special Session",
            "name": "2018 Second Special Session",
            "start_date": "2018-10-24",
            "end_date": "2018-10-25",
            "active": False,
        },
        {
            "_scraped_name": "2019",
            "classification": "primary",
            "identifier": "2019 Regular Session",
            "name": "2019 Regular Session",
            "start_date": "2019-01-16",
            "end_date": "2019-05-02",
        },
        {
            # "Special Session of 2019": convened 2019-09-16, adjourned 2019-09-17 (Senate journal)
            # journals/Senate/2019/Senate_Journal_2019_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2019 Special Session",
            "name": "2019 Special Session",
            "start_date": "2019-09-16",
            "end_date": "2019-09-17",
            "active": False,
        },
        {
            # "Second Special Session of 2019": convened 2019-11-12, adjourned 2019-11-13 (Senate journal)
            # journals/Senate/2019/Senate_Journal_2019_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2019 Second Special Session",
            "name": "2019 Second Special Session",
            "start_date": "2019-11-12",
            "end_date": "2019-11-13",
            "active": False,
        },
        {
            "_scraped_name": "2020",
            "classification": "primary",
            "identifier": "2020 Regular Session",
            "name": "2020 Regular Session",
            "start_date": "2020-01-15",
            "end_date": "2020-07-10",
        },
        {
            # "Special Session of 2020": convened 2020-10-05, adjourned 2020-10-06 (Senate journal)
            # journals/Senate/2020/Senate_Journal_2020_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2020 Special Session",
            "name": "2020 Special Session",
            "start_date": "2020-10-05",
            "end_date": "2020-10-06",
            "active": False,
        },
        {
            # "Second Special Session of 2020": convened 2020-11-18, adjourned 2020-11-19 (Senate journal)
            # journals/Senate/2020/Senate_Journal_2020_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2020 Second Special Session",
            "name": "2020 Second Special Session",
            "start_date": "2020-11-18",
            "end_date": "2020-11-19",
            "active": False,
        },
        {
            "_scraped_name": "2021",
            "classification": "primary",
            "identifier": "2021 Regular Session",
            "name": "2021 Regular Session",
            "start_date": "2021-01-20",
            "end_date": "2021-04-29",
            "active": False,
        },
        {
            # "Special Session of 2021": convened 2021-07-06, adjourned 2021-07-08 (Senate journal)
            # journals/Senate/2021/Senate_Journal_2021_1st_Special_Session.pdf
            # both chambers; House journal: HJournal Final SS 07-06-21 Day 01, 07-08-21 Day 02
            "classification": "special",
            "identifier": "2021 Special Session",
            "name": "2021 Special Session",
            "start_date": "2021-07-06",
            "end_date": "2021-07-08",
            "active": False,
        },
        {
            # "Second Special Session of 2021": convened 2021-07-28, adjourned 2021-08-27 (Senate journal)
            # journals/Senate/2021/Senate_Journal_2021_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2021 Second Special Session",
            "name": "2021 Second Special Session",
            "start_date": "2021-07-28",
            "end_date": "2021-08-27",
            "active": False,
        },
        {
            # "Third Special Session of 2021": convened 2021-10-28, adjourned 2021-10-29 (Senate journal)
            # journals/Senate/2021/Senate_Journal_2021_3rd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2021 Third Special Session",
            "name": "2021 Third Special Session",
            "start_date": "2021-10-28",
            "end_date": "2021-10-29",
            "active": False,
        },
        {
            "_scraped_name": "2022",
            "classification": "primary",
            "identifier": "2022 Regular Session",
            "name": "2022 Regular Session",
            "start_date": "2022-01-19",
            "end_date": "2022-05-05",
            "active": False,
        },
        {
            # "Special Session of 2022": convened 2022-06-20, adjourned 2022-06-21 (Senate journal)
            # journals/Senate/2022/Senate_Journal_2022_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2022 Special Session",
            "name": "2022 Special Session",
            "start_date": "2022-06-20",
            "end_date": "2022-06-21",
            "active": False,
        },
        {
            # "Second Special Session of 2022": convened 2022-08-22, adjourned 2022-08-23 (Senate journal)
            # journals/Senate/2022/Senate_Journal_2022_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2022 Second Special Session",
            "name": "2022 Second Special Session",
            "start_date": "2022-08-22",
            "end_date": "2022-08-23",
            "active": False,
        },
        {
            # "Third Special Session of 2022": convened 2022-10-19, adjourned 2022-10-20 (Senate journal)
            # journals/Senate/2022/Senate_Journal_2022_3rd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2022 Third Special Session",
            "name": "2022 Third Special Session",
            "start_date": "2022-10-19",
            "end_date": "2022-10-20",
            "active": False,
        },
        {
            "_scraped_name": "2023",
            "classification": "primary",
            "identifier": "2023 Regular Session",
            "name": "2023 Regular Session",
            "start_date": "2023-01-18",
            "end_date": "2023-05-04",
            "active": False,
        },
        {
            # "Special Session of 2023": convened 2023-08-21, adjourned 2023-08-22 (Senate journal)
            # journals/Senate/2023/Senate_Journal_2023_1st_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2023 Special Session",
            "name": "2023 Special Session",
            "start_date": "2023-08-21",
            "end_date": "2023-08-22",
            "active": False,
        },
        {
            # "Second Special Session of 2023": convened 2023-11-20, adjourned 2023-11-21 (Senate journal)
            # journals/Senate/2023/Senate_Journal_2023_2nd_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2023 Second Special Session",
            "name": "2023 Second Special Session",
            "start_date": "2023-11-20",
            "end_date": "2023-11-21",
            "active": False,
        },
        {
            "_scraped_name": "2024",
            "classification": "primary",
            "identifier": "2024",
            "name": "2024 Regular Session",
            "start_date": "2024-01-17",
            # OPEN-793: both journals' 60th day, Friday, May 3, 2024: adjourned sine die
            "end_date": "2024-05-03",
            "active": False,
        },
        {
            # "Special Session of 2024": convened 2024-06-26, adjourned 2024-06-27 (Senate journal)
            # journals/Senate/2024/Senate_Journal_2024_Special_Session.pdf
            # the Senate alone (confirmations)
            "classification": "special",
            "identifier": "2024 Special Session",
            "name": "2024 Special Session",
            "start_date": "2024-06-26",
            "end_date": "2024-06-27",
            "active": False,
        },
        {
            "_scraped_name": "2025",
            "classification": "primary",
            "identifier": "2025",
            "name": "2025 Regular Session",
            # OPEN-793: both journals' first day, Wednesday, January 15, 2025
            "start_date": "2025-01-15",
            "end_date": "2025-05-02",
            "active": False,
        },
        {
            "_scraped_name": "2026",
            "classification": "primary",
            "identifier": "2026",
            "name": "2026 Regular Session",
            "start_date": "2026-01-21",
            "end_date": "2026-05-08",
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
        "2000",
        "1999",
    ]

    def get_session_list(self):
        response = requests.get(
            "https://data.capitol.hawaii.gov/session/archives/main.aspx", verify=False
        ).content
        page = lxml.html.fromstring(response)
        # page doesn't include current session, we need to add it
        sessions = page.xpath("//*[@name='ctl00$MainContent$yearList']/option/text()")
        sessions.append("2024")
        return sessions
