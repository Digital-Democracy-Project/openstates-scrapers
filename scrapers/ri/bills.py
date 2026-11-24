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
from utils import presiding_officers, url_xpath

subjects = None
bill_subjects = None

# What a silly low number. This is just putting more load on the
# server, not even helping with that. Sheesh.
MAXQUERY = 250
RI_URL_BASE = "https://webserver.rilegislature.gov"

# OPEN-785: the vote reports print each chamber's presiding officer by title ("Mr. Speaker",
# "Madam President"); who that is comes from the manifest (utils/presiding_officers.py)
PRESIDING_OFFICERS = {
    "Mr. Speaker": ("lower", "house_speaker_by_session"),
    "Madam Speaker": ("lower", "house_speaker_by_session"),
    "Mr. President": ("upper", "senate_president_by_session"),
    "Madam President": ("upper", "senate_president_by_session"),
}


def add_voter(vote, option, name, chamber, session, day):
    """Record `name`'s vote; a presiding-officer title gets the officer in office on `day`
    ('YYYY-MM-DD'). Returns the manifest field with no name for it, else None."""
    return presiding_officers.add_voter(
        vote, option, name, chamber, session, "ri", PRESIDING_OFFICERS, day
    )


# OPEN-683: a roll call's header ends with the motion, one to three lines under the
# bill's title: House "PASSAGE" / "AS AMENDED" / "PASSAGE OF AMENDMENT", Senate
# "Approval of Amendment" / "Passage" ("In Concurrence / Passage" and "Approval of
# Amendment / Passage" are both seen). These are the lines the motion is made of.
MOTION_LINE = re.compile(
    r"^(passage( as amended)?|as amended|in concurrence|(passage|approval) of amendment"
    r"|reconsider(ation)?|ruling of the chair)$",
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
# OPEN-873: a bill number printed in a form the two patterns above do not read, only
# tried when they find nothing. The Senate prints the budget as "House Bill No. 7127  SUB A aa"
# and "BUDGET H-7127 SUB A AA", a bill "SENATE BILL - S 2045 sub a", "REP NAME      H 7165",
# "2025   H-5477" or "HOUSE BILL 2026 H-8611", and a bill filed by a member "SEN NAME   No. 2067"
# (or "REP NAME  HOUSE No. 5146"). The chamber is the letter (or the word) before the number.
PRINTED_BILL = [
    re.compile(
        r"(?:^|[\s-])(?:(?P<year>(?:20)?\d\d)[\s-]*)?(?P<chamber>[SH])[\s-]+(?P<bill>[1-9][0-9]*)\b"
    ),
    re.compile(
        r"\b(?P<chamber>House|Senate)\s+(?:Bill\s+(?:No\.?\s*)?|No\.?\s*)(?P<bill>[1-9][0-9]*)\b",
        re.I,
    ),
    re.compile(r"^(?P<chamber>SEN|REP)\b.*\bNo\.?\s*(?P<bill>[1-9][0-9]*)\b", re.I),
]
# a calendar item's header is its marker, the item and the bill's title, with no motion
# line when the item is simply read and passed (OPEN-873)
CALENDAR_MARKER = re.compile(r"^(calendar|immediate consideration)$", re.I)
ITEM_LINE = re.compile(r"^ITEM\b", re.I)


def printed_bill(headers):
    """The bill a header prints in one of the PRINTED_BILL forms, as {"year", "chamber"
    ("S" or "H"), "bill"}, else None. The first form that finds a bill decides; if it
    finds two different bills in the header, the header is ambiguous and reads as none."""
    for pattern in PRINTED_BILL:
        found = []
        for h in headers:
            m = pattern.search(h.strip())
            if m:
                found.append(m.groupdict())
        for f in found:
            f.setdefault("year", None)
            f["chamber"] = f["chamber"][0].upper()
        if len({(f["chamber"], f["bill"]) for f in found}) == 1:
            return found[0]
        if found:
            return None
    return None


def vote_motion(headers):
    """The motion of a roll call from its header lines: the motion lines at the end
    joined with " / " ("PASSAGE / AS AMENDED"), else the last line as before (a
    header with no motion line, such as a point of order, ends in the title). A
    budget article's vote keeps its article ("ARTICLE 2 PASSAGE"): it cannot pass
    or kill the whole bill. OPEN-873: a calendar item with no motion line at all
    ("CALENDAR", "ITEM 59  2026-S 3315", title) is the item read and passed, so its
    motion is the marker ("CALENDAR", "IMMEDIATE CONSIDERATION"), not a title line."""
    lines = [h.strip() for h in headers if h.strip()]
    motion = []
    while lines and MOTION_LINE.match(lines[-1]):
        motion.insert(0, lines.pop())
    if motion:
        motion = " / ".join(motion)
    elif (
        lines
        and CALENDAR_MARKER.match(lines[0])
        and any(ITEM_LINE.match(h) for h in lines)
    ):
        motion = lines[0]
    else:
        motion = headers[-1].strip() if headers else ""
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

# OPEN-784: the search page links only a bill's current text, named by its number ("7603",
# "7532  SUB B as amended"), a name with no stage. The legislature's text index for each
# chamber and year (BillText26/HouseText26/HouseText26.html) lists every text of every bill,
# in the order they were printed (H7532, H7532A, H7532Aaa, H7532B, H7532Baa), and each text's
# own header names it by its file's ending: none (the introduced text), "aa" AS AMENDED, "A"
# SUBSTITUTE A, "Aaa" SUBSTITUTE A AS AMENDED (read 2026-11-23).
TEXT_FILE = re.compile(r"\A(?P<bill>[HS]\d+)(?P<sub>[A-Z])?(?P<amended>aa)?\Z")


def text_name(text):
    """A text's name from its file name (TEXT_FILE match): "Introduced", "As Amended",
    "Substitute A", "Substitute A As Amended"."""
    sub, amended = text.group("sub"), text.group("amended")
    if not sub and not amended:
        return "Introduced"
    name = f"Substitute {sub}" if sub else ""
    return f"{name} As Amended".strip() if amended else name


class RIBillScraper(Scraper):
    # when scraping votes we only get 'S101' so we can't tie them to their parent bill
    # so we keep a dict of (chamber, number) -> bill_id from the bill scrape to be used in the
    # vote scrape
    _bill_id_by_type = {}
    # OPEN-784: text index URL -> {bill: [TEXT_FILE matches, oldest first]}, new each run
    _text_index = {}
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

    def bill_texts(self, url):
        """OPEN-784: (name, url) of each text of the bill whose current text is `url`, oldest
        first: the texts its chamber's text index lists, up to and including the current one.
        A text printed after the current one is left out (S2048's index lists a Substitute A
        after the "as amended" text the status page shows as current: 1 of 3,011 bills in
        2026; the other 3,010 end on their current text). Just the current text if the index
        can't be read or does not list it; None if `url` is not a text file of this shape."""
        folder, _, filename = url.rpartition("/")
        stem, _, ext = filename.rpartition(".")
        current = TEXT_FILE.match(stem) if ext.lower() == "pdf" else None
        if not current:
            return None
        index_url = f"{folder}/{folder.rpartition('/')[2]}.html"
        if index_url not in self._text_index:
            try:
                page = lxml.html.fromstring(self.get(index_url).text)
                names = page.xpath("//td[@class='bill_col1']/text()")
            except (scrapelib.HTTPError, lxml.etree.ParserError):
                self.warning(f"text index {index_url} unreadable: current texts only")
                names = []
            by_bill = {}
            for text in filter(None, (TEXT_FILE.match(n.strip()) for n in names)):
                by_bill.setdefault(text.group("bill"), []).append(text)
            self._text_index[index_url] = by_bill
        texts = self._text_index[index_url].get(current.group("bill"), [])
        files = [t.group(0) for t in texts]
        if current.group(0) in files:
            texts = texts[: files.index(current.group(0)) + 1]
        else:
            texts = [current]
        return [(text_name(t), f"{folder}/{t.group(0)}.pdf") for t in texts]

    def scrape_bills(self, chamber, session, subjects):
        idexes = bill_start_numbers(session)[chamber]
        FROM = "ctl00$rilinContent$txtBillFrom"
        TO = "ctl00$rilinContent$txtBillTo"
        YEAR = "ctl00$rilinContent$cbYear"
        for idex in idexes:
            blocks = "FOO"  # Ugh.
            while len(blocks) > 0:
                # OPEN-771: the search includes both ends ("8250 to 8500" lists 251
                # bills), so each range stops one short of the next one's start;
                # otherwise every boundary bill (HB 8500) is yielded twice and the
                # import stops on it
                last = idex + MAXQUERY - 1
                self.info(f"Searching for bills in {chamber} in range {idex} to {last}")
                default_headers = get_default_headers(SEARCH_URL)
                default_headers[FROM] = idex
                default_headers[TO] = last
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
                        url = href.attrib["href"]
                        texts = self.bill_texts(url) or [(href.text, url)]
                        for name, text_url in texts:
                            b.add_version_link(
                                name, text_url, media_type="application/pdf"
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
        self._text_index = {}

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

        day = vote["time"].date().isoformat()
        # (manifest field, session) pairs already warned about in this run, one warning each
        warned = self.__dict__.setdefault("_warned_officers", set())
        for vt in vote["votes"]:
            key = {"Y": "yes", "N": "no"}.get(vt["vote"], "other")
            unnamed = add_voter(v, key, vt["name"], chamber, session, day)
            if unnamed and (unnamed, session) not in warned:
                warned.add((unnamed, session))
                self.warning(
                    "OPEN-785: manifest ri.votes.%s has no %s on %s; %r left as printed",
                    unnamed,
                    session,
                    day,
                    vt["name"],
                )
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
            bill_metainf = printed_bill(headers)
            if bill_metainf is not None and bill_metainf["year"]:
                if bill_metainf["year"][-2:] != session[-2:]:
                    self.warning(
                        "Skipping vote - it's in the %s session, we're in the %s session."
                        % (bill_metainf["year"][-2:], session[-2:])
                    )
                    return ret

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
