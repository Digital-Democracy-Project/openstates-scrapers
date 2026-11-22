"""OPEN-751: the measures of Hawaii's two-chamber special sessions, read from the legislature's own
PDFs on data.capitol.hawaii.gov.

A special session numbers its measures from 1 again, and the site's bill lists and measure pages
hold only the regular session's measures (asking for SB 1 of 2013 returns the regular SB 1), so
OPEN-748 left them out. They exist only as PDFs:

* the session's document folder (`/sessions/splsession<year><letter>/`) lists every measure's
  texts: `SB1_.pdf` as introduced, `SB1_HD1_.PDF` for each draft, `SB1_SSCR1_.pdf` for each
  standing committee report and `SB1_HD1_FA10_.PDF` for each floor amendment;
* each chamber's journal (`/sessions/journal/<House|Senate>/<year>/`) records what was done with
  each measure, day by day: who introduced or offered it, its title ("entitled: ..."), its
  readings, referrals and adoption, and its roll calls ("Ayes, 20. Noes, 4 (...)").

Only the four special sessions where both chambers sat are read (SOURCES); the other 23 were the
Senate alone confirming appointments, with no bills or resolutions of their own. Only bills,
resolutions and concurrent resolutions are read: the governor's and judiciary's messages
(nominations, GM and JC files) are not measures the scraper files under a bill.

What is read, and from where (all from the journals' own wording, never guessed):

* the measure's number, from its introduced text's file name in the folder;
* its title, from the journal's "entitled: "A BILL FOR AN ACT ...,"" text in its own chamber
  (the other chamber's journal next, for a measure its own chamber never titles);
* its sponsors, from "Introduced by:" (Senate bills, House bills) and "offered by" (resolutions);
* its versions, committee reports and floor amendments, from the folder;
* its actions: the journal sentences that state what was done with it (introduced and passed
  First Reading, referred, reported, passed Second, Third or Final Reading, agreed to amendments,
  adopted), dated by the journal day they are printed under;
* its roll calls: a motion on it to pass a reading or to adopt it, followed by the printed
  showing of ayes and noes. A tally whose counts and names do not agree is left out, with a
  warning. Roll calls on floor amendments and on procedural motions (recommit, postpone) are not
  the measure's own vote and are not read.

Left out because the journals do not print them in a form that can be read without guessing: the
House's committee referrals (printed as a referral sheet table that does not read in order) and the
governor's action (printed in later journals). See the OPEN-751 PR for the per-session results.
"""
import datetime as dt
import re
import subprocess
import tempfile

from lxml import etree

DATA = "https://data.capitol.hawaii.gov"

# the two-chamber special sessions (OPEN-748 entries in hi/__init__.py), with the folder of their
# documents and each chamber's journal, as data.capitol.hawaii.gov lists them (read 2026-11-21)
SOURCES = {
    "2013 Second Special Session": {
        "folder": "/sessions/splsession2013b/",
        "upper": [
            "/sessions/journal/Senate/2013/Senate_Journal_2013_2nd_Special_Session.pdf"
        ],
        "lower": ["/sessions/journal/House/2013/HJournal_Final_2SS_2013_Days_.pdf"],
    },
    "2016 Second Special Session": {
        "folder": "/sessions/splsession2016b/",
        "upper": [
            "/sessions/journal/Senate/2016/Senate_Journal_2016_2nd_Special_Session.pdf"
        ],
        "lower": [
            "/sessions/journal/House/2016/HJournal%20Final%202016%20Second%20Special%20Session.pdf"
        ],
    },
    "2017 Special Session": {
        "folder": "/sessions/splsession2017a/",
        "upper": [
            "/sessions/journal/Senate/2017/Senate_Journal_2017_1st_Special_Session.pdf"
        ],
        "lower": [
            "/sessions/journal/House/2017/2017%20HJournal%20Final%204%20Special%20Session.pdf"
        ],
    },
    "2021 Special Session": {
        "folder": "/sessions/splsession2021/",
        "upper": [
            "/sessions/journal/Senate/2021/Senate_Journal_2021_1st_Special_Session.pdf"
        ],
        "lower": [
            "/sessions/journal/House/2021/2021%20HJournal%20Final%206%20SS%202%20Days.pdf"
        ],
    },
}

# measure prefixes read, as the folder's file names and the journals write them
TYPES = {
    "HB": ("lower", "bill", "H.B."),
    "SB": ("upper", "bill", "S.B."),
    "HR": ("lower", "resolution", "H.R."),
    "SR": ("upper", "resolution", "S.R."),
    "HCR": ("lower", "concurrent resolution", "H.C.R."),
    "SCR": ("upper", "concurrent resolution", "S.C.R."),
}
CITATION = {v[2]: k for k, v in TYPES.items()}

FILE_RE = re.compile(
    r"^(?P<type>HCR|SCR|HB|SB|HR|SR)(?P<num>\d+)_(?P<rest>.*?)\.pdf$", re.IGNORECASE
)
DRAFT_RE = re.compile(
    r"^(?:(?:HD|SD|CD)\d+_)*(?P<draft>(?:HD|SD|CD)\d+)_$", re.IGNORECASE
)
FILE_REPORT_RE = re.compile(r"(?:^|_)(?P<chamber>H|S)SCR(?P<num>\d+)_$", re.IGNORECASE)
AMENDMENT_RE = re.compile(r"(?:^|_)FA(?P<num>\d+)_$", re.IGNORECASE)


def folder_measures(listing_html):
    """{("SB", "1"): {"introduced": url, "versions": [(name, url)], "documents": [(name, url)]}}
    from a document folder's listing. Only measures whose introduced text is in the folder are
    returned: a draft or report without it is not a measure of this session."""
    hrefs = re.findall(r'href="([^"]+)"', listing_html, flags=re.IGNORECASE)
    files = {}
    for href in hrefs:
        name = re.sub(r"(%20|\s)+", "", href.rsplit("/", 1)[-1])
        m = FILE_RE.match(name)
        if m:
            key = (m.group("type").upper(), m.group("num"))
            files.setdefault(key, []).append((m.group("rest"), DATA + href))
    measures = {}
    for key, entries in files.items():
        prefix = f"{key[0]}{key[1]}"
        found = {"introduced": None, "versions": [], "documents": []}
        # in the order of their numbers: HD1 before HD2, FA4 before FA10
        natural = [
            (re.sub(r"\d+", lambda d: d.group(0).zfill(4), r), r, u) for r, u in entries
        ]
        for _, rest, url in sorted(natural):
            if rest == "":
                found["introduced"] = url
            elif DRAFT_RE.match(rest):
                found["versions"].append(
                    (DRAFT_RE.match(rest).group("draft").upper(), url)
                )
            elif FILE_REPORT_RE.search(rest):
                r = FILE_REPORT_RE.search(rest)
                kind = {"H": "House", "S": "Senate"}[r.group("chamber").upper()]
                found["documents"].append(
                    (f"{kind} Standing Committee Report {r.group('num')}", url)
                )
            elif AMENDMENT_RE.search(rest):
                found["documents"].append(
                    (f"Floor Amendment {AMENDMENT_RE.search(rest).group('num')}", url)
                )
        if found["introduced"]:
            found["versions"].insert(0, (prefix, found["introduced"]))
            measures[key] = found
    return measures


def pdf_xml(path):
    """pdftohtml's word-position XML for a PDF file (images ignored, so nothing is written)."""
    return subprocess.run(
        ["pdftohtml", "-xml", "-stdout", "-i", "-q", path],
        capture_output=True,
        check=True,
    ).stdout


def pdf_bytes_xml(content):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(content)
        f.flush()
        return pdf_xml(f.name)


def _lines(runs):
    runs = sorted(runs, key=lambda r: (r[0], r[1]))
    lines, cur, top = [], [], None
    for r in runs:
        if top is None or abs(r[0] - top) > 3:
            if cur:
                lines.append(" ".join(x[2] for x in sorted(cur, key=lambda x: x[1])))
            cur, top = [], r[0]
        cur.append(r)
    if cur:
        lines.append(" ".join(x[2] for x in sorted(cur, key=lambda x: x[1])))
    return lines


def xml_pages(xml):
    """Each page of a journal as a list of text lines in reading order: a two-column page is read
    left column first, then right (pdftotext reads across both columns, mixing them)."""
    root = etree.fromstring(xml, etree.XMLParser(recover=True, huge_tree=True))
    pages = []
    for page in root.iter("page"):
        width = float(page.get("width"))
        runs = []
        for t in page.iter("text"):
            text = re.sub(r"\s+", " ", "".join(t.itertext())).strip()
            if text:
                runs.append(
                    (int(t.get("top")), int(t.get("left")), text, int(t.get("width")))
                )
        mid = width / 2
        wide = [r for r in runs if r[1] < mid - 20 and r[1] + r[3] > mid + 20]
        right = [r for r in runs if r[1] >= mid - 20]
        if len(wide) > len(right):
            pages.append(_lines(runs))
        else:
            left = [r for r in runs if r[1] < mid - 20]
            pages.append(_lines(left) + _lines(right))
    return pages


ORDINALS = [
    "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH",
    "TENTH", "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH", "FIFTEENTH",
]  # fmt: skip
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DAY_RE = re.compile(rf"^(?:{'|'.join(ORDINALS)}) DAY$")
DATE_RE = re.compile(
    rf"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), ((?:{MONTHS}) \d{{1,2}}, "
    r"\d{4})$"
)
# a sitting day's page header: "S E N A T E J O U R N A L - 1 s t D A Y - O C T O B E R 2 8,
# 2 0 1 3", "2 0 1 3 H O U S E J O U R N A L – S E C O N D S P E C I A L S E S S I O N – 1 S T
# D A Y", "2017 HOUSE JOURNAL – SPECIAL SE SSION – 5TH DAY" (squashed, spaces dropped). Other
# pages (contents, communications received after adjournment, committee reports, histories,
# rules) carry other headers and are not read.
HEADER_RE = re.compile(r"(SENATE|HOUSE)JOURNAL")
DAY_HEADER_RE = re.compile(r"\d(?:st|nd|rd|th)DAY(?:$|[-–])", re.IGNORECASE)


def journal_days(pages):
    """[(date, text)] for each sitting day of a journal, its lines joined in reading order with
    page headers and page numbers dropped. A day runs from its "<ORDINAL> DAY" / "<weekday>,
    <date>" heading to the next one (the page headers are not used for the date: some print the
    wrong day, for example every even page of the 2021 House journal's second day says 1ST DAY)."""
    days = []
    for lines in pages:
        headers = [line for line in lines if HEADER_RE.search(re.sub(r"\s+", "", line))]
        if not any(DAY_HEADER_RE.search(re.sub(r"\s+", "", h)) for h in headers):
            continue
        for i, line in enumerate(lines):
            line = line.strip()
            if line in headers or re.fullmatch(r"[\d ]{1,5}|[ivx]+", line):
                continue  # a page header or page number
            date = DATE_RE.match(lines[i + 1].strip()) if i + 1 < len(lines) else None
            if DAY_RE.match(line) and date:
                days.append(
                    (dt.datetime.strptime(date.group(1), "%B %d, %Y").date(), [])
                )
            if days:
                days[-1][1].append(line)
    return [(date, _join(lines)) for date, lines in days]


def _join(lines):
    text = ""
    for line in lines:
        line = line.strip()
        if text.endswith("-") and not text.endswith(" -"):
            text += line
        else:
            text += (" " if text else "") + line
    return re.sub(r"[“”]", '"', text).replace("’", "'")


# ---- what the journal says was done with each measure ----------------------------------------

CIT = r"(?P<cit>H\.C\.R\.|S\.C\.R\.|H\.B\.|S\.B\.|H\.R\.|S\.R\.) No\.? (?P<num>\d+)"
# "S.B. No. 1, H.D. 1", "S.B. No. 1, HD 1", "S.B. No. 1 (H.D. 1)", "H.B. No. 3, as amended in HD 1"
DRAFTS = r"(?:,? (?:as amended in )?(?:[HSC]\.? ?D\.? \d+)|,? \([HSC]\.? ?D\.? \d+\))*"
ENTITLED = r'(?:,? entitled[:,]? "(?P<title>[^"]+?),?",?)?'
FILLER = r"(?: having been read throughout,?(?: and Roll Call vote having been requested,?)?)?"
OUTCOME_RE = re.compile(
    CIT
    + DRAFTS
    + ENTITLED
    + FILLER
    + r" (?P<outcome>passed (?P<reading>First|Second|Third|Final) Reading"
    r"(?! in the (?:House|Senate))|was adopted|was not adopted|was laid on the table"
    r"|failed to pass (?P<failed>Second|Third|Final) Reading)"
)
# the House's roll calls are written as the motion: "Roll call having been approved, the motion
# that S.B. No. 1, HD 1, entitled: "...," pass Third Reading, was put to vote by the Chair and
# carried, on the following show of ayes and noes:"
MOTION_RE = re.compile(
    r"the motion that "
    + CIT
    + DRAFTS
    + ENTITLED
    + r" (?P<outcome>pass (?P<reading>Second|Third|Final) Reading|be adopted)[^.]*?, was put "
    r"to vote by the Chair,? and (?:on the following show of ayes and noes, )?"
    r"(?P<result>carried|failed)(?: to carry)?"
)
SHOWING_RE = re.compile(
    r"^(?:[^.]*?on the following show(?:ing)? of ayes and noes)?:\s*", re.I
)
# Senate: "Ayes, 20. Noes, 4 (Gabbard, Kim, Kouchi, Slom). Excused, 1 (Wakai)."
SENATE_TALLY_RE = re.compile(
    r"^Ayes, (?P<yes>\d+|none)(?:; Ayes with Reservations \((?P<resv_names>[^)]*)\))?\.\s*"
    r"Noes,? (?P<no>\d+|none)(?: \((?P<no_names>[^)]*)\))?\."
    r"(?:\s*Excused, (?P<excused>\d+|none)(?: \((?P<excused_names>[^)]*)\))?\.)?"
)
# House: "Ayes, 30: Belatti, ..., Wooley and Yamashita. Noes, 19: Aquino, .... Excused, 2:
# Cabanilla and Choy."
HOUSE_TALLY_RE = re.compile(
    r"^Ayes, (?P<yes>\d+|none)(?:: (?P<yes_names>[^.]*))?\.\s*Noes, (?P<no>\d+|none)"
    r"(?:: (?P<no_names>[^.]*))?\.(?:\s*Excused, (?P<excused>\d+|none)(?:: (?P<excused_names>"
    r"[^.]*))?\.)?"
)
# "passed Third Reading by a vote of 47 ayes, with Representatives Choy, Nakashima, Say and
# Yamane being excused." / "by a vote of 31 ayes to 15 noes, with Representatives ... voting aye
# with reservations, with Representatives ... voting no, and with Representatives ... being
# excused."
HOUSE_COUNT_RE = re.compile(
    r"^ by a vote of (?P<yes>\d+) ayes(?: to (?P<no>\d+) noes)?(?P<rest>[^.]*)\."
)
NAMED_RE = re.compile(
    r"^Representatives? (?P<names>.+?) (?P<how>voting aye with reservations|voting no|being excused)$"
)
REFERRAL_RE = re.compile(
    r"^ by title(?:,)? and (?:was )?referred (?P<joint>jointly )?to (?P<committees>(?:the )?"
    r"Committee on .+?)(?=,? with |\.|$)"
)
INTRO_RE = re.compile(
    r"(?P<lead>(?:H\.C\.R\.|S\.C\.R\.|H\.B\.|S\.B\.|H\.R\.|S\.R\.) No\.|\d+) ?(?P<num>(?<=No\.) \d+)?"
    r':? "(?P<title>[^"]+?)\.?"(?: THE)? (?P<how>Introduced|Offered) by: (?P<sponsors>[^.]*?(?:, by request)?)\.'
)
# the Senate's intro block names the committees until the next measure or heading: "Referred to:
# Committee on Ways and Means S.B. No. 2 ...", "Referred to: Jointly to the Committee on Labor and
# the Committee on Ways and Means The Chair then ..."
REFERRED_TO_RE = re.compile(
    r"\s*Referred to: (?P<c>(?:Jointly to )?(?:the )?Committee on [A-Za-z ,&']+?)"
    r"(?= [A-Z]\.| [A-Z]{2,}| The | At | On |\.|$)"
)
# every "S.B. No. 1, HD 1, entitled: "A BILL FOR AN ACT RELATING TO EQUAL RIGHTS,"" gives the title
TITLE_RE = re.compile(CIT + DRAFTS + r',? entitled[:,]? "(?P<title>[^"]+?),?"')
# the House's resolutions: "H.R. No. 1, entitled: "...," resolving that ..., was offered by
# Representative Evans." (the summary between the title and "was offered" can be long)
OFFERED_RE = re.compile(
    r"was (?:jointly )?offered by (?P<sponsors>Representatives? [^.]+?)\."
)
# "the following Senate Bills passed First Reading by title and further action was deferred:
# (Representatives ... were excused.) S.B. No. 2 S.B. No. 3 S.B. No. 4"
FIRST_READING_LIST_RE = re.compile(
    r"the following (?:Senate|House) Bills? passed First Reading by title(?P<how>[^:]*): "
    r"(?:\([^)]*\) )?(?P<list>(?:(?:H|S)\.B\. No\. \d+(?:, [HSC]D \d+)* ?)+)"
)
RECEIVED_RE = re.compile(
    r"(?P<from>Hse|Sen)\. Com\. No\. (?P<com>\d+), transmitting " + CIT
)
AGREED_RE = re.compile(r"agreed to the amendments proposed by the House to " + CIT)
REPORT_RE = re.compile(
    r"presented a report \(Stand\. Com\. Rep\. No\. (?P<rep>\d+)\) recommending that "
    + CIT
    + DRAFTS
    + r",? (?P<rec>pass (?:Second|Third) Reading|be adopted)"
)
TITLE_PREFIX_RE = re.compile(
    r"^(?:A BILL FOR AN ACT|(?:HOUSE|SENATE)(?: CONCURRENT)? RESOLUTION) ",
    re.IGNORECASE,
)
NAMES_SPLIT_RE = re.compile(r",\s*(?:and\s+)?|\s+and\s+")


def _clean_title(title):
    title = re.sub(r"\s+", " ", title).strip().rstrip(",")
    title = TITLE_PREFIX_RE.sub("", title)
    return title if title.endswith(".") else title + "."


def _names(text):
    if not text:
        return []
    text = re.sub(r"^(?:Senators?|Representatives?) ", "", text.strip())
    return [n.strip() for n in NAMES_SPLIT_RE.split(text) if n.strip()]


def _count(value):
    return 0 if value in (None, "none") else int(value)


def _tally(chamber, text):
    """The roll call printed at the start of `text` as {"yes": n, "no": n, "excused": n, "voters":
    [(option, name)]}, or None when it is not there or its counts and names disagree."""
    m = (SENATE_TALLY_RE if chamber == "upper" else HOUSE_TALLY_RE).match(text)
    if not m:
        return None
    counts = {k: _count(m.group(k)) for k in ("yes", "no", "excused")}
    voters = []
    for option, key in (("yes", "yes"), ("no", "no"), ("not voting", "excused")):
        group = key + "_names"
        names = _names(m.groupdict().get(group))
        if group in m.groupdict() and (names or counts[key]):
            if chamber == "lower" or key != "yes":
                if len(names) != counts[key]:
                    return None
        voters.extend((option, n) for n in names)
    # "Ayes, 20; Ayes with Reservations (Thielen)": the 20 count those with reservations
    voters.extend(("yes", n) for n in _names(m.groupdict().get("resv_names")))
    counts["voters"] = voters
    return counts


def _house_count(text):
    """The House's counted vote at the start of `text` ("by a vote of 44 ayes, with
    Representatives ... being excused"), None when there is none, "unreadable" when a clause
    naming members cannot be read or the names do not match the printed noes."""
    c = HOUSE_COUNT_RE.match(text)
    if not c:
        return None
    vote = {"yes": int(c.group("yes")), "no": 0, "excused": 0, "voters": []}
    for clause in re.split(r",? (?:and )?with (?=Representatives? )", c.group("rest"))[
        1:
    ]:
        n = NAMED_RE.match(clause.strip())
        if not n:
            return "unreadable"
        names = _names(n.group("names"))
        option = {"voting aye with reservations": "yes", "voting no": "no"}.get(
            n.group("how"), "not voting"
        )
        vote["voters"].extend((option, x) for x in names)
        if option == "no":
            vote["no"] += len(names)
        elif option == "not voting":
            vote["excused"] += len(names)
    if c.group("rest").strip() and not c.group("rest").startswith(","):
        return "unreadable"
    if c.group("no") is not None and int(c.group("no")) != vote["no"]:
        return "unreadable"
    return vote


def measure_events(days, chamber, wanted):
    """What the journal of `chamber` ("upper"/"lower"), as journal_days() returns it, says was done
    with each measure in `wanted` (a set of keys like ("SB", "1")): {key: {"titles": [...],
    "sponsors": [...], "actions": [...], "votes": [...]}}. Every entry comes from one journal
    sentence; anything the patterns do not recognize is not recorded."""
    found = {
        key: {"titles": [], "sponsors": [], "actions": [], "votes": []}
        for key in wanted
    }

    def key_of(m):
        return (CITATION[m.group("cit")], m.group("num"))

    def action(key, date, description, classification, at):
        if key in found:
            found[key]["actions"].append(
                (at, date, chamber, description, classification)
            )

    for date, text in days:
        # introductions with their sponsors: the Senate's "S.B. No. 1 "A BILL ..." Introduced by:
        # Senator Galuteria. Referred to: Committee on ...", the House's "H. B. Nos." list of
        # numbers with titles and introducers, and "Offered by:" resolutions
        for m in INTRO_RE.finditer(text):
            if m.group("num"):
                key = (CITATION[m.group("lead")[:-4]], m.group("num").strip())
            else:
                # a House list entry: the type is the list's "H. B. Nos." heading before it
                heading = list(
                    re.finditer(r"([HS])\. ?(B|R|C\. ?R)\. Nos\.", text[: m.start()])
                )
                if not heading:
                    continue
                h = heading[-1]
                key = (
                    h.group(1) + h.group(2).replace(".", "").replace(" ", ""),
                    m.group("lead"),
                )
            if key not in found:
                continue
            found[key]["titles"].append((chamber, _clean_title(m.group("title"))))
            found[key]["sponsors"].extend(
                _names(m.group("sponsors").replace(", by request", ""))
            )
            how = "Introduced" if m.group("how") == "Introduced" else "Offered"
            if how == "Introduced":
                # the list follows the motion it answers: "the following bill passed First
                # Reading by title" (Senate), "the following bills (H.B. Nos. 6 through 12)
                # passed First Reading by title", or "moved that the following bills ... pass
                # First Reading by title", carried later that day ("the noted bills passed First
                # Reading by title")
                lead = list(
                    re.finditer(r"the following bills?\b[^:]*:", text[: m.start()])
                )
                lead = lead[-1].group(0) if lead else ""
                if "passed First Reading by title" in lead or (
                    "pass First Reading by title" in lead
                    and "the noted bills passed First Reading by title" in text
                ):
                    first = ["introduction", "reading-1"]
                    action(
                        key,
                        date,
                        "Introduced and Passed First Reading",
                        first,
                        m.start(),
                    )
                else:
                    action(key, date, "Introduced", "introduction", m.start())
                ref = REFERRED_TO_RE.match(text[m.end() :])
                if ref:
                    committees = re.sub(
                        r"^Jointly to ", "jointly to ", ref.group("c").strip()
                    )
                    if not committees.startswith("jointly"):
                        committees = "to " + committees
                    referred = f"Referred {committees}"
                    action(key, date, referred, "referral-committee", m.start() + 1)
            else:
                action(key, date, "Offered", "introduction", m.start())
        titled = list(TITLE_RE.finditer(text))
        for i, m in enumerate(titled):
            key = key_of(m)
            if key not in found:
                continue
            found[key]["titles"].append((chamber, _clean_title(m.group("title"))))
            # a House resolution's "was offered by", before the next titled measure
            end = titled[i + 1].start() if i + 1 < len(titled) else len(text)
            offered = OFFERED_RE.search(text, m.end(), min(end, m.end() + 3000))
            if offered and TYPES[key[0]][1] != "bill":
                found[key]["sponsors"].extend(_names(offered.group("sponsors")))
                action(key, date, "Offered", "introduction", m.start())
        for m in FIRST_READING_LIST_RE.finditer(text):
            for c in re.finditer(CIT, m.group("list")):
                action(key_of(c), date, "Passed First Reading", "reading-1", m.start())
        for m in RECEIVED_RE.finditer(text):
            # the other chamber sending one of its measures over; a message about one of this
            # chamber's own measures reports the other chamber's action, which its own journal
            # records
            if (
                TYPES[key_of(m)[0]][0] != chamber
                and TYPES[key_of(m)[0]][1] != "resolution"
            ):
                other = "House" if m.group("from") == "Hse" else "Senate"
                action(
                    key_of(m), date, f"Received from {other}", "introduction", m.start()
                )
        for m in REPORT_RE.finditer(text):
            rec = m.group("rec").replace("pass", "PASS", 1)
            report = f"Stand. Com. Rep. No. {m.group('rep')} recommends that the measure {rec}"
            action(key_of(m), date, report, "committee-passage-favorable", m.start())
        for m in AGREED_RE.finditer(text):
            action(
                key_of(m), date, "Agreed to House amendments", "concurrence", m.start()
            )

        for m in list(OUTCOME_RE.finditer(text)) + list(MOTION_RE.finditer(text)):
            key = key_of(m)
            if key not in found:
                continue
            if m.group("title"):
                found[key]["titles"].append((chamber, _clean_title(m.group("title"))))
            outcome = m.group("outcome")
            rest = text[m.end() :]
            is_motion = outcome.startswith(("pass ", "be "))
            reading = m.group("reading")
            if is_motion:
                failed = m.group("result") == "failed"
                description = (
                    ("Failed to pass" if failed else "Passed") + f" {reading} Reading"
                    if reading
                    else ("Failed adoption" if failed else "Adopted")
                )
            elif outcome.startswith("failed"):
                reading = m.group("failed")
                description = f"Failed to pass {reading} Reading"
            elif outcome == "was not adopted":
                description = "Failed adoption"
            elif outcome == "was laid on the table":
                description = "Laid on the table"
            else:
                description = f"Passed {reading} Reading" if reading else "Adopted"
            classification = {
                "First": "reading-1",
                "Second": "reading-2",
                "Third": "passage",
                "Final": "passage",
                None: "passage",
            }[reading]
            if description.startswith("Failed"):
                classification = "failure"
            elif description == "Laid on the table":
                classification = None
            ref = REFERRAL_RE.match(rest) if reading == "First" else None
            if ref:
                description += (
                    f"; referred {ref.group('joint') or ''}to {ref.group('committees')}"
                )
                classification = ["reading-1", "referral-committee"]
            action(key, date, description, classification, m.start())

            vote = None
            showing = SHOWING_RE.match(rest[:400])
            if showing:
                vote = _tally(chamber, rest[showing.end() :])
            elif chamber == "lower" and not is_motion:
                vote = _house_count(rest)
            if showing and vote is None:
                vote = "unreadable"
            if vote:
                found[key]["votes"].append(
                    (m.start(), date, chamber, description, vote)
                )
    for entry in found.values():
        entry["actions"] = [
            a[1:] for a in sorted(entry["actions"], key=lambda a: (a[1], a[0]))
        ]
        entry["votes"] = [
            v[1:] for v in sorted(entry["votes"], key=lambda v: (v[1], v[0]))
        ]
    return found
