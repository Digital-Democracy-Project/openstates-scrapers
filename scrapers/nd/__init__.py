from openstates.scrape import State
from .bills import NDBillScraper
from .events_web import NDEventScraper
from .events import NDEventsCSVScraper


settings = {
    "SCRAPELIB_RPM": 5,
    "SCRAPELIB_RETRY_ATTEMPTS": 6,
    "SCRAPELIB_RETRY_WAIT_SECONDS": 30,
}


class NorthDakota(State):
    scrapers = {
        "bills": NDBillScraper,
        "events_web": NDEventScraper,
        "events": NDEventsCSVScraper,
    }
    # OPEN-746: each special session is a session of its own, with its own dates (Ramon 2026-11-21:
    # "regular session and special session are two different things. don't ever mix their dates
    # together"). The legislature names them "<n>th Legislative Assembly - Special Session (<Mon
    # yyyy>)" (its pages ndlegis.gov/assembly/<assembly>/special and .../special-2, which give the
    # convened and adjourned days used below) and its journals list each one apart ("2016 Special
    # Session House and Senate Journals", research-and-archives/journals). The site's API keeps
    # one bill list per Legislative Assembly (api/assembly/<assembly>/data/bills.json) and tags
    # every bill with its own session (`session_id`: 201501 for the 2015 Regular Session, 201502
    # for the special session of August 2016), so each session reads its assembly's list and keeps
    # only the bills tagged with its `site_session_id` (bills.py). A regular session's assembly is
    # "<identifier>-<start year>" and its tag "<start year>01"; a special session names both in
    # `extras`.
    legislative_sessions = [
        {
            "_scraped_name": "62nd Legislative Assembly (2011-12)",
            "identifier": "62",
            "name": "62nd Legislative Assembly (2011-2012)",
            "start_date": "2011-01-04",
            "end_date": "2011-04-28",
            "classification": "primary",
        },
        {
            # ndlegis.gov/assembly/62-2011/special: convened Monday, November 7, 2011,
            # adjourned Friday, November 11, 2011
            "identifier": "62S1",
            "name": "62nd Legislative Assembly - Special Session (Nov 2011)",
            "start_date": "2011-11-07",
            "end_date": "2011-11-11",
            "classification": "special",
            "active": False,
            "extras": {"assembly": "62-2011", "site_session_id": "201102"},
        },
        {
            "_scraped_name": "63rd Legislative Assembly (2013-14)",
            "identifier": "63",
            "name": "63rd Legislative Assembly (2013-2014)",
            "start_date": "2013-01-08",
            "end_date": "2013-05-04",
            "classification": "primary",
        },
        {
            "_scraped_name": "64th Legislative Assembly (2015-16)",
            "identifier": "64",
            "name": "64th Legislative Assembly (2015-2016)",
            "start_date": "2015-01-08",
            "end_date": "2015-04-29",
            "classification": "primary",
        },
        {
            # ndlegis.gov/assembly/64-2015/special: convened Tuesday, August 2, 2016,
            # adjourned Thursday, August 4, 2016
            "identifier": "64S1",
            "name": "64th Legislative Assembly - Special Session (Aug 2016)",
            "start_date": "2016-08-02",
            "end_date": "2016-08-04",
            "classification": "special",
            "active": False,
            "extras": {"assembly": "64-2015", "site_session_id": "201502"},
        },
        {
            "_scraped_name": "65th Legislative Assembly (2017-18)",
            "identifier": "65",
            "name": "65th Legislative Assembly (2017-2018)",
            "start_date": "2017-01-03",
            "end_date": "2017-04-27",
            "classification": "primary",
        },
        {
            "_scraped_name": "66th Legislative Assembly (2019-20)",
            "identifier": "66",
            "name": "66th Legislative Assembly (2019-2020)",
            "start_date": "2019-01-03",
            "end_date": "2019-04-26",
            "classification": "primary",
        },
        {
            "_scraped_name": "67th Legislative Assembly (2021-22)",
            "identifier": "67",
            "name": "67th Legislative Assembly (2021-2022)",
            "start_date": "2021-01-05",
            "end_date": "2021-04-29",
            "classification": "primary",
            "active": False,
        },
        {
            "_scraped_name": "67th (2021) Legislative Assembly Special 2021 Session",
            # ndlegis.gov/assembly/67-2021/special: convened Monday, November 8, 2021, adjourned
            # Friday, November 12, 2021
            "identifier": "67S1",
            "name": "67th Legislative Assembly - Special Session (Nov 2021)",
            "start_date": "2021-11-08",
            "end_date": "2021-11-12",
            "classification": "special",
            "active": False,
            "extras": {"assembly": "67-2021", "site_session_id": "202102"},
        },
        {
            "_scraped_name": "68th Legislative Assembly (2023-24)",
            "identifier": "68",
            "name": "68th Legislative Assembly (2023-24)",
            "start_date": "2023-01-03",
            "end_date": "2023-05-10",
            "classification": "primary",
            "active": False,
        },
        {
            # ndlegis.gov/assembly/68-2023/special: convened Monday, October 23, 2023,
            # adjourned Wednesday, October 25, 2023
            "identifier": "68S1",
            "name": "68th Legislative Assembly - Special Session (Oct 2023)",
            "start_date": "2023-10-23",
            "end_date": "2023-10-25",
            "classification": "special",
            "active": False,
            "extras": {"assembly": "68-2023", "site_session_id": "202302"},
        },
        {
            "_scraped_name": "69th Legislative Assembly (2025-26)",
            "identifier": "69",
            "name": "69th Legislative Assembly (2025-26)",
            "start_date": "2025-01-07",
            "end_date": "2025-05-02",
            "classification": "primary",
            "active": True,
        },
        {
            # ndlegis.gov/assembly/69-2025/special: convened Wednesday, January 21, 2026,
            # adjourned Friday, January 23, 2026
            "identifier": "69S1",
            "name": "69th Legislative Assembly - Special Session (Jan 2026)",
            "start_date": "2026-01-21",
            "end_date": "2026-01-23",
            "classification": "special",
            "active": False,
            "extras": {"assembly": "69-2025", "site_session_id": "202502"},
        },
        {
            # ndlegis.gov/assembly/69-2025/special-2: convened Wednesday, September 2, 2026,
            # adjourned Friday, September 4, 2026
            "identifier": "69S2",
            "name": "69th Legislative Assembly - Special Session (Sep 2026)",
            "start_date": "2026-09-02",
            "end_date": "2026-09-04",
            "classification": "special",
            "active": False,
            "extras": {"assembly": "69-2025", "site_session_id": "202503"},
        },
        {
            "_scraped_name": "70th Legislative Assembly (2027-28)",
            "identifier": "70",
            "name": "70th Legislative Assembly (2027-28)",
            "start_date": "2027-01-07",  # TODO approximate; get real date when closer
            "end_date": "2028-05-02",  # TODO approximate; get real date when closer
            "classification": "primary",
            "active": False,
        },
    ]
    ignored_scraped_sessions = [
        "61st Legislative Assembly (2009-10)",
        "60th Legislative Assembly (2007-08)",
        "59th Legislative Assembly (2005-06)",
        "58th Legislative Assembly (2003-04)",
        "57th Legislative Assembly (2001-02)",
        "56th Legislative Assembly (1999-2000)",
        "55th Legislative Assembly (1997-98)",
        "54th Legislative Assembly (1995-96)",
        "53rd Legislative Assembly (1993-94)",
        "52nd Legislative Assembly (1991-92)",
        "51st Legislative Assembly (1989-90)",
        "50th Legislative Assembly (1987-88)",
        "49th Legislative Assembly (1985-86)",
        "48th Legislative Assembly (1983-84)",
        "47th Legislative Assembly (1981-82)",
        "46th Legislative Assembly (1979-80)",
        "45th Legislative Assembly (1977-78)",
        "44th Legislative Assembly (1975-76)",
        "43rd Legislative Assembly (1973-74)",
        "42nd Legislative Assembly (1971-72)",
        "41st Legislative Assembly (1969-70)",
        "40th Legislative Assembly (1967-68)",
        "39th Legislative Assembly (1965-66)",
        "38th Legislative Assembly (1963-64)",
        "37th Legislative Assembly (1961-62)",
        "36th Legislative Assembly (1959-60)",
        "35th Legislative Assembly (1957-58)",
        "1st Legislative Assembly (1889-90)",
        "2nd Legislative Assembly (1891-92)",
        "3rd Legislative Assembly (1893-94)",
        "4th Legislative Assembly (1895-96)",
        "5th Legislative Assembly (1897-98)",
        "6th Legislative Assembly (1899-1900)",
        "7th Legislative Assembly (1901-02)",
        "8th Legislative Assembly (1903-04)",
        "9th Legislative Assembly (1905-06)",
        "10th Legislative Assembly (1907-08)",
        "11th Legislative Assembly (1909-10)",
        "12th Legislative Assembly (1911-12)",
        "13th Legislative Assembly (1913-14)",
        "14th Legislative Assembly (1915-16)",
        "15th Legislative Assembly (1917-18)",
        "16th Legislative Assembly (1919-20)",
        "17th Legislative Assembly (1921-22)",
        "18th Legislative Assembly (1923-24)",
        "19th Legislative Assembly (1925-26)",
        "20th Legislative Assembly (1927-28)",
        "21st Legislative Assembly (1929-30)",
        "22nd Legislative Assembly (1931-32)",
        "23rd Legislative Assembly (1933-34)",
        "24th Legislative Assembly (1935-36)",
        "25th Legislative Assembly (1937-38)",
        "26th Legislative Assembly (1939-40)",
        "27th Legislative Assembly (1941-42)",
        "28th Legislative Assembly (1943-44)",
        "29th Legislative Assembly (1945-46)",
        "30th Legislative Assembly (1947-48)",
        "31st Legislative Assembly (1949-50)",
        "32nd Legislative Assembly (1951-52)",
        "33rd Legislative Assembly (1953-54)",
        "34th Legislative Assembly (1955-56)",
    ]

    def get_session_list(self):
        import scrapelib
        import lxml.html

        url = "http://www.legis.nd.gov/assembly/"
        html = scrapelib.Scraper().get(url).text
        doc = lxml.html.fromstring(html)
        doc.make_links_absolute(url)
        sessions = doc.xpath("//div[@class='view-content']//a/text()")
        sessions = [
            session for session in sessions if "Territorial Assembly" not in session
        ]
        return sessions
