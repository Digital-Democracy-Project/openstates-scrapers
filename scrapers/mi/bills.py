import dateutil
import os
import re
import lxml.html
import requests
import scrapelib
import collections
import typing
from datetime import date
from utils.media import get_media_type

from openstates.scrape import Scraper, Bill, VoteEvent
from openstates.utils.cookie_provider import (
    WafBlockDetected,
    content_matches_block_markers,
    content_matches_fake_404_block,
)
from openstates.utils.mi_cookies import MI_COOKIE_PROVIDER
from classify_motion import classify_motion
from ._waf_circuit_breaker import MIWafCircuitBreakerMixin

_categorizers = {
    "approved by governor with line item(s) vetoed": "executive-veto-line-item",
    "read a first time": "reading-1",
    "read a second time": "reading-2",
    "read a third time": "reading-3",
    "introduced by": "introduction",
    "passed": "passage",
    "referred to committee": "referral-committee",
    "reported": "committee-passage",
    "received": "introduction",
    "presented to governor": "executive-receipt",
    "presented to the governor": "executive-receipt",
    "approved by governor": "executive-signature",
    "approved by the governor": "executive-signature",
    "adopted": "passage",
    "amendment(s) adopted": "amendment-passage",
    "amendment(s) defeated": "amendment-failure",
    "vetoed by governor": "executive-veto",
}
BASE_URL = "https://legislature.mi.gov"
# legislature.mi.gov's WAF blocks a generic/bare User-Agent (found 2026-07-28, via
# ddp-open-states's bill-document archive step -- see that repo's PLAN-bill-document-
# provenance.md). Module-level so it's a single source of truth other tools can import
# directly instead of keeping their own hand-copied duplicate that can drift out of sync.
USER_AGENT = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/118.0"

# OPEN-18's consecutive-WAF-block circuit breaker (abort the whole scrape rather than
# silently skipping item after item) lives in _waf_circuit_breaker.py -- extended to
# MIEventScraper by OPEN-22 (AC7), so both scrapers share one threshold/message.

# OPEN-21: MI is the one jurisdiction with a confirmed, escalating reputation-based WAF
# block (see mi_cookies.py's docstring -- cached cookies alone stopped being sufficient
# after a day of heavy traffic), so it gets its own, more conservative request pacing
# instead of the platform-wide default (openstates.settings.SCRAPELIB_RPM, 60/min) applied
# uniformly to every other jurisdiction. 10/min (~1 request every 6s) is a deliberately
# conservative starting point -- roughly 1/6th of the platform default -- chosen to put
# several real seconds of spacing between requests (on top of http_resilience_mode's own
# 1-3s jittered per-request delay) without making a full scrape impractically slow. Not
# derived from a measured threshold (none exists yet); expected to be revisited once
# OPEN-22's sustained-blocking-escalation investigation has more data. Env-configurable
# (like the platform's own SCRAPELIB_RPM/STATS_BATCH_SIZE-style settings) so it can be
# tuned without a redeploy.
MI_SCRAPELIB_RPM = int(os.environ.get("MI_SCRAPELIB_RPM", 10))


class MIResilientScraperMixin:
    """Shared http_resilience_mode configuration for MI's scrapers (OPEN-21).

    Both MIBillScraper and MIEventScraper opt into openstates.scrape.base.Scraper's
    http_resilience_mode unconditionally -- regardless of what the CLI/State
    scraper-instantiation path passes for other jurisdictions -- and use MI's own
    conservative MI_SCRAPELIB_RPM instead of the platform-wide default.

    They also exclude scrapelib.HTTPError and requests.exceptions.ConnectionError from
    request_resiliently's own retry-on-connection-error loop (via the base class's
    _resilience_retry_excluded_exceptions opt-out). Both are already handled by
    mi_waf_get()'s do_request, which retries them itself via a fresh cookie
    invalidate-and-rewarm, exactly once (OPEN-19). Left unexcluded, they'd also be caught
    by request_resiliently's own broad except clause -- scrapelib.HTTPError inherits
    requests.exceptions.RequestException -- and retried there too, up to 3x with
    10s/20s/40s backoff, *before* mi_waf_get ever saw them: doubling MI's request volume
    on every WAF block instead of reducing it, which is the opposite of this ticket's
    point. Excluding just these two keeps mi_waf_get's invalidate-and-retry-once dance as
    the only retry layer for WAF-related failures, while still letting
    http_resilience_mode's other benefits (jittered delay, circuit breaker, connection
    pool reset, and retry-with-backoff for genuine timeouts/URL errors/connection resets
    unrelated to the WAF) apply as normal.
    """

    def __init__(self, *args, **kwargs):
        kwargs["http_resilience_mode"] = True
        super().__init__(*args, **kwargs)
        self.requests_per_minute = MI_SCRAPELIB_RPM
        self._resilience_retry_excluded_exceptions = (
            scrapelib.HTTPError,
            requests.exceptions.ConnectionError,
        )


def mi_waf_get(request_func: typing.Callable[[dict], typing.Any]) -> typing.Any:
    """
    Attach legislature.mi.gov's cached WAF cookies (OPEN-19 -- see
    openstates.utils.mi_cookies for the "sufficient in our testing" framing) to a request
    and retry exactly once, with a fresh cookie warm-up, if a block is detected.

    request_func(cookies: dict) -> response -- everything about the request except the
    cookies should already be bound (e.g. via a lambda) by the caller. Used identically by
    bills.py, events.py, and __init__.py's get_session_list() so the attach-cookies +
    invalidate-and-retry-once contract lives in exactly one place.
    """

    def do_request(cookies: dict) -> typing.Any:
        try:
            resp = request_func(cookies)
        except requests.exceptions.ConnectionError as e:
            raise WafBlockDetected(str(e)) from e
        except scrapelib.HTTPError as e:
            body = getattr(e.response, "content", None)
            if body is None:
                body = (e.body or "").encode()
            if content_matches_fake_404_block(body):
                raise WafBlockDetected(
                    f"{e.response.status_code if e.response else '?'} response matched "
                    "fake-404 WAF block-page heuristic"
                ) from e
            # Not the known block-page signature -- a genuine HTTPError (e.g. a real dead
            # link/malformed ObjectName) must keep propagating unchanged (OPEN-18 AC: don't
            # suppress real 404s).
            raise
        content = getattr(resp, "content", None)
        if content is None:
            content = getattr(resp, "text", "").encode()
        if content_matches_block_markers(content):
            raise WafBlockDetected("response matched known WAF block-page heuristic")
        return resp

    return MI_COOKIE_PROVIDER.fetch_with_retry(do_request)


def categorize_action(action: str) -> str:
    for prefix, atype in _categorizers.items():
        if action.lower().startswith(prefix):
            return atype


class MIBillScraper(MIResilientScraperMixin, MIWafCircuitBreakerMixin, Scraper):
    headers = {}
    verify = False

    # convert from MI's redirector to a bill permalink
    def make_bill_url(self, url: str) -> str:
        match = re.search(r"objectName=([^&]+)", url)
        return f"https://legislature.mi.gov/Bills/Bill?ObjectName={match.group(1)}"

    def scrape(self, session, start=None):
        self.headers = {"User-Agent": USER_AGENT}
        date_from = ""
        if start:
            try:
                dt = dateutil.parser.parse(start)
                date_from = dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
        search_url = f"https://legislature.mi.gov/Search/ExecuteSearch?chamber=&docTypesList=HB%2CSB&docTypesList=HR%2CSR&docTypesList=HCR%2CSCR&docTypesList=HJR%2CSJR&sessions={session}&sponsor=&number=&dateFrom={date_from}&dateTo=&contentFullText="
        page = mi_waf_get(
            lambda cookies: self.get(
                search_url, headers=self.headers, cookies=cookies, verify=False
            )
        ).content
        page = lxml.html.fromstring(page)
        page.make_links_absolute(search_url)

        # UNCOMMENT TO TEST SINGLE BILL
        # Test one specific bill in scrape only
        # bill id string's numerals must be 0-padded to 4 digits
        # bill_id_to_test = "HB 5150"
        # for link in [
        #     link
        #     for link in page.xpath(
        #         "//div[contains(@class,'tableScrollWrapper')]/table[1]/tbody/tr/td[1]/a"
        #     )
        #     if bill_id_to_test in link.xpath("text()")[0].split(" of ")[0]
        # ]:
        #     bill_url = self.make_bill_url(link.xpath("@href")[0])
        #     bill_id = link.xpath("text()")[0].split(" of ")[0]
        #     yield from self.scrape_bill(session, bill_id, bill_url)

        for link in page.xpath(
            "//div[contains(@class,'tableScrollWrapper')]/table[1]/tbody/tr/td[1]/a"
        ):
            bill_url = self.make_bill_url(link.xpath("@href")[0])
            bill_id = link.xpath("text()")[0].split(" of ")[0]
            yield from self.scrape_bill(session, bill_id, bill_url)

    def scrape_bill(self, session: str, bill_id: str, url: str) -> None:
        try:
            page = mi_waf_get(
                lambda cookies: self.get(
                    url, headers=self.headers, cookies=cookies, verify=False
                )
            ).content
        except WafBlockDetected as e:
            self._register_waf_block_or_abort(
                e,
                item_label=f"{bill_id} ({url})",
                scrape_label="MI bill scrape",
                fetch_description="fetching bill pages",
            )
            return
        self._register_waf_success()

        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)

        title = page.xpath("string(//div[@id='ObjectSubject'])").strip()

        heading = page.xpath("//h1[@id='BillHeading']/text()")[0].lower()

        if "house" in heading:
            chamber = "lower"
        elif "senate" in heading:
            chamber = "upper"
        elif "join" in heading:
            chamber = "joint"

        bill_type = "bill"
        for key in ["concurrent resolution", "joint resolution", "resolution"]:
            if key in heading:
                bill_type = key

        bill = Bill(bill_id, session, title, chamber=chamber, classification=bill_type)

        bill.add_source(url)

        self.scrape_actions(bill, page)
        self.scrape_legal(bill, page)
        self.scrape_sponsors(bill, page)
        self.scrape_subjects(bill, page)
        self.scrape_versions(bill, page)
        yield from self.scrape_votes(bill, page)
        yield bill

    def scrape_actions(self, bill: Bill, page: lxml.html.HtmlElement):
        # there can be multiple substitute printings with the same name,
        # but different text
        seen_subs = {}
        for row in page.xpath("//div[@id='History']/table/tbody/tr"):
            when = row.xpath("td[1]/text()")[0]
            when = dateutil.parser.parse(when).date()

            action = row.xpath("string(td[3])").strip()

            journal = row.xpath("string(td[2])").strip()

            if "HJ" in journal:
                actor = "lower"
            elif "SJ" in journal:
                actor = "upper"

            bill.add_action(
                action, when, chamber=actor, classification=categorize_action(action)
            )

            if "substitute" in action.lower() and row.xpath("td[3]/a/@href"):
                version_url = row.xpath("td[3]/a/@href")[0]
                sub = re.search(r"\(.*?\)", action)

                version_name = None
                if sub:
                    version_name = f"Substitute {sub.group(0)}"
                elif "committee of the whole" in action.lower():
                    version_name = "Substitute, reported by Committee of the Whole"
                elif "committee on" in action.lower():
                    match = re.search(
                        r"committee\s+on\s+(.+)\s+with", action, re.IGNORECASE
                    )
                    if match and match.group(1):
                        version_name = f"Substitute {match.group(1)}"

                if not version_name:
                    version_name = "Substitute"

                if version_name in seen_subs:
                    seen_subs[version_name] += 1
                    version_name = f"{version_name} - {seen_subs[version_name]}"
                else:
                    seen_subs[version_name] = 1
                self.info(f"Found Substitute {version_name}, {version_url}")
                bill.add_version_link(
                    version_name,
                    version_url,
                    media_type=get_media_type(version_url, default="text/html"),
                    on_duplicate="ignore",
                )

            # chapter law
            if "assigned pa" in action.lower():
                match = re.search(r"(\d+)'(\d+)", action)
                if match:
                    act_num = match.group(1).lstrip("0")
                    act_year = f"20{match.group(2)}"
                    bill.add_citation(
                        "Michigan Public Acts",
                        f"Public Act {act_num} of {act_year}",
                        citation_type="chapter",
                    )
                else:
                    self.logger.warning(
                        f"Could not match Public Act pattern in string {action} for {bill}"
                    )

    def scrape_votes(self, bill: Bill, page: lxml.html.HtmlElement):

        # Iterate through vote history table rows
        for row in page.xpath("//div[@id='History']/table/tbody/tr"):
            # Extract vote metadata
            when = row.xpath("td[1]/text()")[0]
            when = dateutil.parser.parse(when).date()
            action = row.xpath("string(td[3])").strip()
            journal = row.xpath("string(td[2])").strip()

            # Determine chamber from journal reference
            if "HJ" in journal:
                actor = "lower"
            elif "SJ" in journal:
                actor = "upper"

            # Process roll call votes
            # House format: "Roll Call #44" (no space); Senate: "ROLL CALL # 1" (space)
            rcmatch = re.search(r"Roll Call #\s*(\d+)", action, re.IGNORECASE)
            if rcmatch:
                rc_num = rcmatch.groups()[0]
                vote_url = None
                journal_link = None

                # In format: mileg.aspx?page=getobject&objectname=2011-SJ-02-10-011
                journal_link = row.xpath("td[2]/a/@href")
                chamber_name = {"upper": "Senate", "lower": "House"}[actor]

                # Build vote URL from journal link or generate fallback
                if journal_link:
                    objectname = journal_link[0].rsplit("=", 1)[-1]
                    vote_url = BASE_URL + "/documents/%s/Journal/%s/htm/%s.htm" % (
                        bill.legislative_session,
                        chamber_name,
                        objectname,
                    )
                else:
                    self.warning(
                        f"Missing journal link for {bill.identifier} {action}, Trying to generate it using journal reference {journal}"
                    )
                    vote_url = (
                        self.make_michigan_votes_url_when_journal_link_not_available(
                            action_date=when,
                            journal_reference=journal,
                            base_url=BASE_URL,
                            legislative_session=bill.legislative_session,
                            chamber=chamber_name,
                        )
                    )

                # Parse and validate vote results
                results = self.parse_roll_call(
                    vote_url, rc_num, bill.legislative_session
                )

                if results is not None:
                    vote_passed = len(results["yes"]) > len(results["no"])
                    vote = VoteEvent(
                        start_date=when,
                        chamber=actor,
                        bill=bill,
                        motion_text=action,
                        result="pass" if vote_passed else "fail",
                        classification=classify_motion("mi", action),
                    )

                    # Verify vote count matching the expected count in the action string
                    count = re.search(r"YEAS (\d+)", action, re.IGNORECASE)
                    count = int(count.groups()[0]) if count else 0
                    if count != len(results["yes"]):
                        self.warning(
                            "vote count mismatch for %s %s, %d != %d"
                            % (bill.identifier, action, count, len(results["yes"]))
                        )

                    count = re.search(r"NAYS (\d+)", action, re.IGNORECASE)
                    count = int(count.groups()[0]) if count else 0
                    if count != len(results["no"]):
                        self.warning(
                            "vote count mismatch for %s %s, %d != %d"
                            % (bill.identifier, action, count, len(results["no"]))
                        )

                    vote.set_count("yes", len(results["yes"]))
                    vote.set_count("no", len(results["no"]))
                    vote.set_count("other", len(results["other"]))
                    possible_vote_results = ["yes", "no", "other"]
                    for pvr in possible_vote_results:
                        for name in results[pvr]:
                            if bill.legislative_session == "2017-2018":
                                names = name.split("\t")
                                for n in names:
                                    vote.vote(pvr, n.strip())
                            else:
                                # Prevents voter names like "House Bill No. 4451, entitled" and other sentences
                                if len(name.split()) < 5:
                                    vote.vote(pvr, name.strip())

                    # Emit the parsed roll-call number so downstream consumers can
                    # tell a real recorded vote from an empty/summary passage motion
                    # (mirrors usa/votes.py's house/senate-rollcall-num extras).
                    vote.extras[
                        "senate-rollcall-num" if actor == "upper" else "house-rollcall-num"
                    ] = rc_num
                    vote.add_source(vote_url)
                    yield vote

    def make_michigan_votes_url_when_journal_link_not_available(
        self,
        action_date: date,
        journal_reference: str,
        base_url: str,
        legislative_session: str,
        chamber: str,
    ) -> str:

        journal_match = re.search(r"[HS]J\s+(\d+)", journal_reference)
        if not journal_match:
            self.warning(f"Could not extract journal number from '{journal_reference}'")
            return None

        if not isinstance(action_date, date):
            self.warning(
                f"Invalid action_date while generating vote url: {action_date}, must be a datetime.date object"
            )
            return None

        journal_num = journal_match.group(1).zfill(3)
        date_formatted = action_date.strftime("%m-%d")
        journal_prefix = "SJ" if chamber == "Senate" else "HJ"
        year = str(action_date.year)
        objectname = f"{year}-{journal_prefix}-{date_formatted}-{journal_num}"
        return f"{base_url}/documents/{legislative_session}/Journal/{chamber}/htm/{objectname}.htm"

    def parse_roll_call(self, url, rc_num, session):
        try:
            resp = mi_waf_get(
                lambda cookies: self.get(
                    url, headers=self.headers, cookies=cookies, verify=False
                )
            )
        except (scrapelib.HTTPError, WafBlockDetected):
            self.warning(
                f"Could not fetch roll call document at {url}, unable to extract vote"
            )
            return
        html = resp.text
        vote_doc = lxml.html.fromstring(html)
        vote_doc_textonly = vote_doc.text_content()

        if re.search("In\\s+The\\s+Chair", vote_doc_textonly) is None:
            self.warning('"In The Chair" indicator not found, unable to extract vote')
            return

        # Split the file into lines using the <p> tags
        pieces = [
            p.text_content().replace("\xa0", " ").replace("\r\n", " ")
            for p in vote_doc.xpath("//p")
        ]

        # Go until we find the roll call
        for i, p in enumerate(pieces):
            if p.startswith(f"Roll Call No. {rc_num}"):
                break

        vtype = None
        results = collections.defaultdict(list)

        # Once we find the roll call, go through voters
        for p in pieces[i:]:
            if "Yeas" in p:
                vtype = "yes"
            elif "Nays" in p:
                vtype = "no"
            elif "Excused" in p or "Not Voting" in p:
                vtype = "other"
            elif "Roll Call No" in p:
                continue
            elif p.startswith("In The Chair:"):
                break
            elif vtype:
                # Split on tabs (House journals) or multiple spaces (Senate journals)
                for line in re.split(r"\t|(?<!,)\s{2,}", p):
                    if line.strip():
                        if session == "2017-2018":
                            for leg in line.split():
                                results[vtype].append(leg)
                        else:
                            results[vtype].append(line)
            else:
                self.warning("piece without vtype set: %s", p)

        return results

    def scrape_legal(self, bill: Bill, page: lxml.html.HtmlElement):
        for row in page.xpath(
            "//div[@id='ObjectSubject']/a[contains(@href,'?sectionNumbers')]/text()"
        ):
            bill.add_citation(
                "Michigan Compiled Laws", f"MCL {row.strip()}", citation_type="proposed"
            )

    def scrape_sponsors(self, bill: Bill, page: lxml.html.HtmlElement):
        for row in page.xpath(
            "//li[contains(@title, 'sponsored')]/a[contains(@class,'primarySponsor')]"
        ):
            sponsor = row.xpath("text()")[0].split("(")[0].strip()
            bill.add_sponsorship(
                sponsor, classification="primary", entity_type="person", primary=True
            )

        for row in page.xpath(
            "//li[contains(@title, 'sponsored')]/a[not(contains(@class,'primarySponsor'))]"
        ):
            sponsor = row.xpath("text()")[0].split("(")[0].strip()
            bill.add_sponsorship(
                sponsor, classification="cosponsor", entity_type="person", primary=False
            )

    def scrape_subjects(self, bill: Bill, page: lxml.html.HtmlElement):
        # union with the second expression is just in case they fix the typo
        for row in page.xpath(
            "//div[@id='CateogryList']/a|//div[@id='CategoryList']/a"
        ):
            bill.add_subject(row.xpath("text()")[0].strip())

    def scrape_versions(self, bill: Bill, page: lxml.html.HtmlElement):
        for row in page.xpath("//div[@class='billDocuments']/div[@class='billDocRow']"):
            name = row.xpath(".//div[@class='text']/span/strong/text()")[0]
            if row.xpath(".//div[@class='pdf']/a/@href"):
                bill.add_version_link(
                    name,
                    row.xpath(".//div[@class='pdf']/a/@href")[0],
                    media_type="application/pdf",
                    on_duplicate="ignore",
                )
            if row.xpath(".//div[@class='html']/a/@href"):
                bill.add_version_link(
                    name,
                    row.xpath(".//div[@class='html']/a/@href")[0],
                    media_type="text/html",
                    on_duplicate="ignore",
                )

        for row in page.xpath(
            "//div[@id='HFAAnalysisSection']/div/div[@class='billDocRow']|//div[@id='SFAAnalysisSection']/div/div[@class='billDocRow']"
        ):
            name = row.xpath(".//div[@class='text']/span/strong/text()")[0]
            if row.xpath(".//div[@class='pdf']/a/@href"):
                bill.add_document_link(
                    name,
                    row.xpath(".//div[@class='pdf']/a/@href")[0],
                    media_type="application/pdf",
                    on_duplicate="ignore",
                )
            if row.xpath(".//div[@class='html']/a/@href"):
                bill.add_document_link(
                    name,
                    row.xpath(".//div[@class='html']/a/@href")[0],
                    media_type="text/html",
                    on_duplicate="ignore",
                )

    #         # check if action mentions a sub
    #         submatch = re.search(
    #             r"WITH SUBSTITUTE\s+([\w\-\d]+)", action, re.IGNORECASE
    #         )
    #         if submatch and tds[2].xpath("a"):
    #             version_url = tds[2].xpath("a/@href")[0]
    #             version_name = tds[2].xpath("a/text()")[0].strip()
    #             version_name = "Substitute {}".format(version_name)
    #             self.info("Found Substitute {}".format(version_url))
    #             if version_url.lower().endswith(".pdf"):
    #                 mimetype = "application/pdf"
    #             elif version_url.lower().endswith(".htm"):
    #                 mimetype = "text/html"
    #             bill.add_version_link(version_name, version_url, media_type=mimetype)
