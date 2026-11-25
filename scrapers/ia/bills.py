import re
import datetime
import lxml.html
import requests
import time
from openstates.scrape import Scraper, Bill
from .actions import Categorizer
from .sessions import newest_active_regular, ordinal, session_for_bill

_IA_ORGANIZATION_ENTITY_NAME_KEYWORDS = ["COMMITTEE", "RULES AND ADMINISTRATION"]
_VERSION_HTML_URL_TEMPLATE = (
    "https://www.legis.iowa.gov/docs/publications/LG{}/{}/attachments/{}.html"
)
_VERSION_PDF_URL_TEMPLATE = (
    "https://www.legis.iowa.gov/docs/publications/LG{}/{}/{}.pdf"
)


def version_folder_code(version_abbrev):
    """Map a billVersions <option value> (e.g. "eg", "e", "rm", "r", "i")
    to the publication folder code legis.iowa.gov actually serves docs
    from (LGE, LGR, LGI, ...). The site keys folders off only the first
    letter of the version family, not the full option value."""
    return version_abbrev[0].upper()


def first_action_date(page):
    """The earliest date in a billHistory page's action table, or None (OPEN-745)."""
    dates = []
    for tr in page.xpath("//table[contains(@class, 'billActionTable')][1]/tbody/tr"):
        text = tr.xpath("string(td[contains(text(), ', 20')])").strip()
        try:
            dates.append(datetime.datetime.strptime(text, "%B %d, %Y").date())
        except ValueError:
            continue
    return min(dates, default=None)


# OPEN-797: www.legis.iowa.gov sometimes stops answering for minutes at a time (a page read
# timed out after 60 s and ended a whole session's collection). Upstream's answer is
# --http-resilience, which DDP does not use: it sends made-up browser user-agents, and it
# wraps a second retry loop around scrapelib's own. Instead Iowa gets a bigger budget on
# scrapelib's per-request retry, which every self.get() already goes through: 5 retries,
# waiting 10, 20, 40, 80 and 160 s (SCRAPELIB_RETRY_WAIT_SECONDS doubled each time), each
# logged as a "got ... sleeping for N seconds before retry" warning, with the scraper's own
# user-agent. About 10 minutes from the first timeout to the last try, longer than the
# 7-minute rest this scraper already gives the site below.
RETRY_ATTEMPTS = 5


class IABillScraper(Scraper):
    categorizer = Categorizer()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_attempts = RETRY_ATTEMPTS

    def scrape(self, session=None, chamber=None, prefiles=None):
        self.http_resilience_headers = {"X-Requested-With": "XMLHttpRequest"}
        # openstates/issues#252 - IA continues to prefile after session starts
        # so we'll continue scraping both
        # (filed under the newest regular session switched on, not under an extraordinary
        # session or an earlier year: OPEN-745)
        if session == newest_active_regular(self.jurisdiction.legislative_sessions):
            yield from self.scrape_prefiles(session)

        if prefiles == "True":
            return

        session_id = self.get_session_id(session)
        url = f"https://www.legis.iowa.gov/legislation/findLegislation/allbills?ga={session_id}"
        # OPEN-797: through self.get (timeout, retries) rather than a bare requests.Session,
        # which had neither
        page = lxml.html.fromstring(
            self.get(url, headers={"X-Requested-With": "XMLHttpRequest"}).text
        )
        start_time = time.time()
        for option in page.xpath("//*[@id='sortableTable']/tbody/tr"):
            bill_id = option.xpath("td[2]/a/text()")[0]
            title = option.xpath("td[3]/text()")[0].split("(")[0]
            chamber = "lower" if bill_id[0] == "H" else "upper"
            sponsors = option.xpath("td[6]/text()")[0]
            companion = re.findall(r"[A-Z]+ \d+", option.xpath("string(td[4])"))

            bill_url = f"https://www.legis.iowa.gov/legislation/BillBook?ga={session_id}&ba={bill_id.replace(' ', '')}"

            yield self.scrape_bill(
                chamber,
                session,
                session_id,
                bill_id,
                bill_url,
                title,
                sponsors,
                companion=companion[0] if companion else None,
            )

        # scrapes dropdown options on 'Bill Book' page
        #  to get bill types not found on 'All Bills' page
        bill_book_url = (
            f"https://www.legis.iowa.gov/legislation/BillBook?ga={session_id}"
        )
        bill_book_page = lxml.html.fromstring(self.get(bill_book_url).text)

        other_bill_ids = []
        other_bill_prefixes = {"upper": ["SSB"], "lower": ["HSB"]}

        for chamber, bill_prefixes in other_bill_prefixes.items():
            for prefix in bill_prefixes:
                select = "house" if chamber == "lower" else "senate"
                options = bill_book_page.xpath(
                    f".//select[@id='{select}Select']//option"
                )
                values = [x.get("value") for x in options if prefix in x.get("value")]
                other_bill_ids += values

        for bill_id in other_bill_ids:
            if (time.time() - start_time) >= 600:
                time.sleep(420)
                start_time = time.time()
            bill_url = (
                "https://www.legis.iowa.gov/"
                f"legislation/BillBook?ga={session_id}&ba={bill_id}"
            )
            chamber = "lower" if bill_id[0] == "H" else "upper"

            # title and sponsors for these will be found during detail page scraping
            yield self.scrape_bill(chamber, session, session_id, bill_id, bill_url)

    # IA does prefiles on a separate page, with no bill numbers,
    # after introduction they'll link bill numbers to the prefile doc id
    def scrape_prefiles(self, session):
        prefile_url = (
            "https://www.legis.iowa.gov/legislation/billTracking/prefiledBills"
        )
        page = lxml.html.fromstring(self.get(prefile_url).content)
        page.make_links_absolute(prefile_url)

        for row in page.xpath('//table[contains(@class, "sortable")]/tr[td]'):
            title = row.xpath("td[2]/a/text()")[0].strip()
            url = row.xpath("td[2]/a/@href")[0]

            bill_id = self.extract_doc_id(title)

            bill = Bill(
                bill_id,
                legislative_session=session,
                chamber="legislature",
                title=title,
                classification="proposed bill",
            )

            if row.xpath("td[3]/a"):
                document_url = row.xpath("td[3]/a/@href")[0]
                if ".docx" in document_url:
                    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                elif ".pdf" in document_url:
                    media_type = "application/pdf"
                elif ".xlsx" in document_url or ".xls" in document_url:
                    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                else:
                    media_type = None
                    self.logger.warning(
                        f"Failed to ID media type for bill doc url: {document_url}"
                    )
                if media_type:
                    bill.add_document_link(
                        note="Background Statement",
                        url=document_url,
                        media_type=media_type,
                    )

            bill.add_version_link(
                note="Prefiled", url=url, media_type="application/pdf"
            )

            bill.add_source(prefile_url)

            yield bill

    def extract_doc_id(self, title):
        doc_id = re.findall(r"\((\d{4}\w{2})\)", title)
        return doc_id[0]

    def scrape_subjects(self, bill, bill_number, session):

        self.http_resilience_headers = {"X-Requested-With": "XMLHttpRequest"}
        # self.session.headers.update({"X-Requested-With": "XMLHttpRequest"})

        session_id = self.get_session_id(session)
        bill_id = bill_number.replace(" ", "+")
        subject_url = (
            "https://www.legis.iowa.gov/legislation/BillBook?ga={}"
            "&billName={}&billVersion=i&action=getTaggedTopics&bl=false".format(
                session_id, bill_id
            )
        )

        # In HTTP resilience mode, we will have cookies (--http-resilience)
        if hasattr(self, "session"):
            cookies = self.session.cookies
        else:
            cookies = None
        html = self.get(subject_url, cookies=cookies).text
        page = lxml.html.fromstring(html)

        subjects = page.xpath('//div[@class="taggedTopics"]/a/text()')
        for subject in subjects:
            bill.add_subject(subject.strip())

    def bill_history(self, bill_id, session_id):
        hist_url = (
            f"https://www.legis.iowa.gov/legislation/billTracking/"
            f"billHistory?billName={bill_id}&ga={session_id}"
        )
        return hist_url, self.get(hist_url)

    def scrape_bill(
        self,
        chamber,
        session,
        session_id,
        bill_id,
        url,
        title=None,
        sponsors=None,
        companion=None,
    ):
        # In HTTP resilience mode, we will have cookies (--http-resilience)
        # check if self has attribute session
        if hasattr(self, "session"):
            cookies = self.session.cookies
        else:
            cookies = None
        hist_url, req = self.bill_history(bill_id, session_id)
        if req.status_code == 500:
            self.warning("500 error on {}, skipping".format(hist_url))
            return

        page = lxml.html.fromstring(req.text)
        page.make_links_absolute("https://www.legis.iowa.gov")

        # OPEN-745: every session of a General Assembly reads its one bill list; a bill belongs
        # to one session only, decided by its first dated action (sessions.py), or by its
        # companion's when it has none (SCR 8 of 2023, whose actions are on HCR 10)
        first_action = first_action_date(page)
        if first_action is None and companion:
            _, companion_req = self.bill_history(companion, session_id)
            if companion_req.status_code != 500:
                first_action = first_action_date(
                    lxml.html.fromstring(companion_req.text)
                )
        owner = session_for_bill(
            self.jurisdiction.legislative_sessions, session_id, first_action
        )
        if owner is None:
            self.warning(
                f"Skipping {bill_id}: no session of General Assembly {session_id} holds its "
                f"first dated action ({first_action}, companion {companion})"
            )
            return
        if owner != session:
            self.info(f"Skipping {bill_id}: it belongs to {owner}")
            return

        try:
            sidebar = lxml.html.fromstring(self.get(url, cookies=cookies).text)
            sidebar.make_links_absolute("https://www.legis.iowa.gov")
        except requests.exceptions.ConnectionError:
            self.warning("Connection closed without response, skipping")
            return

        # bills that had neither title nor sponsors passed in
        if not title and not sponsors:
            sponsors_elems = page.xpath(
                ".//div[@style='margin-left:10px;']//div[@class='divideVert']"
            )
            if len(sponsors_elems) == 0:
                self.warning(
                    f"Skipping {bill_id}: No sponsors/title info found at {hist_url}"
                )
                return
            sponsors_div = sponsors_elems[0]

            raw_sponsors = sponsors_div.text
            sponsors = re.sub(r"By\s+", "", raw_sponsors).strip()

            raw_title = sponsors_div.getnext().text
            title = re.sub(r"\(Formerly|\(See", "", raw_title).strip()

        if "HR" in bill_id or "SR" in bill_id:
            bill_type = ["resolution"]
        elif "HJR" in bill_id or "SJR" in bill_id:
            bill_type = ["joint resolution"]
        elif "HCR" in bill_id or "SCR" in bill_id:
            bill_type = ["concurrent resolution"]
        elif "HSB" in bill_id or "SSB" in bill_id:
            bill_type = ["proposed bill"]
        else:
            bill_type = ["bill"]

        bill = Bill(
            bill_id,
            legislative_session=session,
            chamber=chamber,
            title=title,
            classification=bill_type,
        )

        bill.add_source(hist_url)

        # get pieces of version_link
        vpieces = sidebar.xpath('//select[@id="billVersions"]/option')
        if vpieces:
            for version in vpieces:
                version_name = version.text
                version_abbrev = version.xpath("string(@value)")

                folder_code = version_folder_code(version_abbrev)

                # Get HTML document of bill version.
                version_html_url = _VERSION_HTML_URL_TEMPLATE.format(
                    folder_code, session_id, bill_id.replace(" ", "")
                )

                bill.add_version_link(
                    note=version_name, url=version_html_url, media_type="text/html"
                )

                # Get PDF document of bill version.
                version_pdf_url = _VERSION_PDF_URL_TEMPLATE.format(
                    folder_code, session_id, bill_id.replace(" ", "")
                )

                if "Marked Up" in version_name:
                    version_pdf_url = sidebar.xpath(
                        "//iframe[@id='bbContextDoc']/@src"
                    )[0]

                bill.add_version_link(
                    note=version_name, url=version_pdf_url, media_type="application/pdf"
                )

        sponsor_array = sponsors.replace("and", ",").split(",")

        for sponsor in sponsor_array:
            entity_type = "person"
            if any(
                keyword in sponsor for keyword in _IA_ORGANIZATION_ENTITY_NAME_KEYWORDS
            ):
                entity_type = "organization"
            bill.add_sponsorship(
                name=sponsor.strip(),
                classification="primary",
                entity_type=entity_type,
                primary=True,
            )

        for tr in page.xpath(
            "//table[contains(@class, 'billActionTable')][1]/tbody/tr"
        ):
            date = tr.xpath("string(td[contains(text(), ', 20')])").strip()
            if date.startswith("***"):
                continue
            elif "No history is recorded at this time." in date:
                return
            if date == "":
                for anchor in tr.xpath(".//a"):
                    link_text = anchor.text_content()
                    link_url = anchor.xpath("@href")[0]
                    if "signed" in link_text.lower():
                        bill.add_version_link(
                            note=link_text, url=link_url, media_type="application/pdf"
                        )
                    elif "acts" in link_text.lower():
                        bill.add_document_link(
                            note=link_text, url=link_url, media_type="application/pdf"
                        )
                        bill.add_citation(
                            f"IA Acts, {session}",
                            link_text.replace("Acts", ""),
                            citation_type="chapter",
                            url=link_url,
                        )
                continue

            date = datetime.datetime.strptime(date, "%B %d, %Y").date()

            action = tr.xpath("string(td[3])").strip()
            action = re.sub(r"\s+", " ", action)

            # Capture any amendment links.
            links = [link for link in [version["links"] for version in bill.versions]]
            version_urls = [link["url"] for link in [i for sub in links for i in sub]]
            if "amendment" in action.lower():
                for anchor in tr.xpath(".//a[1]"):
                    if "-" in anchor.text:
                        # https://www.legis.iowa.gov/docs/publications/AMDI/88/S3071.pdf
                        amd_pattern = "https://www.legis.iowa.gov/docs/publications/AMDI/{}/{}.pdf"
                        amd_id = anchor.text.replace("-", "").strip()
                        amd_url = amd_pattern.format(session_id, amd_id)
                        amd_name = "Amendment {}".format(anchor.text.strip())

                        if amd_url not in version_urls:
                            bill.add_version_link(
                                note=amd_name, url=amd_url, media_type="application/pdf"
                            )
                            version_urls.append(amd_url)
                        else:
                            self.info("Already Added {}, skipping".format(amd_url))
            else:
                for anchor in tr.xpath(".//a"):
                    link_text = anchor.text_content()
                    link_url = anchor.xpath("@href")[0]
                    action_date = date.strftime("%m/%d/%Y")
                    if "fiscal" in link_text.lower() or "summary" in link_text.lower():
                        # there can be multiple fiscal notes or summaries, so date them
                        doc_title = f"{link_text} {action_date}"
                        bill.add_document_link(
                            note=doc_title, url=link_url, media_type="application/pdf"
                        )
                    elif "signed" in link_text.lower():
                        bill.add_version_link(
                            note=link_text, url=link_url, media_type="application/pdf"
                        )
                    elif "acts" in link_text.lower():
                        bill.add_document_link(
                            note=link_text, url=link_url, media_type="application/pdf"
                        )
                        bill.add_citation(
                            f"IA Acts, {session}",
                            link_text.replace("Acts", ""),
                            citation_type="chapter",
                            url=link_url,
                        )

            if "S.J." in action or "SCS" in action:
                actor = "upper"
            elif "H.J." in action or "HCS" in action:
                actor = "lower"
            else:
                actor = "legislature"

            action = re.sub(r"(H|S)\.J\.\s+\d+\.$", "", action).strip()

            action_attr = self.categorizer.categorize(action.lower())
            atype = action_attr["classification"]

            if action.strip() == "":
                continue

            if re.search(r"END OF \d+ ACTIONS", action):
                continue

            if "$history" not in action:
                bill.add_action(
                    description=action, date=date, chamber=actor, classification=atype
                )

        # OPEN-894: the journal order lists a later "Explanation of vote" ahead of earlier days'
        # actions (310 of 4,206 bills step backwards), so the bill's actions are stored oldest
        # first; the sort is stable, so a day keeps the journal's order (Maine OPEN-839,
        # Hawaii OPEN-823, Wyoming OPEN-780)
        bill.actions.sort(key=lambda a: str(a["date"]))

        self.scrape_subjects(bill, bill_id, session)

        yield bill

    def get_session_id(self, session):
        # https://www.legis.iowa.gov/legislation/BillBook
        # select[@name="gaList"]: the General Assembly every Iowa session is filed under
        return ordinal(self.jurisdiction.legislative_sessions, session)
