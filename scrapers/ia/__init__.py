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
    # OPEN-745: Iowa's journals name each year of a General Assembly as its own regular session
    # ("Ninety-first General Assembly of Iowa, 2025 Regular Session", HJNL 20250113; "2026 Regular
    # Session", HJNL 20260112), and Iowa Code Sec. 2.10(1) speaks of its "first regular session"
    # and "second regular session"; so each year is a session of its own (Ramon 2026-11-21: "Two
    # yearly sessions, bills by filing year"). Each starts on the day it convened (its first
    # journal on legis.iowa.gov's journal list) and ends on the day the legislature declared it
    # adjourned sine die (the FINAL ADJOURNMENT paragraph of the daily journals,
    # docs/publications/HJNL|SJNL/<yyyymmdd>_HJNL|SJNL.pdf; where the chambers' days differ, the
    # later one). The extraordinary sessions are sessions of their own too (Ramon 2026-11-21:
    # "regular session and special session are two different things. don't ever mix their
    # dates together"), each convened by the Governor's proclamation and adjourned sine die the
    # same day (the House and Senate journals of that day). The site keeps one bill list and one
    # journal list per General Assembly (`extras.ordinal`, its `ga=`), shared by all of them;
    # sessions.py says which session each bill and journal belongs to.
    legislative_sessions = [
        {
            # sine die: HJNL/SJNL 20110630
            "_scraped_name": "General Assembly: 84",
            "classification": "primary",
            "identifier": "2011",
            "name": "2011 Regular Session",
            "start_date": "2011-01-10",
            "end_date": "2011-06-30",
            "active": False,
            "extras": {"ordinal": 84},
        },
        {
            # sine die: HJNL/SJNL 20120509
            "_scraped_name": "General Assembly: 84",
            "classification": "primary",
            "identifier": "2012",
            "name": "2012 Regular Session",
            "start_date": "2012-01-09",
            "end_date": "2012-05-09",
            "active": False,
            "extras": {"ordinal": 84},
        },
        {
            # sine die: HJNL 20130523, SJNL 20130522 (both: "the day of May 23, 2013")
            "_scraped_name": "General Assembly: 85",
            "classification": "primary",
            "identifier": "2013",
            "name": "2013 Regular Session",
            "start_date": "2013-01-14",
            "end_date": "2013-05-23",
            "active": False,
            "extras": {"ordinal": 85},
        },
        {
            # sine die: SJNL 20140502 (the House adjourned at 5:54 a.m. on May 1, HJNL 20140430)
            "_scraped_name": "General Assembly: 85",
            "classification": "primary",
            "identifier": "2014",
            "name": "2014 Regular Session",
            "start_date": "2014-01-13",
            "end_date": "2014-05-02",
            "active": False,
            "extras": {"ordinal": 85},
        },
        {
            # sine die: HJNL/SJNL 20150605
            "_scraped_name": "General Assembly: 86",
            "classification": "primary",
            "identifier": "2015",
            "name": "2015 Regular Session",
            "start_date": "2015-01-12",
            "end_date": "2015-06-05",
            "active": False,
            "extras": {"ordinal": 86},
        },
        {
            # sine die: HJNL/SJNL 20160429
            "_scraped_name": "General Assembly: 86",
            "classification": "primary",
            "identifier": "2016",
            "name": "2016 Regular Session",
            "start_date": "2016-01-11",
            "end_date": "2016-04-29",
            "active": False,
            "extras": {"ordinal": 86},
        },
        {
            # sine die: HJNL 20170421, SJNL 20170422 (both: "the day of April 22, 2017")
            "_scraped_name": "General Assembly: 87",
            "classification": "primary",
            "identifier": "2017",
            "name": "2017 Regular Session",
            "start_date": "2017-01-09",
            "end_date": "2017-04-22",
            "active": False,
            "extras": {"ordinal": 87},
        },
        {
            # sine die: HJNL/SJNL 20180505
            "_scraped_name": "General Assembly: 87",
            "classification": "primary",
            "identifier": "2018",
            "name": "2018 Regular Session",
            "start_date": "2018-01-08",
            "end_date": "2018-05-05",
            "active": False,
            "extras": {"ordinal": 87},
        },
        {
            # sine die: HJNL/SJNL 20190427
            "_scraped_name": "General Assembly: 88",
            "classification": "primary",
            "identifier": "2019",
            "name": "2019 Regular Session",
            "start_date": "2019-01-14",
            "end_date": "2019-04-27",
            "active": False,
            "extras": {"ordinal": 88},
        },
        {
            # sine die: HJNL/SJNL 20200614 (the session resumed in June)
            "_scraped_name": "General Assembly: 88",
            "classification": "primary",
            "identifier": "2020",
            "name": "2020 Regular Session",
            "start_date": "2020-01-13",
            "end_date": "2020-06-14",
            "active": False,
            "extras": {"ordinal": 88},
        },
        {
            # sine die: HJNL/SJNL 20210519
            "_scraped_name": "General Assembly: 89",
            "classification": "primary",
            "identifier": "2021",
            "name": "2021 Regular Session",
            "start_date": "2021-01-11",
            "end_date": "2021-05-19",
            "active": False,
            "extras": {"ordinal": 89},
        },
        {
            # 2021 Extraordinary Session: journals of 2021-10-05; bills first acted on from 2021-05-20, the day after the
            # legislature last sat.
            "classification": "special",
            "identifier": "2021s1",
            "name": "2021 Extraordinary Session",
            "start_date": "2021-10-05",
            "end_date": "2021-10-05",
            "active": False,
            "extras": {"ordinal": 89, "bills_filed_from": "2021-05-20"},
        },
        {
            # 2021 Second Extraordinary Session: journals of 2021-10-28; bills first acted on from 2021-10-06, the day after the
            # legislature last sat.
            "classification": "special",
            "identifier": "2021s2",
            "name": "2021 Second Extraordinary Session",
            "start_date": "2021-10-28",
            "end_date": "2021-10-28",
            "active": False,
            "extras": {"ordinal": 89, "bills_filed_from": "2021-10-06"},
        },
        {
            # sine die: HJNL/SJNL 20220524
            "_scraped_name": "General Assembly: 89",
            "classification": "primary",
            "identifier": "2022",
            "name": "2022 Regular Session",
            "start_date": "2022-01-10",
            "end_date": "2022-05-24",
            "active": False,
            "extras": {"ordinal": 89},
        },
        {
            # sine die: HJNL/SJNL 20230504
            "_scraped_name": "General Assembly: 90",
            "classification": "primary",
            "identifier": "2023",
            "name": "2023 Regular Session",
            "start_date": "2023-01-09",
            "end_date": "2023-05-04",
            "active": False,
            "extras": {"ordinal": 90},
        },
        {
            # 2023 Extraordinary Session: journals of 2023-07-11; bills first acted on from 2023-05-05, the day after the
            # legislature last sat. HCR 10, its business resolution, was filed on 2023-07-07, before it convened (H.J. 1051).
            "classification": "special",
            "identifier": "2023s1",
            "name": "2023 Extraordinary Session",
            "start_date": "2023-07-11",
            "end_date": "2023-07-11",
            "active": False,
            "extras": {"ordinal": 90, "bills_filed_from": "2023-05-05"},
        },
        {
            # sine die: HJNL/SJNL 20240419
            "_scraped_name": "General Assembly: 90",
            "classification": "primary",
            "identifier": "2024",
            "name": "2024 Regular Session",
            "start_date": "2024-01-08",
            "end_date": "2024-04-19",
            "active": False,
            "extras": {"ordinal": 90},
        },
        {
            # sine die: HJNL 20250514 ("May 14", 6:31 a.m.), SJNL 20250514 ("the day of May 15, 2025")
            "_scraped_name": "General Assembly: 91",
            "classification": "primary",
            "identifier": "2025",
            "name": "2025 Regular Session",
            "start_date": "2025-01-13",
            "end_date": "2025-05-15",
            "active": True,
            "extras": {"ordinal": 91},
        },
        {
            # sine die: HJNL 20260502, SJNL 20260503 ("the day of Sunday, May 3, 2026")
            "_scraped_name": "General Assembly: 91",
            "classification": "primary",
            "identifier": "2026",
            "name": "2026 Regular Session",
            "start_date": "2026-01-12",
            "end_date": "2026-05-03",
            "active": True,
            "extras": {"ordinal": 91},
        },
        {
            # 2026 Extraordinary Session: journals of 2026-10-02; bills first acted on from 2026-05-04, the day after the
            # legislature last sat.
            "classification": "special",
            "identifier": "2026s1",
            "name": "2026 Extraordinary Session",
            "start_date": "2026-10-02",
            "end_date": "2026-10-02",
            "active": False,
            "extras": {"ordinal": 91, "bills_filed_from": "2026-05-04"},
        },
        {
            # OPEN-744: meets on the second Monday of January (Iowa Constitution Art. III, Sec. 2),
            # the day after General Assembly 91 ends on the site's list. The end date is a placeholder,
            # not a legal end: the 110th calendar day of the first regular session, the last day Iowa
            # Code Sec. 2.10(1) pays members a per diem for. Replace it with the sine die in the
            # journals once the session adjourns. Switched on when its bills appear.
            "_scraped_name": "General Assembly: 92",
            "classification": "primary",
            "identifier": "2027",
            "name": "2027 Regular Session",
            "start_date": "2027-01-11",
            "end_date": "2027-04-30",
            "active": False,
            "extras": {"ordinal": 92},
        },
        {
            # OPEN-744: the second Monday of January 2028; placeholder end, the 100th calendar day of
            # the second regular session (Iowa Code Sec. 2.10(1)).
            "_scraped_name": "General Assembly: 92",
            "classification": "primary",
            "identifier": "2028",
            "name": "2028 Regular Session",
            "start_date": "2028-01-10",
            "end_date": "2028-04-18",
            "active": False,
            "extras": {"ordinal": 92},
        },
    ]
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
