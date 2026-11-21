import datetime as dt
import lxml.html
import os
import pytz
import re
import scrapelib

from openstates.scrape import Scraper, Bill, VoteEvent
from openstates.utils import convert_pdf
from .actions import Categorizer
from .consent import (
    CONSENT_HEADER,
    consent_calendars,
    journal_urls,
    match_consent_votes,
)

from classify_motion import classify_motion
from utils import url_xpath

subjects = None
bill_subjects = None

# What a silly low number. This is just putting more load on the
# server, not even helping with that. Sheesh.
MAXQUERY = 250
RI_URL_BASE = "https://webserver.rilegislature.gov"

# OPEN-683: a roll call's header ends with the motion, one to three lines under the
# bill's title: House "PASSAGE" / "AS AMENDED" / "PASSAGE OF AMENDMENT", Senate
# "Approval of Amendment" / "Passage" ("In Concurrence / Passage" and "Approval of
# Amendment / Passage" are both seen). These are the lines the motion is made of.
MOTION_LINE = re.compile(
    r"^(passage( as amended)?|as amended|in concurrence|(passage|approval) of amendment"
    r"|reconsideration|ruling of the chair)$",
    re.I,
)
# the line naming a budget article ("ARTICLE 2"), voted on one by one in the House
ARTICLE_LINE = re.compile(r"^ARTICLE\s+\d+$", re.I)
AMENDMENT_VOTE = re.compile(r"\b(passage|approval) of amendment\b", re.I)
# OPEN-701: a calendar item whose bill number is printed without its year
# ("ITEM 31    3225 SUB A as amended", "ITEM 24   S 122 SUB A", "ITEM 34   -S 70").
# A bill number of 0 ("ITEM 8                        0") is a nomination, not a
# bill, and is not read. With no chamber letter, the number is looked up
# in both chambers: a session's House and Senate numbers do not overlap.
YEARLESS_ITEM = re.compile(
    r"^ITEM\s+\d+\s+-?(?:(?P<chamber>[SH])\s*)?(?P<bill>[1-9][0-9]*)\b"
)


def vote_motion(headers):
    """The motion of a roll call from its header lines: the motion lines at the end
    joined with " / " ("PASSAGE / AS AMENDED"), else the last line as before (a
    header with no motion line, such as a point of order, ends in the title). A
    budget article's vote keeps its article ("ARTICLE 2 PASSAGE"): it cannot pass
    or kill the whole bill."""
    lines = [h.strip() for h in headers if h.strip()]
    motion = []
    while lines and MOTION_LINE.match(lines[-1]):
        motion.insert(0, lines.pop())
    motion = " / ".join(motion) if motion else (headers[-1].strip() if headers else "")
    article = [h for h in lines if ARTICLE_LINE.match(h)]
    if article:
        motion = "%s %s" % (article[0], motion)
    return motion


def vote_classification(motion):
    """What a roll call decides: passage from the ri block of
    config/motion_classification.yaml, else "amendment" for an amendment roll
    call (the YAML only decides passage), else nothing."""
    classification = classify_motion("ri", motion)
    if classification:
        return classification
    if AMENDMENT_VOTE.search(motion):
        return ["amendment"]
    return []


def bill_start_numbers(session):
    # differs by first/second session in term
    if int(session) % 2 == 0:
        return {"lower": [6500, 7000], "upper": [2000]}
    else:
        return {"lower": [5000], "upper": [1]}


def get_postable_subjects():
    global subjects
    if subjects is None:
        subs = url_xpath(
            "https://status.rilegislature.gov/",
            "//select[@id='rilinContent_cbCategory']",
        )[0].xpath("./*")
        subjects = {o.text: o.attrib["value"] for o in subs}
        subjects.pop(None)
    return subjects


def get_default_headers(page):
    headers = {}
    for el in url_xpath(page, "//*[@name]"):
        name = el.attrib["name"]
        value = ""
        try:
            value = el.attrib["value"]
        except KeyError:
            value = el.text

        if value:
            value = value.strip()

        headers[name] = value or ""
    headers["__EVENTTARGET"] = ""
    headers["__EVENTARGUMENT"] = ""
    headers["__LASTFOCUS"] = ""
    return headers


SEARCH_URL = "https://status.rilegislature.gov/"

BILL_NAME_TRANSLATIONS = {
    "House Bill No.": "HB",
    "Senate Bill No.": "SB",
    "Senate Resolution No.": "SR",
    "House Resolution No.": "HR",
    "Senate Concurrent Resolution No.": "SCR",
    "House Concurrent Resolution No.": "HCR",
}

BILL_STRING_FLAGS = {
    "bill_id": r"^[House|Senate].*",
    "sponsors": r"^BY.*",
    "title": r"ENTITLED,.*",
    "version": r"\{.*\}",
    "resolution": r"Resolution.*",
    "chapter": r"^Chapter.*",
    "by_request": r"^\(.*\)$",
    "act": r"^Act\ \d*$",
}

BILL_TITLE_RE = re.compile(r"ENTITLED,\s+([^(]+)(\(.+\))?")


class RIBillScraper(Scraper):
    # when scraping votes we only get 'S101' so we can't tie them to their parent bill
    # so we keep a dict of (chamber, number) -> bill_id from the bill scrape to be used in the
    # vote scrape
    _bill_id_by_type = {}
    categorizer = Categorizer()
    _tz = pytz.timezone("US/Eastern")

    def parse_results_page(self, page):
        blocks = []
        current = []

        p = lxml.html.fromstring(page)
        if "We're Sorry! You seem to be lost." in p.text_content():
            raise ValueError("POSTing has gone wrong")

        nodes = p.xpath("//span[@id='lblBills']/*")
        for node in nodes:
            if node.tag == "br":
                if len(current) > 0:
                    blocks.append(current)
                    current = []
            else:
                current.append(node)
        if current:
            blocks.append(current)
        return blocks

    def digest_results_page(self, nodes):
        blocks = {}
        for node in nodes:
            nblock = {"actions": []}
            lines = [(n.text_content().strip(), n) for n in node]
            if "No Bills Met this Criteria" in [x[0] for x in lines]:
                self.info("No results. Skipping block")
                return []

            for line in lines:
                line, node = line
                if (
                    "Total Bills:" in line
                    and "State House, Providence, Rhode Island" in line
                ):
                    continue

                found = False
                for regexp in BILL_STRING_FLAGS:
                    if re.match(BILL_STRING_FLAGS[regexp], line):
                        hrefs = node.xpath("./a")
                        if len(hrefs) > 0:
                            nblock[regexp + "_hrefs"] = hrefs
                        nblock[regexp] = line
                        found = True
                if not found:
                    nblock["actions"].append(line)

            self.info("Working on %s" % (nblock.get("bill_id")))
            if "bill_id" in nblock:
                blocks[nblock["bill_id"]] = nblock
            else:
                # either we got a bad block, or they skipped a span of bill numbers
                # in 2022 they did 6500-6700, then restarted at 7000
                self.warning("Current entry doesn't have a matching bill id")
                self.warning("Did they skip around?")
        return blocks

    def get_subject_bill_dict(self, session):
        global bill_subjects
        if bill_subjects is not None:
            return bill_subjects
        ret = {}
        subjects = get_postable_subjects()
        self.info("getting subjects (total=%s)", len(subjects))
        for subject in subjects:

            default_headers = get_default_headers(SEARCH_URL)

            default_headers["ctl00$rilinContent$cbCategory"] = subjects[subject]
            default_headers["ctl00$rilinContent$cbYear"] = session

            self.info(f"Fetching bills subject mapping for {subject}")
            blocks = self.parse_results_page(
                self.post(SEARCH_URL, data=default_headers).text
            )
            blocks = blocks[1:-1]
            blocks = self.digest_results_page(blocks)
            for block in blocks:
                try:
                    ret[block].append(subject)
                except KeyError:
                    ret[block] = [subject]
        bill_subjects = ret
        return bill_subjects

    def process_actions(self, actions, bill):
        for action in actions:
            actor = "legislature"

            if "house" in action.lower():
                actor = "lower"

            if "senate" in action.lower():
                actor = "upper"

            if "joint" in action.lower():
                actor = "legislature"

            if "governor" in action.lower():
                actor = "executive"
            date = action.split(" ")[0]
            date = dt.datetime.strptime(date, "%m/%d/%Y")
            action_attr = self.categorizer.categorize(action)
            atype = action_attr["classification"]

            bill.add_action(
                action,
                date.strftime("%Y-%m-%d"),
                chamber=actor,
                classification=atype,
            )

    def get_type_by_name(self, name):
        name = name.lower()
        self.info(name)

        things = ["resolution", "joint resolution", "memorial", "memorandum", "bill"]

        for t in things:
            if t in name:
                self.info("Returning %s" % t)
                return t

        self.warning("XXX: Bill type fallthrough. This ain't great.")
        return "bill"

    def scrape_bills(self, chamber, session, subjects):
        idexes = bill_start_numbers(session)[chamber]
        FROM = "ctl00$rilinContent$txtBillFrom"
        TO = "ctl00$rilinContent$txtBillTo"
        YEAR = "ctl00$rilinContent$cbYear"
        for idex in idexes:
            blocks = "FOO"  # Ugh.
            while len(blocks) > 0:
                self.info(
                    f"Searching for bills in {chamber} in range {idex} to {idex + MAXQUERY}"
                )
                default_headers = get_default_headers(SEARCH_URL)
                default_headers[FROM] = idex
                default_headers[TO] = idex + MAXQUERY
                default_headers[YEAR] = session
                idex += MAXQUERY
                blocks = self.parse_results_page(
                    self.post(SEARCH_URL, data=default_headers).text
                )
                blocks = blocks[1:-1]
                blocks = self.digest_results_page(blocks)

                for block in blocks:
                    bill = blocks[block]
                    subs = []
                    try:
                        subs = subjects[bill["bill_id"]]
                    except KeyError:
                        pass

                    title_match = BILL_TITLE_RE.match(bill["title"])
                    title = title_match[1].strip()
                    abstract = None
                    if title_match[2]:
                        abstract = title_match[2].strip("() ")

                    billid = bill["bill_id"]
                    try:
                        subs = subjects[bill["bill_id"]]
                    except KeyError:
                        subs = []

                    for b in BILL_NAME_TRANSLATIONS:
                        if billid[: len(b)] == b:
                            billid = (
                                BILL_NAME_TRANSLATIONS[b]
                                + billid[len(b) + 1 :].split()[0]
                            )

                    b = Bill(
                        billid,
                        title=title,
                        chamber=chamber,
                        legislative_session=session,
                        classification=self.get_type_by_name(bill["bill_id"]),
                    )
                    b.subject = subs

                    if abstract:
                        b.add_abstract(abstract, "summary")

                    # keep bill ID around
                    self._bill_id_by_type[
                        (chamber, re.findall(r"\d+", billid)[0])
                    ] = billid

                    self.process_actions(bill["actions"], b)
                    sponsors = bill["sponsors"][len("BY") :].strip()
                    sponsors = sponsors.split(",")
                    sponsors = [s.strip() for s in sponsors]

                    for href in bill["bill_id_hrefs"]:
                        b.add_version_link(
                            href.text, href.attrib["href"], media_type="application/pdf"
                        )

                    for sponsor in sponsors:
                        b.add_sponsorship(
                            sponsor,
                            entity_type="person",
                            classification="primary",
                            primary=True,
                        )

                    b.add_source(SEARCH_URL)
                    yield b

    def scrape(self, chamber=None, session=None):
        chambers = [chamber] if chamber is not None else ["upper", "lower"]

        # NOTE: disabled by showerst 2024-01-04
        # this is making 350 POST requests because there are almost no subjects
        # assigned yet, but the 2023 subjects are still posted.
        # possibly restore this later.
        # subjects = self.get_subject_bill_dict(session)
        subjects = {}

        # OPEN-701: every chamber's bills before any votes, so a Senate roll call on a
        # House bill (and the reverse) finds its bill
        for chamber in chambers:
            yield from self.scrape_bills(chamber, session, subjects)
        for chamber in chambers:
            yield from self.scrape_chamber_votes(chamber, session)

    def scrape_chamber_votes(self, chamber, session):
        url = {
            "upper": "%s/%s" % (RI_URL_BASE, "SVotes"),
            "lower": "%s/%s" % (RI_URL_BASE, "HVotes"),
        }[chamber]
        action = "%s/%s" % (url, "votes.asp")
        dates = self.get_vote_dates(url, session)
        for date in dates:
            votes = self.parse_vote_page(self.post_to(action, date), url, session)
            consent = []
            for vote_dict in votes:
                for vote in vote_dict.values():
                    if vote["meta"].get("consent"):
                        # OPEN-711: a Senate consent roll call names no bill; its bills
                        # come from that day's Senate Journal below. The House votes
                        # each consent item on its own, so its opening vote stays out.
                        if chamber == "upper":
                            consent.append(vote)
                        continue
                    letters = vote["meta"]["chamber"] or "SH"
                    found = [
                        ({"H": "lower", "S": "upper"}[c], vote["meta"]["bill"])
                        for c in letters
                    ]
                    found = [k for k in found if k in self._bill_id_by_type]
                    if len(found) != 1:
                        self.warning(
                            "no such bill_id %s %s", letters, vote["meta"]["bill"]
                        )
                        continue
                    yield self.vote_event(
                        chamber,
                        session,
                        vote,
                        vote["meta"]["extra"]["motion"],
                        self._bill_id_by_type[found[0]],
                        found[0][0],
                        vote["source"],
                    )
            if consent:
                yield from self.consent_vote_events(date, session, consent)

    def vote_event(
        self, chamber, session, vote, motion, bill_id, bill_chamber, dedupe_key
    ):
        count = vote["count"]
        # OPEN-701: the vote's chamber is the page's (SVotes / HVotes), not the
        # bill's: the House also votes on Senate bills and the reverse
        v = VoteEvent(
            chamber=chamber,
            start_date=self._tz.localize(vote["time"]),
            motion_text=motion,
            result="pass" if count["passage"] else "fail",
            classification=vote_classification(motion),
            legislative_session=session,
            bill=bill_id,
            bill_chamber=bill_chamber,
        )
        v.set_count("yes", int(count["YEAS"]))
        v.set_count("no", int(count["NAYS"]))
        # recused members are itemized as "other" too
        v.set_count(
            "other",
            int(count["NOT VOTING"]) + int(count.get("RECUSED", 0)),
        )
        v.add_source(vote["source"])
        v.dedupe_key = dedupe_key

        for vt in vote["votes"]:
            key = {"Y": "yes", "N": "no"}.get(vt["vote"], "other")
            v.vote(key, vt["name"])
        return v

    def consent_vote_events(self, date, session, roll_calls):
        """OPEN-711: one vote event per bill on each Senate consent calendar of `date`,
        the bills read from that day's Senate Journal (consent.py). The key is the roll
        call's report URL plus the bill, so the one roll call gives each bill its own
        vote (OPEN-252, OPEN-397). A day whose journal is missing, or whose calendars
        cannot be matched to its roll calls, gives none."""
        roll_calls = sorted(
            roll_calls, key=lambda v: int(v["source"].rsplit("=", 1)[1])
        )
        journal, calendars = self.senate_journal_consent_calendars(date)
        pairs = match_consent_votes(
            [
                {"yeas": int(v["count"]["YEAS"]), "nays": int(v["count"]["NAYS"])}
                for v in roll_calls
            ],
            calendars,
        )
        if not pairs:
            self.warning(
                "consent calendar %s: %d roll calls, %d journal calendars (%s); not tied",
                date,
                len(roll_calls),
                len(calendars),
                journal,
            )
            return
        for n, (vote, (_, calendar)) in enumerate(zip(roll_calls, pairs), 1):
            motion = "Consent Calendar" if n == 1 else "Consent Calendar #%d" % n
            for line in calendar["unread"]:
                # neither a bill nor a nomination: a layout the parser does not know
                self.warning("consent calendar %s: item not read: %s", date, line)
            for year, letter, number in calendar["bills"]:
                key = ({"H": "lower", "S": "upper"}[letter], number)
                if year != session[:4] or key not in self._bill_id_by_type:
                    self.warning("no such bill_id %s-%s %s", year, letter, number)
                    continue
                bill_id = self._bill_id_by_type[key]
                v = self.vote_event(
                    "upper",
                    session,
                    vote,
                    motion,
                    bill_id,
                    key[0],
                    "%s#%s" % (vote["source"], bill_id),
                )
                v.add_source(journal)
                yield v

    def senate_journal_consent_calendars(self, date):
        """The Senate Journal of `date` ("6/11/2026") and the consent calendars it says
        were voted that day, or (None, []) when the journal is not published."""
        day = dt.datetime.strptime(date, "%m/%d/%Y").date()
        for url in journal_urls(date):
            try:
                path, _ = self.urlretrieve(url)
            except scrapelib.HTTPError:
                continue
            try:
                with open(path, "rb") as f:
                    if f.read(4) != b"%PDF":
                        continue
                text = convert_pdf(path, "text").decode("utf-8", "replace")
            finally:
                os.remove(path)
            return url, consent_calendars(text, day)
        return None, []

    def post_to(self, url, vote):
        headers = {"votedate": vote}
        return self.post(url, data=headers).text

    def get_vote_dates(self, page, session):
        dates = url_xpath(page, "//select[@name='votedate']")[0].xpath("./*")
        return [a.text for a in dates if a.text.endswith(session[-2:])]

    def get_votes(self, url, session):
        ret = {}
        html = self.get(url).text
        p = lxml.html.fromstring(html)
        tables = p.xpath("//td[@background='/images/capBG.jpg']/div/table")

        metainf = tables[0]
        table = tables[1]

        inf = metainf.xpath("./tr/td/pre")[0]
        headers = [br.tail for br in inf.xpath("./*")]

        dateinf = metainf.xpath("./tr/td")[3]
        date = dateinf.text
        time = dateinf.xpath("./*")[0].tail

        vote_digest = metainf.xpath("./tr/td[@colspan='3']")
        digest = vote_digest[2].text_content()
        dig = []
        for d in digest.split("\n"):
            lis = d.strip().split("-")
            for li in lis:
                if li is not None and li != "":
                    dig.append(li.strip())
        digest = dig

        il = iter(digest)
        d = dict(zip(il, il))
        vote_count = d
        vote_count["passage"] = int(vote_count["YEAS"]) > int(vote_count["NAYS"])
        # XXX: This here has a greater then normal chance of failing.
        # However, it's an upstream issue.

        time_string = "%s %s" % (time, date)

        fmt_string = "%I:%M:%S %p %A, %B %d, %Y"
        # 4:31:14 PM TUESDAY, JANUARY 17, 2012
        date_time = dt.datetime.strptime(time_string, fmt_string)

        bill_s_n_no = r"(?P<year>[0-9]{2,4})(-?)(?P<chamber>[SH])\s*(?P<bill>[0-9]+)"
        # This is technically wrong, but it's close enough to be fine.
        # something like "123S  3023" is technically valid, even though it's
        # silly

        bill_metainf = None

        for h in headers:
            h = h.strip()
            inf = re.search(bill_s_n_no, h)
            if inf is not None:
                bill_metainf = inf.groupdict()
                if bill_metainf["year"][-2:] != session[-2:]:
                    self.warning(
                        "Skipping vote - it's in the %s session, we're in the %s session."
                        % (bill_metainf["year"][-2:], session[-2:])
                    )
                    return ret

        if bill_metainf is None:
            for h in headers:
                inf = YEARLESS_ITEM.match(h.strip())
                if inf is not None:
                    bill_metainf = inf.groupdict()
                    break

        if bill_metainf is None:
            # OPEN-711: a Senate consent roll call's whole header is "CONSENT
            # CALENDAR", "Consent #2" or "#2"
            lines = [h.strip() for h in headers if h.strip()]
            if len(lines) == 1 and CONSENT_HEADER.match(lines[0]):
                bill_metainf = {"chamber": None, "bill": "", "consent": lines[0]}

        if bill_metainf is None:
            self.warning("No metainf for this bill. Aborting snag")
            return ret

        motion = vote_motion(headers)
        bill_metainf["extra"] = {"motion": motion}

        votes = []

        for t in table.xpath("./tr/td"):
            nodes = t.xpath("./*")
            for node in nodes:
                if node.tag == "span":
                    vote = node.text.strip().upper()
                    name = node.tail.strip()
                    votes.append({"name": name, "vote": vote})
            if len(votes) > 0:
                bid = (bill_metainf["chamber"] or "") + bill_metainf["bill"]
                ret[bid] = {
                    "votes": votes,
                    "meta": bill_metainf,
                    "time": date_time,
                    "count": vote_count,
                    "source": url,
                }
        return ret

    def parse_vote_page(self, page, context_url, session):
        ret = []
        p = lxml.html.fromstring(page)
        votes = p.xpath("//center/div[@class='vote']")
        for vote in votes:
            votes = self.get_votes(
                context_url + "/" + vote.xpath("./a")[0].attrib["href"], session
            )
            ret.append(votes)
        return ret
