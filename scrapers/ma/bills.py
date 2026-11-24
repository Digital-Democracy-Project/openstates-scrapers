import re
import requests
from utils import checked_requests

import os
import json
import zlib
from datetime import datetime
import lxml.html
from openstates.exceptions import EmptyScrape
from openstates.scrape import Scraper, Bill, VoteEvent
from classify_motion import classify_motion
from openstates.utils import convert_pdf
from openstates.utils.transformers import fix_bill_id

from . import catchup
from .actions import Categorizer
from .voter_names import SPEAKER_TITLE, senate_voter_name
from .votes import (
    JOURNAL_MONTH_URL,
    JOURNAL_PDF_LINKS,
    HouseVoteRecordParser,
    journal_date,
    vote_result,
)

try:
    # DDP's openstates-core fork at or after OPEN-517 (what the scraper image is built with). Upstream's
    # openstates package has no version_ordering, and an older fork has no non_bill_kind; without it every
    # paper is yielded as an ordinary bill, as before OPEN-508 (and the scraper says so once). Only those
    # names being absent is forgiven: any other import failure is a real defect and stays loud.
    from openstates.utils.version_ordering import (
        NON_BILL_AMENDMENT,
        ORIGINAL_CLASSIFICATION_KEY,
        non_bill_kind,
    )
except ImportError as exc:
    if exc.name not in ("openstates.utils.version_ordering", "openstates.utils"):
        raise
    NON_BILL_AMENDMENT = ORIGINAL_CLASSIFICATION_KEY = non_bill_kind = None

# OPEN-509: an amendment paper is saved with the label "amendment" only when openstates-core accepts it as a bill
# label (the core change that adds it); with an older core it stays an ordinary bill, as before, rather than failing
# the import's schema check.
from openstates.data.common import BILL_CLASSIFICATIONS  # noqa: E402

AMENDMENT_LABEL_OK = (
    bool(NON_BILL_AMENDMENT) and NON_BILL_AMENDMENT in BILL_CLASSIFICATIONS
)


requests.packages.urllib3.disable_warnings()


# OPEN-176: a Senate roll call's PDF is named after the roll-call number the
# action text itself cites, and that is the ONLY reliable way to find it.
#
# The scraper used to take `td[3]/a/@href` -- the first link in the action cell --
# and treat it as the roll-call PDF. That cell carries several unrelated kinds of
# link (Chapter-of-the-Acts text, cross-references to another bill number, and an
# amendment's own content page), so the first one is frequently not the roll call.
# Measured across MA 194th: of 118 Senate vote events that imported with a real
# tally and zero voters, 115 had been pointed at
# `/Bills/GetAmendmentContent/.../Preview` -- an 818-byte HTML modal, not a PDF.
# `convert_pdf` on that HTML fails with "Couldn't find trailer dictionary", which
# is why OPEN-176 was first filed as a malformed-PDF problem. The file is not a
# malformed PDF; it was never a PDF.
#
# Deriving the URL from the cited number instead is not a guess -- it is the rule
# the working data already follows, checked in both directions:
#
#   * All 110 Senate vote events that DID import voters cite a `Roll Call #<n>`
#     whose number equals the number in the URL that worked. 110 of 110, so
#     reconstruction reproduces every URL that currently succeeds.
#   * Of the 236 roll-call actions in the 194th, 2 are quorum calls (excluded
#     below) and all 234 that would produce a vote carry a `Roll Call #<n>` in
#     their own text -- so the number is always available where it is read, and
#     no same-date sibling lookup is needed.
#
# Note the number is not always written tight against the "#": S 2710 reads
# `Roll Call # 97`, which is why `#\s*` is not `#`.
#
# An action can in principle name a roll call in EACH chamber. The docstring of
# the Senate branch below already cites the shape, from 2019 H86:
#
#     Ordered to a third reading -- see Senate   Roll Call #25 and House Roll Call 56
#
# Taking the first number there would build a *Senate* URL out of a *House*
# roll-call number -- a URL that resolves, returns a real PDF, and attaches the
# wrong chamber's voters to the vote. That is the same silent-wrong-source class
# OPEN-176 exists to remove, so it is guarded rather than left to chance even
# though no such action exists in the data today: across all 236 Massachusetts
# roll-call actions we hold, none cites more than one number and none uses the
# chamber-qualified wording at all.
_SENATE_ROLLCALL_URL = "http://malegislature.gov/RollCall/{}/SenateRollCall{}.pdf"

# OPEN-443: each House roll call also has its own sheet, in the same layout as the
# House journal's year PDF. The year PDF is rebuilt only now and then (the 2026 one
# was last built on 2026-07-27 and stops at No. 236, without No. 233), so the roll
# calls after it are read from here instead. House roll-call numbers run on across
# the whole session, so one number names one sheet.
_HOUSE_ROLLCALL_URL = "https://malegislature.gov/RollCall/{}/HouseRollCall{}.pdf"
_ROLLCALL_NUMBER_RE = re.compile(r"Roll\s+Call\s+#\s*(\d+)", re.I)
_SENATE_ROLLCALL_MENTION_RE = re.compile(r"Senate\s+Roll\s+Call\s+#?\s*(\d+)", re.I)
_HOUSE_ROLLCALL_MENTION_RE = re.compile(r"House\s+Roll\s+Call\s+#?\s*(\d+)", re.I)

# OPEN-177: Massachusetts writes the nay count three different ways, and the
# scraper only accepted one of them.
#
# The gate used to require the literal substring "nays", so an action reading
# "(Yeas 39 to Nay 0)" created no vote event at all -- not a tally-only vote, no
# vote. Across MA 194th's 236 roll-call actions, 230 match the old condition and
# 6 do not: 3 use the singular "Nay", 1 is a source-side typo that writes the nay
# count as "Yeas" ("Yeas 39 to Yeas 0", S 2565), and 2 are quorum roll calls
# handled separately below. Those 4 are 4 of the 6 bills in OPEN-177 that cite a
# Senate roll call while holding no Senate vote.
#
# The second pattern accepts "Yeas" in the nay position deliberately. It is a
# transcription error on the legislature's side, and the alternative -- dropping
# the vote -- loses a real 39-0 roll call whose PDF is available and readable.
# The count is recorded from the text, as it always was; the voters come from the
# PDF, which is authoritative either way.
_SENATE_TALLY_RES = (
    # "39 yeas ... 0 nays" -- the older form, e.g. 2019 H86.
    re.compile(r"(\d+)\s+yeas\b.*?(\d+)\s+nays\b", re.I),
    # "Yeas 39 to Nays 0" / "Yeas 39 to Nay 0" / "Yeas 39 to Yeas 0".
    # The second label is captured, not discarded, so the caller can tell a
    # tally that Massachusetts labelled correctly from one it mislabelled.
    re.compile(r"\byeas?\s+(\d+)\s+to\s+(nays?|yeas?)\s+(\d+)", re.I),
)

# A quorum roll call establishes that enough members are present. It is not a
# vote on the bill, and the two in MA 194th ("Quorum Roll Call - 149 YEAS to 0
# NAYS (See YEA and NAY No. 249 )") are House counts that were minting Senate
# vote events -- they are the 2 remaining Senate events whose source URL points
# at a *House* roll-call PDF.
#
# OPEN-567: the same two lines also carry "YEA and NAY", so the House branch
# stored them as House votes (No. 249 on H 5620, No. 154 on S 2581), shown on the
# site as unanimous "yes" votes on those bills. Neither branch records one now.
_QUORUM_RE = re.compile(r"Quorum\s+Roll\s+Call", re.I)


# A bill-history link to another bill's page, e.g. /Bills/194/S2957.
_BILL_HREF_RE = re.compile(r"^/Bills/\d+/([A-Za-z]+\d+)/?$")
# OPEN-645 (PLAN-companion-lineage §5.3): a bill page's "Similar Bills" tab lists bills of this and earlier sessions as
# links "/Bills/<session number>/<bill>". The legislature calls them similar, not companions, so they are `related`
# (Ramon's D1 counts only "Identical"), labelled with its own words.
_SIMILAR_HREF_RE = re.compile(r"^/Bills/(\d+)/([A-Za-z]+\d+)/?$")
MA_SIMILAR_LABEL = "Similar Bills"

# OPEN-512: the action by which a chamber adopted a draft as the bill's text, read from the draft's own history:
# "Substituted, as amended for H4010", "Substituted as a new text for H4282", "Substituted for S2726".
_SUBSTITUTED_FOR_RE = re.compile(r"\bSubstituted\b.*?\bfor\s+([HS])\.?\s*(\d+)\b", re.I)


# The h1 of a page whose title is missing: "Bill S.757", "Bill SD.3528". A number, not a title.
_BILL_PLACEHOLDER_H1_RE = re.compile(r"\s*Bill\s+[A-Za-z]+\.?\s*\d+[A-Za-z]?\s*")


def page_titles(page):
    """Return (own_title, display_title) of a bill page, or (None, None) when it has neither.

    `own_title` is what the paper calls itself, the only text the kind label reads (OPEN-508/518): the h2, or,
    when there is none, the h1 unless the h1 is the "Bill <number>" placeholder. OPEN-509: amendment papers
    ("Amendment S.2512") and a few messages and orders ("Governor's Message H.5712", "Extension Order H.4819")
    have no h2 at all; their h1 is their title. `display_title` is the stored title, unchanged: the h2, else the
    h1 with "Bill" removed.
    """
    try:
        h2 = page.xpath('//div[@id="contentContainer"]/div/div/h2/text()')[0]
    except IndexError:
        h2 = None
    if h2 is not None:
        return h2, h2
    try:
        h1 = page.xpath('//div[contains(@class,"followable")]/h1/text()')[0]
    except IndexError:
        return None, None
    own = None if _BILL_PLACEHOLDER_H1_RE.fullmatch(h1) else h1.strip()
    return own, h1.replace("Bill", "").strip()


def resolve_paper_parents(papers):
    """OPEN-509/512: the real bill each amendment paper belongs to, or None.

    `papers` maps a paper's id (fix_bill_id form) to {"refs": [bill ids its history links to],
    "substituted_for": the bill id its "Substituted ... for <bill>" action names, or None}. A paper that points at
    another paper belongs to that paper's bill: a floor amendment's history says "See S3178", the committee draft
    it amends, and S3178 was substituted for H5576. A paper whose links lead to no bill (no history), or to two
    different bills, gets None: it is never attached by guessing.
    """

    def bills_of(paper_id, seen):
        paper = papers[paper_id]
        targets = (
            [paper["substituted_for"]] if paper["substituted_for"] else paper["refs"]
        )
        found = []
        for target in targets:
            if target == paper_id or target in seen:
                continue
            reached = (
                bills_of(target, seen | {paper_id}) if target in papers else [target]
            )
            for bill_id in reached:
                if bill_id not in found:
                    found.append(bill_id)
        return found

    parents = {}
    for paper_id in papers:
        found = bills_of(paper_id, frozenset())
        parents[paper_id] = found[0] if len(found) == 1 else None
    return parents


def parse_senate_tally(action_name):
    """Return (yes, no, nay_label_ok) from a Senate roll-call action, or None.

    OPEN-177: accepts every spelling of the nay count Massachusetts actually
    uses, not just "nays". See `_SENATE_TALLY_RES`.

    `nay_label_ok` is False only for the malformed form -- "Yeas 39 to Yeas 0",
    where the source labels the nay count as yeas (S 2565). Reading the second
    number as the nay count there is an *inference* about a transcription error,
    not something the text says, so the caller records that it inferred it. The
    alternative, dropping the vote, loses a real 39-0 roll call whose PDF is
    readable -- but a caller that cannot corroborate it against a PDF should not
    present an inferred number as though the source supplied it.
    """
    text = action_name or ""
    match = _SENATE_TALLY_RES[0].search(text)
    if match:
        return int(match.group(1)), int(match.group(2)), True
    match = _SENATE_TALLY_RES[1].search(text)
    if match:
        nay_label_ok = match.group(2).lower().startswith("na")
        return int(match.group(1)), int(match.group(3)), nay_label_ok
    return None


def senate_rollcall_url(action_name, session):
    """Return the Senate roll-call PDF URL an action cites, or None.

    OPEN-176: built from the roll-call number in the action's own text rather
    than from whichever link happens to sit first in the action cell.

    Only ever returns a number this action attributes to the Senate:

    * an explicit ``Senate Roll Call #<n>`` wins outright;
    * otherwise an unqualified ``Roll Call #<n>`` is used, but only when the
      action names exactly one and it is not the number it gave the House;
    * anything ambiguous returns None, and the caller records the vote with
      ``voters_unavailable`` rather than guessing.

    Returning None costs a vote its voter list. Returning the wrong number
    costs it the *other chamber's* voter list, silently and plausibly, which is
    worse -- so ambiguity resolves to None.
    """
    text = action_name or ""

    senate_mention = _SENATE_ROLLCALL_MENTION_RE.search(text)
    if senate_mention:
        number = senate_mention.group(1)
    else:
        house_numbers = set(_HOUSE_ROLLCALL_MENTION_RE.findall(text))
        candidates = {
            n for n in _ROLLCALL_NUMBER_RE.findall(text) if n not in house_numbers
        }
        if len(candidates) != 1:
            return None
        number = candidates.pop()

    return _SENATE_ROLLCALL_URL.format(re.sub(r"\D+$", "", session), number)


def _house_vote_dedupe_key(housevote_pdf, n_supplement, bill_identifier):
    """OPEN-252: a single House roll-call PDF supplement number can legitimately be cited by
    more than one bill's action history -- MA sometimes engrosses companion/consolidated bills
    together in one roll call. Confirmed live in the 194th session: Supplement #29 on
    2025-04-09 is cited by both H4005's and H4010's "Passed to be engrossed" actions.

    `VoteEvent.bill` is a single FK, so this needs one row PER (roll call, bill) pair, not one
    shared row. Without the bill identifier folded in here, the second bill's vote resolves via
    `dedupe_key` to the first bill's already-imported row (`vote_events.py`'s `get_object()`
    replaces the whole match spec with `dedupe_key` alone) and the importer raises
    `DuplicateItemError` instead of creating its own row -- exactly what happened live during
    OPEN-193's canary (run `ma-f08d7646b9fe`).
    """
    return "{}#{}#{}".format(housevote_pdf, n_supplement, bill_identifier)


def _senate_vote_dedupe_key(
    rollcall_pdf, fallback_source, action_date, action_name, bill_identifier
):
    """Same reasoning as `_house_vote_dedupe_key()` -- a Senate roll-call PDF can likewise be
    cited by more than one bill's action history, so the bill identifier is folded in here too
    when a real `rollcall_pdf` is available.

    The no-PDF fallback branch is deliberately left in its original format (pm-review, round
    1): `fallback_source` there is already `bill.sources[0]["url"]` -- the bill's OWN page --
    so it was already unique per bill before this fix, and was never vulnerable to the
    companion-bill collision the PDF branch above has. Changing its key format anyway would
    only add migration/compatibility risk (any already-imported row would stop matching on the
    next scrape) for a branch that per the comment above this call site currently never
    executes at all (0 of 236 roll-call actions in the 194th).
    """
    if rollcall_pdf:
        return "{}#{}".format(rollcall_pdf, bill_identifier)
    return "{}#senate-{}-{}".format(
        fallback_source,
        action_date,
        re.sub(r"\W+", "-", action_name.strip().lower())[:80],
    )


def meta_id(bill_meta):
    """A Documents-list row's bill number, in fix_bill_id form ("H 4001")."""
    return fix_bill_id(bill_meta["BillNumber"] or bill_meta["DocketNumber"])


def meta_chamber(bill_meta):
    """The chamber a Documents-list row is scraped under (the split chamber_bill_list makes)."""
    return (
        "lower"
        if "H" in (bill_meta["BillNumber"] or bill_meta["DocketNumber"])
        else "upper"
    )


def meta_numbers(bill_meta):
    """OPEN-609: every number a Documents-list row is known by: its bill number and its docket number."""
    return {
        fix_bill_id(number)
        for number in (bill_meta["BillNumber"], bill_meta["DocketNumber"])
        if number
    }


def rollcall_of(vote):
    """OPEN-568: which roll call a vote is, whatever bill cited it: its dedupe key without the bill number.

    None for a Senate vote whose action cites no roll-call number (`_senate_vote_dedupe_key`'s fallback, keyed by
    the bill's own page, 0 of the 236 roll-call actions of the 194th): stripped, every such vote of one paper would
    read as the same roll call (its page), and date and tally alone do not identify one.
    """
    key = vote.dedupe_key or ""
    if "#senate-" in key:
        return None
    return key.rsplit("#", 1)[0]


class MABillScraper(Scraper):

    categorizer = Categorizer()
    session_filters = {}
    chamber_filters = {}
    house_pdf_cache = {}

    bill_list = []

    chamber_map = {"lower": "House", "upper": "Senate"}
    chamber_map_reverse = {
        "House": "lower",
        "Senate": "upper",
        "Executive": "executive",
        "Joint": "legislature",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # forcing these values so that 500s come back as skipped bills
        self.raise_errors = False
        self.retry_attempts = 0
        self._warned_no_title_rule = False
        # OPEN-509/512, filled by scrape_amendment_papers(): what each real bill gets from its amendment papers
        # (fix_bill_id -> [(kind, note, url, date, media_type)]), the papers it read, and the bill pages it already
        # fetched (url -> compressed html), so scrape_bill does not fetch them twice.
        self.paper_links = {}
        self.amendment_papers = set()
        self.prefetched_pages = {}
        # OPEN-568: amendment paper (fix_bill_id) -> its real bill; for this run's paper groups (see
        # with_paper_pairs): bill -> its group's real bill, real bill -> members not scraped yet, the members read
        # whole, and the group's votes held back; the bill pages whose history could not be read in full
        self.paper_parents = {}
        self.group_of = {}
        self.group_waiting = {}
        self.group_read_whole = set()
        self.group_votes = {}
        self.failed_histories = set()

    def label_non_bill(self, bill, page_title):
        """OPEN-518: give a paper that is not a bill the label for what it is, instead of skipping it.

        malegislature.gov files agency reports, communications, orders, study orders, precepts and rules under
        H/S/HD/SD numbers in the same list as real bills. Ramon (2026-11-09): nothing is removed from our data,
        so each is stored, labelled. The ONE rule that names the kind is openstates-core's `non_bill_kind`
        (OPEN-517), the same one `os-text-extract relabel-non-bills ma` uses, so the two always agree; this
        only asks it, with the page's own title and the actions (a committee study order titled by its subject
        is known by its action). A blank or missing title leaves an ordinary bill (the state site sometimes
        lacks one for a few days). OPEN-509: amendment papers are labelled "amendment" too, and the label the
        paper would otherwise have is saved under ORIGINAL_CLASSIFICATION_KEY, as the relabel command saves it.
        """
        if non_bill_kind is None:
            if not self._warned_no_title_rule:
                self._warned_no_title_rule = True
                self.warning(
                    "OPEN-518: openstates-core's non_bill_kind is not installed; "
                    "every paper is saved as a bill"
                )
            return
        kind = non_bill_kind(
            "Massachusetts", page_title, [a["description"] for a in bill.actions]
        )
        if kind is None:
            return
        if kind == NON_BILL_AMENDMENT:
            # OPEN-509: an amendment paper is labelled too (Ramon, 2026-11-15), so it leaves Explore and search;
            # it is listed under its real bill instead (see scrape_amendment_papers).
            if fix_bill_id(bill.identifier) not in self.amendment_papers:
                self.warning(
                    f"OPEN-509: {bill.identifier} is an amendment paper the pre-pass did not read; "
                    "it is not linked from its bill this run"
                )
            if not AMENDMENT_LABEL_OK:
                return
        self.info(
            f"OPEN-518: {bill.identifier} is a {kind} ({page_title.strip()[:60]!r})"
        )
        # the label it would otherwise have, kept so the relabel can be undone (as `relabel-non-bills` does)
        bill.extras[ORIGINAL_CLASSIFICATION_KEY] = list(bill.classification)
        bill.classification = [kind]

    def format_bill_number(self, raw):
        return raw.replace("Bill ", "").replace(".", " ").strip()

    def get_refiners(self, page, refinerName):
        # Get the possible values for each category of refiners,
        # e.g. House, Senate for lawsbranchname (Branch)
        filters = page.xpath(
            "//div[@data-refinername='{}']/div/label".format(refinerName)
        )

        refiner_list = {}
        for refiner_filter in filters:
            label = re.sub(r"\([^)]*\)", "", refiner_filter.xpath("text()")[1]).strip()
            refiner = refiner_filter.xpath("input/@data-refinertoken")[0].replace(
                '"', ""
            )
            refiner_list[label] = refiner
        return refiner_list

    # bill_no can be set to a specific bill (no spaces) to scrape only one
    # os-update ma bills --scrape bill_no=H2
    # we can also scrape a "chunk" of all available bills by specifying an integer 1-12 (inclusive)
    # chunks are available to split up this long, slow scrape into 12 smaller scrapes
    # os-update ma bills --scrape scrape_chunk_number=1
    # this trades off comprehensivity for limited scope of failure/faster time to recovery
    def scrape(
        self,
        chamber=None,
        session=None,
        bill_no=None,
        scrape_chunk_number=None,
        start=None,
    ):
        self.scrape_bill_list(session, start=start)

        # OPEN-609: a whole run (no chamber, bill or chunk) given start= reads only the bills the catch-up sources
        # name (see catch_up), unless a full walk is due or a source cannot answer, and remembers this run's lists
        # for the next one. A run without start= (a first or manual run) or a partial run is as before: it reads
        # every bill it covers and neither uses nor changes that record.
        whole_run = bool(start) and not (chamber or bill_no or scrape_chunk_number)
        if whole_run and not self.bill_list:
            # review 21038: not a quiet week. A hard error, so the collector fails the run instead of taking an empty
            # incremental run for a no-op and advancing the watermark
            raise ValueError("OPEN-609: the Documents list is empty")
        selected = hearings = None
        if whole_run:
            state = catchup.load_state(catchup.state_path(session))
            selected, hearings = self.catch_up(session, start, state)
            if hearings is None and state is not None:
                # the hearing list could not be read: the next run compares with the older one
                hearings = state["hearings"]

        # optionally scrape a single bill then exit
        metas = []
        if bill_no:
            metas = [
                bill_meta
                for bill_meta in self.bill_list
                if bill_no in [bill_meta["DocketNumber"], bill_meta["BillNumber"]]
            ][:1]
        if not metas:
            for one_chamber in [chamber] if chamber else ["lower", "upper"]:
                metas += self.chamber_bill_list(one_chamber, scrape_chunk_number)
        if selected is not None:
            metas = [m for m in metas if meta_numbers(m) & selected]
            self.info(
                "OPEN-609: catch-up run reads {} of {} bills".format(
                    len(metas), len(self.bill_list)
                )
            )
            if not metas:
                # a quiet week is a real answer (as PA and GA): nothing to read, nothing deleted
                self.save_catch_up(session, hearings, state["full_walk_on"], set())
                raise EmptyScrape

        self.scrape_amendment_papers(session)

        unread = set()
        for bill_meta in self.with_paper_pairs(metas):
            read = False
            for obj in self.scrape_bill(session, bill_meta, meta_chamber(bill_meta)):
                read = read or isinstance(obj, Bill)
                yield obj
            # a bill whose page failed, or whose history only partly loaded, is read again next run (review 21038)
            if not read or self.bill_url(session, bill_meta) in self.failed_histories:
                unread.add(meta_id(bill_meta))
            yield from self.group_member_done(meta_id(bill_meta))
        if bill_no and len(metas) == 1:
            self.info("Finished individual bill scrape, exiting.")
        if whole_run:
            # a bill that could not be read is read again next run, whatever named it
            walked_on = (
                datetime.utcnow().date() if selected is None else state["full_walk_on"]
            )
            self.save_catch_up(session, hearings, walked_on, unread)

    def catch_up(self, session, start, state):
        """OPEN-609: (the numbers of the bills to read, this run's hearing ids); the numbers are None for a full walk.

        With the last whole run's record, the bills to read are those named in the House and Senate
        journals dated from 21 days before start= (catchup.JOURNAL_LOOKBACK), the bills the governor approved in
        that time (Session Laws), the bills on hearings posted since the last run, the bills new in the Documents
        list since the last run, and the bills the last run could not read. Without a record, when
        the last full walk is catchup.FULL_WALK_EVERY old, or when any source fails or answers implausibly (as GA,
        OPEN-604), every bill is read: never a partial run.
        """
        session_number = self.replace_non_digits(session)
        hearings = None
        try:
            hearings = self.hearing_ids()
        except Exception as e:
            self.warning("OPEN-609: could not list the hearings ({})".format(e))
        reason = None
        if state is None:
            reason = "no record of the last run's lists"
        elif (
            datetime.utcnow().date() - state["full_walk_on"] >= catchup.FULL_WALK_EVERY
        ):
            reason = "the last full walk was on {}".format(state["full_walk_on"])
        elif hearings is None or state["hearings"] is None:
            reason = "no hearing list to compare"
        if reason is None:
            try:
                since = (
                    datetime.strptime(start[:19], "%Y-%m-%dT%H:%M:%S").date()
                    - catchup.JOURNAL_LOOKBACK
                )
            except ValueError:
                reason = "start={!r} is not a date".format(start)
        if reason is None:
            try:
                journals = self.journal_bills(session_number, since)
                laws = self.session_law_bills(session_number, since)
                heard = set()
                for event_id in sorted(hearings - state["hearings"]):
                    heard |= self.hearing_bills(session_number, event_id)
            except Exception as e:
                reason = "a source could not be read ({})".format(e)
        if reason is not None:
            self.info("OPEN-609: reading every bill: {}".format(reason))
            return None, hearings

        listed = set().union(*(meta_numbers(m) for m in self.bill_list))
        new = listed - state["bills"]
        selected = journals | laws | heard | new | state["retry"]
        self.info(
            "OPEN-609: since {} (start={} less {} days): {} named in journals, {} signed, {} on {} new hearings, "
            "{} new in the bill list, {} to retry".format(
                since,
                start,
                catchup.JOURNAL_LOOKBACK.days,
                len(journals),
                len(laws),
                len(heard),
                len(hearings - state["hearings"]),
                len(new),
                len(state["retry"]),
            )
        )
        return selected, hearings

    def save_catch_up(self, session, hearings, full_walk_on, retry):
        listed = set().union(*(meta_numbers(m) for m in self.bill_list))
        catchup.save_state(
            catchup.state_path(session), listed, hearings, full_walk_on, retry
        )

    def fetch_ok(self, url):
        """A source request that must succeed: the scraper's own get() does not raise on an error status here."""
        response = self.get(url)
        if response.status_code != 200:
            raise ValueError("HTTP {} from {}".format(response.status_code, url))
        return response

    def journal_bills(self, session_number, since):
        """Bills named in every House and Senate journal dated on or after `since` (OPEN-609)."""
        today = datetime.utcnow().date()
        found = set()
        for chamber in ("House", "Senate"):
            named, read = set(), 0
            for month in catchup.months(since, today):
                index = self.fetch_ok(
                    JOURNAL_MONTH_URL.format(
                        chamber=chamber, session=session_number, month=month
                    )
                )
                page = lxml.html.fromstring(index.text)
                page.make_links_absolute("https://malegislature.gov")
                for url in JOURNAL_PDF_LINKS.match(page, min_items=0):
                    sitting = journal_date(url)
                    if sitting is None and url.lower().endswith(".pdf"):
                        # a journal file named some new way: its date, and so whether to read it, is unknown
                        raise ValueError("cannot date the journal {}".format(url))
                    if sitting is None or sitting < since:
                        continue
                    named |= catchup.journal_bills(self.journal_text(url))
                    read += 1
            # each chamber sits at least weekly and every sitting names bills, so a chamber whose journals of the last
            # three weeks name nothing (or that has none) means its listing or its files changed shape (pm-review)
            if not named:
                raise ValueError(
                    "{} {} journals since {} name no bill".format(read, chamber, since)
                )
            found |= named
        return found

    def journal_text(self, url):
        path, response = self.urlretrieve(url)
        try:
            with open(path, "rb") as f:
                if response.status_code != 200 or not f.read(5).startswith(b"%PDF"):
                    raise ValueError("{} is not a PDF".format(url))
            return convert_pdf(path, "text").decode("utf-8", "replace")
        finally:
            os.remove(path)

    def session_law_bills(self, session_number, since):
        """Bills the governor approved on or after `since`, from each year's Session Laws page (OPEN-609)."""
        found, chapters = set(), 0
        for year in range(since.year, datetime.utcnow().year + 1):
            page = self.fetch_ok(
                "https://malegislature.gov/Laws/SessionLaws/Acts/{}".format(year)
            )
            signed, listed = catchup.session_law_bills(page.text, session_number, since)
            found |= signed
            chapters += listed
        if not chapters:
            raise ValueError("the Session Laws pages list no chapter")
        return found

    def hearing_ids(self):
        listing = json.loads(
            self.fetch_ok("https://malegislature.gov/api/Hearings").content
        )
        ids = {row["EventId"] for row in listing}
        if not ids:
            raise ValueError("the hearing list is empty")
        return ids

    def hearing_bills(self, session_number, event_id):
        detail = json.loads(
            self.fetch_ok(
                "https://malegislature.gov/api/Hearings/{}".format(event_id)
            ).content
        )
        return catchup.hearing_bills(detail, session_number)

    def with_paper_pairs(self, metas):
        """OPEN-568: `metas`, plus the rest of each paper-and-real-bill group, so a run scrapes them together.

        A real bill's votes now come from its own history and from its papers'. The import deletes every stored vote
        of a bill that gets any vote in the run unless the run brings it again (openstates-core vote_events.py), so
        a run holding only one side would delete the other side's votes: `bill_no=S3` would delete H 4001's own
        votes, `bill_no=H4001` the votes moved from S 3. A full run holds every group already; a single-bill,
        single-chamber or chunk run adds the missing members (in the 194th, 152 linked papers on 102 bills; the
        largest group, H 5576, adds 27 papers).

        It also records this run's groups: a paper whose real bill is not in the list is in none, and its votes stay
        on it, as before OPEN-568.
        """
        ids = {meta_id(meta) for meta in metas}
        roots = {self.paper_parents.get(bill_id, bill_id) for bill_id in ids}
        wanted = roots | {
            paper for paper, parent in self.paper_parents.items() if parent in roots
        }
        extra = []
        for bill_meta in self.bill_list:
            bill_id = meta_id(bill_meta)
            if bill_id in wanted and bill_id not in ids:
                ids.add(bill_id)
                extra.append(bill_meta)
        if extra:
            self.info(
                "OPEN-568: also scraping {} so each amendment paper is scraped with its real bill".format(
                    ", ".join(meta_id(m) for m in extra)
                )
            )
        scheduled = ids
        self.group_of, self.group_waiting = {}, {}
        for paper, parent in self.paper_parents.items():
            if paper in scheduled and parent in scheduled:
                self.group_of[paper] = self.group_of[parent] = parent
        for bill_id, root in self.group_of.items():
            self.group_waiting.setdefault(root, set()).add(bill_id)
        return list(metas) + extra

    def group_member_done(self, bill_id):
        """OPEN-568: once every bill of a paper group has been scraped, send the group's votes, or none of them.

        The import deletes a bill's stored votes that the run did not bring again. If any bill of the group could
        not be read whole (its page, or a page of its history, failed), sending the rest would delete the missing
        votes: S 3's history failing would delete the 21 votes moved from it to H 4001. So the whole group's votes
        are held back that run, and nothing is deleted. A roll call cited both by the real bill and by a paper (or
        by two papers) is sent once, the real bill's own first.
        """
        root = self.group_of.get(bill_id)
        if root is None:
            return
        waiting = self.group_waiting[root]
        waiting.discard(bill_id)
        if waiting:
            return
        members = {b for b, r in self.group_of.items() if r == root}
        votes = self.group_votes.pop(root, [])
        missing = sorted(members - self.group_read_whole)
        if missing:
            self.warning(
                "OPEN-568: {} not read whole; the {} votes of {} and its amendment papers are not sent "
                "this run, so none of them is deleted".format(
                    ", ".join(missing), len(votes), root
                )
            )
            return
        votes.sort(key=lambda vote: "ddp_amendment_paper" in vote.extras)
        sent = set()
        for vote in votes:
            rollcall = rollcall_of(vote)
            if rollcall is not None and rollcall in sent:
                self.info(
                    "OPEN-568: roll call {} from {} is already on {}; not added again".format(
                        rollcall, vote.extras.get("ddp_amendment_paper"), root
                    )
                )
                continue
            sent.add(rollcall)
            yield vote

    def scrape_amendment_papers(self, session):
        """OPEN-509/512 pre-pass: read every amendment paper's real bill before any bill is scraped.

        malegislature.gov files a committee's redraft, a reprint and a member's amendment as a paper of its own
        ("Amendment S.2512"). Ramon (2026-11-15): each is labelled an amendment, and listed on its real bill: the
        drafts a chamber formally substituted for the bill (the paper's own history says "Substituted ... for
        H4010") as a new version of that bill, so LegBot's changelogs can use them; every other paper as a
        supporting document. A bill already yielded cannot be added to, and the paper and its bill can fall in
        different chunks, so the papers are read first, every run and every chunk.

        Only the page says a paper is one: the Documents list's Title is a subject or an "An Act ..." line for
        them (OPEN-509 comment 19566). The list does narrow the search: every amendment paper of the 194th has
        no docket number (145 of 145 in the 2026-08-30 list), against 1,205 other rows without one. Those pages
        are fetched here and kept for scrape_bill, so the pre-pass costs only the papers' histories.
        """
        if non_bill_kind is None:
            return
        session_for_url = self.replace_non_digits(session)
        papers = {}
        for bill_meta in self.bill_list:
            bill_id = bill_meta["BillNumber"]
            if bill_meta["DocketNumber"] or not bill_id:
                continue
            bill_url = "https://malegislature.gov/Bills/{}/{}".format(
                session_for_url, bill_id
            )
            html = self.fetch_bill_page(bill_url)
            if html is None:
                continue
            self.prefetched_pages[bill_url] = zlib.compress(html.encode("utf-8"))
            page = lxml.html.fromstring(html)
            own_title, display_title = page_titles(page)
            if non_bill_kind("Massachusetts", own_title) != NON_BILL_AMENDMENT:
                continue
            paper = {
                "title": display_title,
                "url": bill_url,
                "media_type": "text/html",
                "refs": [],
                "substituted_for": None,
                "substituted_on": None,
                "first_date": None,
            }
            pdf = page.xpath(
                "//div[contains(@class, 'modalBtnGroup')]/"
                "a[contains(text(), 'Download PDF') and not(@disabled)]/@href"
            )
            if pdf:
                paper["url"] = "https://malegislature.gov{}".format(pdf[0])
                paper["media_type"] = "application/pdf"
            for action_page in self.action_pages(bill_url):
                for row in action_page.xpath("//tbody/tr"):
                    if not row.xpath("td[1]/text()"):
                        continue
                    date = datetime.strptime(
                        row.xpath("td[1]/text()")[0].strip(), "%m/%d/%Y"
                    ).strftime("%Y-%m-%d")
                    paper["first_date"] = paper["first_date"] or date
                    text = row.xpath("string(td[3])")
                    substituted = _SUBSTITUTED_FOR_RE.search(text)
                    if substituted and not paper["substituted_for"]:
                        paper["substituted_for"] = fix_bill_id(
                            substituted.group(1) + substituted.group(2)
                        )
                        paper["substituted_on"] = date
                    for href in row.xpath("td[3]//a/@href"):
                        ref = _BILL_HREF_RE.match(href)
                        if ref and fix_bill_id(ref.group(1)) not in paper["refs"]:
                            paper["refs"].append(fix_bill_id(ref.group(1)))
            papers[fix_bill_id(bill_id)] = paper

        self.amendment_papers = set(papers)
        for paper_id, parent in resolve_paper_parents(papers).items():
            paper = papers[paper_id]
            if parent is None:
                self.warning(
                    f"OPEN-509: amendment paper {paper_id} names no single bill; not linked"
                )
                continue
            # OPEN-568: the paper's roll calls go on the real bill (see paper_vote_event and scrape_bill)
            self.paper_parents[paper_id] = parent
            if paper["substituted_for"] and paper["media_type"] == "application/pdf":
                # OPEN-512: the chamber adopted this draft as the bill's text. "Substituted text (S2512)" ranks
                # as an amendment-stage version in openstates-core's version ordering (after "Bill Text", before
                # "Chapter Law Text (Enacted)"); the date is the day it was substituted. A version is the bill's
                # text, so it needs the draft's PDF: without one (none of the 30 substituted in the 194th lacks it)
                # the paper's page is linked as a document instead, never archived as bill text.
                link = (
                    "version",
                    "Substituted text ({})".format(paper_id.replace(" ", "")),
                    paper["url"],
                    paper["substituted_on"],
                    paper["media_type"],
                )
            else:
                link = (
                    "document",
                    paper["title"],
                    paper["url"],
                    paper["first_date"] or "",
                    paper["media_type"],
                )
            self.paper_links.setdefault(parent, []).append(link)
        self.info(
            f"OPEN-509: {len(papers)} amendment papers read, linked to {len(self.paper_links)} bills"
        )

    def fetch_bill_page(self, bill_url):
        """A bill page's html, or None when it could not be fetched (warned)."""
        try:
            response = self.get(bill_url)
            self.info("GET (with `requests`) - {}".format(bill_url))
        except requests.exceptions.RequestException:
            self.warning("Server Error on {}".format(bill_url))
            return None
        return response.text

    def scrape_bill_list(self, session, start=None):
        session_numeric = re.sub(r"[^0-9]", "", session)
        # note -- this returns XML to a browser, but json to curl/python
        api_url = (
            f"https://malegislature.gov/api/GeneralCourts/{session_numeric}/Documents"
        )

        # OPEN-128: `start` is accepted (ddp-sync passes it on every incremental run) and
        # deliberately NOT used to filter. It used to gate on the newest sponsor ResponseDate,
        # which is wrong in a way that loses data silently: sponsorship is set at filing and a
        # later action never touches it, so a bill that passed a chamber, was amended, or became
        # a Public Act kept its original sponsor date, failed the filter, and was skipped every
        # run. Its actions then went stale indefinitely. Measured against the production
        # database, 8,098 of 11,289 MA bills (71%) have activity after their first action, i.e.
        # activity the sponsor date structurally cannot reflect -- on the order of 80-100 bills
        # a week.
        #
        # There is no cheaper signal to swap in, and this was checked rather than assumed:
        #   * The list endpoint used here carries nine fields per bill and no date of any
        #     activity -- the sponsor ResponseDate is the only date in the payload, which is
        #     presumably why it was reached for (OPEN-133 enumerated this).
        #   * malegislature.gov exposes no dated "recently acted on" surface. Michigan's
        #     equivalent bug (OPEN-134) was fixable cheaply because MI's search results page
        #     prints each bill's last action; MA's /Bills/Search is a keyword search that
        #     returns nothing for empty terms and never lists last actions, so the same trick
        #     does not transfer.
        #   * Bill pages send `Cache-Control: no-cache, no-store` and neither ETag nor
        #     Last-Modified, so conditional requests cannot make a walk cheap either.
        #
        # So the honest options were to accept the staleness or to stop filtering, and this
        # takes the second. Cost, measured from a real full walk in the logs rather than
        # estimated: 11,465 requests in 341 minutes, ~1.01 requests per bill. That is bounded by
        # malegislature.gov's own ~2s response time, NOT by our rate limit -- probing 30 real
        # bill pages paced at 3/sec still only sustained 0.4/sec, all 200s. Raising
        # SCRAPELIB_RPM would therefore buy nothing.
        #
        # If ~6h per run proves too long, the lever already exists and needs no new code:
        # scrape()'s `scrape_chunk_number` splits the corpus into 12 chunks, so a caller can
        # cover everything across several shorter runs instead of one long one.
        if start:
            self.info(
                "MA OPEN-128: ignoring start= and listing every bill. The sponsor ResponseDate "
                "this used to filter on does not move when a bill acts, so filtering on it "
                "silently skipped ~80-100 bills a week. See scrape_bill_list() for why no "
                "cheaper signal exists."
            )

        list_data = self.get(api_url).content
        for row in json.loads(list_data):
            chambers = ["H", "S"]

            # bill never flips from house to senate from docket -> intro so we're safe here
            # BillNumber can be set, but mapped to None, so use or here
            bill_id = row["BillNumber"] or row["DocketNumber"]
            # make sure the bill has an H or an S in the code
            if not any([chamber in bill_id for chamber in chambers]):
                self.error(
                    f"Unknown bill type - bill {row['BillNumber']} - docket {row['DocketNumber']}"
                )

            self.bill_list.append(
                {"BillNumber": row["BillNumber"], "DocketNumber": row["DocketNumber"]}
            )

    def chamber_bill_list(self, chamber, scrape_chunk_number):
        chamber_code = "H" if chamber == "lower" else "S"
        chamber_bill_list = []
        for bill_meta in self.bill_list:
            bill_id = bill_meta["BillNumber"] or bill_meta["DocketNumber"]
            if chamber_code in bill_id:
                chamber_bill_list.append(bill_meta)

        # if scrape_chunk_number is specified, we are being asked to scrape
        # only a specific chunk of the total bills in this chamber
        # let's use 1-based counting so we're not doing scrape_chunk_number=0
        if scrape_chunk_number:
            # divide up the chamber_bill_list into 12 equal-sized lists
            chunk_size = (
                len(chamber_bill_list) // 12 if len(chamber_bill_list) >= 12 else 1
            )
            if len(chamber_bill_list) % 12 > 0:
                chunk_size += 1
            bill_chunks = [
                chamber_bill_list[i : i + chunk_size]
                for i in range(0, len(chamber_bill_list), chunk_size)
            ]
            chunk_number = int(scrape_chunk_number)

            chamber_bill_list = bill_chunks[chunk_number - 1]

        return chamber_bill_list

    def bill_url(self, session, bill_meta):
        # https://malegislature.gov/Bills/189/SD2739
        return "https://malegislature.gov/Bills/{}/{}".format(
            self.replace_non_digits(session),
            bill_meta["BillNumber"] or bill_meta["DocketNumber"],
        )

    def scrape_bill(self, session, bill_meta, chamber):
        bill_id = bill_meta["BillNumber"] or bill_meta["DocketNumber"]
        bill_url = self.bill_url(session, bill_meta)

        prefetched = self.prefetched_pages.pop(bill_url, None)
        if prefetched is not None:
            html = zlib.decompress(prefetched).decode("utf-8")
        else:
            html = self.fetch_bill_page(bill_url)
            if html is None:
                return False

        page = lxml.html.fromstring(html)

        if not page.xpath('//div[contains(@class, "followable")]/h1/text()'):
            self.warning("Server Error on {}".format(bill_url))
            return False

        # The state website will periodically miss a few bills' titles for a few days
        # These titles will be extant on the bill list page, but missing on the bill detail page
        # The titles are eventually populated under one of two markups
        #
        # OPEN-508/518: only the page's own title says what a paper is (see page_titles: a "Bill <number>" h1
        # is a placeholder, not a title). The Documents list's `Title` is NOT the same text and must not be used
        # for this: on the live list (2026-11-08) 19 real bills show a title without "An Act" (H5174, S2630, H70,
        # ...) and amendment papers show a subject ("Rural Jobs") where their page says "Amendment S.3207".
        page_title, bill_title = page_titles(page)
        if bill_title is None:
            self.warning("Couldn't find title for {}; skipping".format(bill_id))
            return False

        bill_types = ["H", "HD", "S", "SD", "SRes"]
        if re.sub("[0-9]", "", bill_id) not in bill_types:
            self.warning("Unsupported bill type for {}; skipping".format(bill_id))
            return False
        classification = "proposed bill" if "D" in bill_id else "bill"

        if "SRes" in bill_id:
            bill_id = bill_id.replace("SRes", "SR")

        bill = Bill(
            bill_id,
            legislative_session=session,
            chamber=chamber,
            title=bill_title,
            classification=classification,
        )

        bill_summary = None
        if page.xpath('//p[@id="pinslip"]/text()'):
            bill_summary = page.xpath('//p[@id="pinslip"]/text()')[0].strip()
        if bill_summary and bill_summary != "":
            bill.add_abstract(bill_summary, "summary")

        if bill_meta["BillNumber"] and bill_meta["DocketNumber"]:
            bill.add_related_bill(
                bill_meta["DocketNumber"],
                legislative_session=session,
                relation_type="replaces",
            )

        bill.add_source(bill_url)

        # https://malegislature.gov/Bills/189/SD2739 has a presenter
        # https://malegislature.gov/Bills/189/S2168 no sponsor
        # Find the non-blank text of the dt following Sponsor or Presenter,
        # including any child link text.
        sponsor = page.xpath(
            '//dt[text()="Sponsor:" or text()="Presenter:"]/'
            "following-sibling::dd/descendant-or-self::*/text()[normalize-space()]"
        )
        # Sponsors always have link that follows pattern <a href="/Legislators/Profile/JNR1/193">Jeffrey N. Roy</a>
        # If this is a person i.e. "legislators" it will show in sponsor_href.
        sponsor_href = page.xpath(
            '//dt[text()="Sponsor:" or text()="Presenter:"]/following-sibling::dd//a/@href'
        )
        sponsor_href = sponsor_href[0] if sponsor_href else ""
        entity_type = (
            "person" if "legislators/" in sponsor_href.lower() else "organization"
        )

        if sponsor:
            sponsor = (
                sponsor[0]
                .replace("*", "")
                .replace("%", "")
                .replace("This sponsor is an original petitioner.", "")
                .strip()
            )
            bill.add_sponsorship(
                sponsor, classification="primary", primary=True, entity_type=entity_type
            )

        self.scrape_cosponsors(bill, bill_url)

        version = page.xpath(
            "//div[contains(@class, 'modalBtnGroup')]/"
            "a[contains(text(), 'Download PDF') and not(@disabled)]/@href"
        )
        if version:
            version_url = "https://malegislature.gov{}".format(version[0])
            bill.add_version_link(
                "Bill Text", version_url, media_type="application/pdf"
            )

        # OPEN-509/512: this bill's amendment papers, read by the pre-pass
        for kind, note, url, date, media_type in self.paper_links.get(
            fix_bill_id(bill.identifier), ()
        ):
            add_link = (
                bill.add_version_link if kind == "version" else bill.add_document_link
            )
            add_link(note, url, date=date, media_type=media_type)

        # OPEN-568: a bill of a paper group holds its votes back until the whole group is scraped (see
        # group_member_done). A history the OPEN-509 pre-pass failed to read and this pass reads counts as read.
        member = meta_id(bill_meta)
        root = self.group_of.get(member)
        self.failed_histories.discard(bill_url)
        if root is None:
            yield from self.scrape_actions(bill, bill_url, session)
        else:
            self.group_votes.setdefault(root, []).extend(
                self.scrape_actions(bill, bill_url, session)
            )
            if bill_url not in self.failed_histories:
                self.group_read_whole.add(member)
        # OPEN-645 (Ramon, 2026-11-21: "Read it on every run"): every bill read reads its Similar Bills tab, a full
        # walk included, because each import replaces the bill's related list and a run without the tab would wipe it.
        # The cost: one more page per bill, about 1.5 s (roughly +5 h on a full walk of 11,932 bills). Read after the
        # history, so a failed tab's "read again next run" is not cleared by the history's own reset above.
        self.add_similar_bills(bill, bill_url)
        self.label_non_bill(bill, page_title)
        yield bill

    def paper_vote_event(self, bill, **kwargs):
        """A VoteEvent for a roll call in `bill`'s history, recorded on the bill it really decides.

        OPEN-568 (Ramon, 2026-11-16: "Ship now; move votes later"): a roll call in an amendment paper's history
        (the Senate's budget debate on S 3, its redraft of H 4001: "Amendment #493 (R. Kennedy) adopted") is a vote
        on the real bill, so it is recorded there, on the parent the OPEN-509 pre-pass resolved; the paper keeps
        its own actions. The paper's number is kept in the vote's extras so it can be traced back. Its dedupe key
        is not changed (the callers still build it from the paper's number), so the next import moves the stored
        row to the real bill instead of adding a second one. Any other bill's votes stay on it.
        """
        paper = fix_bill_id(bill.identifier)
        # only within a group this run scrapes whole (see with_paper_pairs)
        parent = self.group_of.get(paper) if self.group_of.get(paper) != paper else None
        # the bill is looked up in its chamber; only an "H" or "S" number names one
        chamber = {"H": "lower", "S": "upper"}.get((parent or "").split(" ")[0])
        if chamber is None:
            return VoteEvent(bill=bill, **kwargs)
        vote = VoteEvent(
            bill=parent,
            bill_chamber=chamber,
            legislative_session=bill.legislative_session,
            **kwargs,
        )
        vote.extras["ddp_amendment_paper"] = bill.identifier
        return vote

    def scrape_cosponsors(self, bill, bill_url):
        # https://malegislature.gov/Bills/189/S1194/CoSponsor
        cosponsor_url = "{}/CoSponsor".format(bill_url)
        response = self.get_as_ajax(cosponsor_url)
        if response is None:
            self.warning("Skipping cosponsors for {} -- fetch failed".format(bill_url))
            return
        page = lxml.html.fromstring(response.text)
        cosponsor_rows = page.xpath("//tbody/tr")
        for row in cosponsor_rows:
            # careful, not everyone is a linked representative
            # https://malegislature.gov/Bills/189/S740/CoSponsor
            cosponsor_name = row.xpath("string(td[1])").strip()
            # cosponsor_district = ''
            # # if row.xpath('td[2]/text()'):
            #     cosponsor_district = row.xpath('td[2]/text()')[0]

            # Filter the sponsor out of the petitioners list
            if not any(
                sponsor["name"] == cosponsor_name for sponsor in bill.sponsorships
            ):
                cosponsor_name = (
                    cosponsor_name.replace("*", "")
                    .replace("%", "")
                    .replace("This sponsor is an original petitioner.", "")
                    .strip()
                )
                bill.add_sponsorship(
                    cosponsor_name,
                    classification="cosponsor",
                    primary=False,
                    entity_type="person",
                    # district=cosponsor_district
                )

    def scrape_actions(self, bill, bill_url, session):
        for page in self.action_pages(bill_url):
            yield from self.scrape_action_page(bill, page)

    def action_pages(self, bill_url):
        """Every page of a bill's history, e.g. https://malegislature.gov/Bills/189/S3/BillHistory?pageNumber=2"""
        page = self.get_action_page(bill_url, 1)
        if page is None:
            self.warning("Skipping actions for {} -- fetch failed".format(bill_url))
            self.failed_histories.add(bill_url)
            return
        yield page

        # the first page holds the paginator
        max_page = page.xpath(
            '//ul[contains(@class,"pagination-sm")]/li[last()]/a/@onclick'
        )
        if max_page:
            max_page = re.sub(r"[^\d]", "", max_page[0]).strip()
            for counter in range(2, int(max_page) + 1):
                page = self.get_action_page(bill_url, counter)
                if page is None:
                    self.warning(
                        "Skipping action page {} for {} -- fetch failed".format(
                            counter, bill_url
                        )
                    )
                    self.failed_histories.add(bill_url)
                    continue
                yield page

    def get_action_page(self, bill_url, page_number):
        actions_url = "{}/BillHistory?pageNumber={}".format(bill_url, page_number)
        response = self.get_as_ajax(actions_url)
        if response is None:
            return None
        return lxml.html.fromstring(response.text)

    def add_similar_bills(self, bill, bill_url):
        """OPEN-645: the bill page's "Similar Bills" tab, each listed bill a `related` link labelled "Similar Bills",
        in its own session. A link the action text already made to the same bill gets the label instead of a second
        row. A tab that cannot be read is skipped with a warning: the bill is still saved, and is read again next run."""
        try:
            page = lxml.html.fromstring(self.get(bill_url + "/SimilarBills").content)
        except Exception as e:
            self.warning(
                "OPEN-645: Similar Bills not read for {} ({})".format(bill_url, e)
            )
            # saved without them, so read again next run (the import replaces the stored list)
            self.failed_histories.add(bill_url)
            return
        sessions = {
            self.replace_non_digits(s["identifier"]): s["identifier"]
            for s in self.jurisdiction.legislative_sessions
        }
        own = fix_bill_id(bill.identifier)
        for href in page.xpath('//ul[contains(@class, "relatedBills")]//a/@href'):
            match = _SIMILAR_HREF_RE.match(href)
            session = sessions.get(match.group(1)) if match else None
            if not session:
                continue
            identifier = fix_bill_id(match.group(2))
            if identifier == own and session == bill.legislative_session:
                continue
            existing = [
                rb
                for rb in bill.related_bills
                if rb["identifier"] == identifier
                and rb["legislative_session"] == session
                and rb["relation_type"] == "related"
            ]
            if existing:
                for rb in existing:
                    rb["ddp_relation_label"] = (
                        rb.get("ddp_relation_label") or MA_SIMILAR_LABEL
                    )
                continue
            bill.add_related_bill(
                identifier,
                legislative_session=session,
                relation_type="related",
                label=MA_SIMILAR_LABEL,
            )

    def scrape_action_page(self, bill, page):
        action_rows = page.xpath("//tbody/tr")
        for row in action_rows:
            if len(row.xpath("td[1]/text()")) == 0:
                continue
            action_date = row.xpath("td[1]/text()")[0]
            action_date = datetime.strptime(action_date, "%m/%d/%Y")
            action_year = action_date.year
            action_date = action_date.strftime("%Y-%m-%d")

            if row.xpath("td[2]/text()"):
                action_actor = row.xpath("td[2]/text()")[0]
                action_actor = self.chamber_map_reverse[action_actor.strip()]

            action_name = row.xpath("string(td[3])")

            # The action-history table's own hrefs carry two independent signals:
            # OPEN-37's enacted Chapter-of-the-Acts link (captured as a second,
            # distinctly-noted bill version so OPEN-34's diff pipeline can diff
            # introduced text against enacted text), and OPEN-36/OPEN-69 Tier 2's
            # cross-references to a different bill number that is a committee-
            # substitute/amendment/conference-report stage of this bill (captured
            # as a related_bill edge, not a version -- see
            # notes/ma-open-69-stage-chain-design-*.md for why).
            for href in row.xpath("td[3]//a/@href"):
                chapter_match = re.search(
                    r"^/Laws/SessionLaws/Acts/(\d{4})/Chapter(\d+)$", href
                )
                if chapter_match:
                    bill.add_version_link(
                        "Chapter Law Text (Enacted)",
                        "https://malegislature.gov{}".format(href),
                        media_type="text/html",
                    )
                    continue

                bill_ref_match = _BILL_HREF_RE.match(href)
                if bill_ref_match:
                    # relation_type="related" (not "replaces"/"replaced-by"):
                    # OPEN-36 found these cross-references form a directed
                    # stage chain, not a clean linear supersession, and
                    # picking a direction here would presuppose the
                    # canonical-bill answer OPEN-69 explicitly defers (see
                    # notes/ma-open-69-stage-chain-design-*.md).
                    ref_bill_id = fix_bill_id(bill_ref_match.group(1))
                    if ref_bill_id == fix_bill_id(bill.identifier):
                        continue
                    already_related = any(
                        rb["identifier"] == ref_bill_id
                        and rb["relation_type"] == "related"
                        # OPEN-645: same session too; the Similar Bills tab also links earlier sessions' bills
                        and rb["legislative_session"] == bill.legislative_session
                        for rb in bill.related_bills
                    )
                    if not already_related:
                        bill.add_related_bill(
                            bill_ref_match.group(1),
                            legislative_session=bill.legislative_session,
                            relation_type="related",
                        )

            # House votes
            #
            # OPEN-169: the trigger used to be `"Supplement" in action_name` alone, and
            # that string does not appear in Massachusetts action text any more. Across
            # the 24 bills that failed the MA 194th coverage comparison, "Supplement"
            # occurs ZERO times while "YEA and NAY" occurs 57 -- so every House roll call
            # was skipped before a single request was made. Not a fetch failure and not a
            # parse failure: the scraper never tried. The Senate branch below matched
            # reality ("Roll Call", 41 occurrences), which is why MA had Senate votes and
            # no House votes at all rather than an obvious total blank.
            #
            # Everything downstream already expects this format. scrape_house_vote()
            # splits the roll-call PDF on "No. " + <number>, which is exactly how
            # "(See YEA and NAY No. 62 )" numbers itself, and the motion/YEAS/NAYS
            # regexes below parse the modern text unchanged. Only the gate was stale.
            #
            # "Supplement" is kept in the condition rather than replaced: older sessions
            # may still use it, and dropping it would trade this bug for its mirror image.
            if (
                "Supplement" in action_name
                or re.search(r"YEA and NAY", action_name, re.IGNORECASE)
            ) and not _QUORUM_RE.search(action_name):
                actor = "lower"

                if not re.findall(r"(.+)-\s*\d+\s*YEAS", action_name):
                    self.warning(
                        "vote {} did not match regex, skipping".format(action_name)
                    )
                    continue

                vote_action = re.findall(r"(.+)-\s*\d+\s*YEAS", action_name)[0].strip()

                y = int(re.findall(r"(\d+)\s*YEAS", action_name)[0])
                n = int(re.findall(r"(\d+)\s*NAYS", action_name)[0])

                # get supplement number
                n_supplement = int(
                    re.findall(r"No\.\s*(\d+)", action_name, re.IGNORECASE)[0]
                )
                cached_vote = self.paper_vote_event(
                    bill,
                    chamber=actor,
                    start_date=action_date,
                    motion_text=vote_action,
                    result=vote_result(vote_action, y, n),
                    classification=classify_motion("ma", vote_action),
                )
                cached_vote.set_count("yes", y)
                cached_vote.set_count("no", n)

                # OPEN-169: the session goes into this URL WITHOUT its ordinal suffix.
                # `bill.legislative_session` is "194th" and produced
                # .../Journal/House/194th/2025/RollCalls, which is a 404. The site
                # wants .../Journal/House/194/2025/RollCalls, which returns the real
                # ~740KB year-aggregate PDF.
                #
                # The 404 was silent and that is the reason it survived: urlretrieve
                # saved the 404 HTML error page, convert_pdf turned it into junk text,
                # the "No. <n>" lookup in scrape_house_vote() missed, and that path
                # `return`s (not `return False`) -- so the caller treated it as success
                # and yielded a vote event with correct counts and ZERO voters. Tallies
                # looked right while every individual House vote was quietly dropped.
                housevote_pdf = (
                    "https://malegislature.gov/Journal/House/{}/{}/RollCalls".format(
                        re.sub(r"\D+$", "", bill.legislative_session), action_year
                    )
                )
                # OPEN-176: same rule as the Senate branch below -- the tally is
                # real, so record the vote either way and label it when the roll
                # call could not be read.
                #
                # The 34 House events that imported tally-only in MA 194th are all
                # 2026 supplements #237-#270, while every supplement up to #235
                # resolved. The year-aggregate journal PDF simply had not been
                # republished with the July sittings yet, so this is a source-side
                # lag rather than a parse failure: the same bills will fill in on a
                # later run, and until they do the gap is now visible instead of
                # looking like a complete vote.
                #
                # OPEN-443: that later run never came -- the year PDF was still
                # unchanged three months on. A roll call missing from it is now read
                # from its own sheet, by the same reader and totals check. The sheet's
                # bill line is not compared with this bill: No. 275 is printed as
                # "H. 5699, as amended" and is the vote stored on H 5700.
                voters_pdf = self.scrape_house_voters(
                    cached_vote, housevote_pdf, bill.legislative_session, n_supplement
                )
                if voters_pdf is None:
                    self.warning(
                        "MA House roll call unreadable for {} supplement #{}: {} -- "
                        "recording the tally with voters_unavailable".format(
                            bill.identifier, n_supplement, housevote_pdf
                        )
                    )
                    cached_vote.extras[
                        "voters_unavailable"
                    ] = "house-rollcall-unreadable"

                # The source is the PDF the voters came from. The dedupe key keeps the
                # year PDF's URL, so the 40 tally-only votes already stored are filled
                # in place rather than added again beside them.
                cached_vote.add_source(voters_pdf or housevote_pdf)
                cached_vote.dedupe_key = _house_vote_dedupe_key(
                    housevote_pdf, n_supplement, bill.identifier
                )
                yield cached_vote

            # Senate votes
            #
            # OPEN-176: a quorum roll call is not a vote on the bill. The two in
            # MA 194th are House counts, and they were minting Senate vote events
            # pointed at a House roll-call PDF -- 2 of the 118 Senate events that
            # imported a tally with nobody in it.
            if "Roll Call" in action_name and not _QUORUM_RE.search(action_name):
                actor = "upper"
                # placeholder
                vote_action = action_name.split(" -")[0]
                # 2019 H86 Breaks our regex,
                # Ordered to a third reading --
                # see Senate   Roll Call #25 and House Roll Call 56
                tally = parse_senate_tally(action_name)
                if tally is not None:
                    y, n, nay_label_ok = tally

                    # TODO: other count isn't included, set later
                    cached_vote = self.paper_vote_event(
                        bill,
                        chamber=actor,
                        start_date=action_date,
                        motion_text=vote_action,
                        result=vote_result(vote_action, y, n),
                        classification=classify_motion("ma", vote_action),
                    )
                    cached_vote.set_count("yes", y)
                    cached_vote.set_count("no", n)

                    # OPEN-176: derive the roll-call PDF from the number this
                    # action cites, not from the first link in the cell.
                    rollcall_pdf = senate_rollcall_url(
                        action_name, bill.legislative_session
                    )
                    read_voters = False
                    if rollcall_pdf:
                        read_voters = self.scrape_senate_vote(cached_vote, rollcall_pdf)

                    # OPEN-176/OPEN-177: the tally came from the action text and
                    # is real whatever the PDF does. Record the vote either way,
                    # and say plainly when nobody could be read from it.
                    #
                    # Dropping it instead -- which is what this branch used to do
                    # on a fetch failure -- is how OPEN-177's H 4530 and S 2903
                    # ended up citing a Senate roll call while holding no Senate
                    # vote at all: SenateRollCall70.pdf and SenateRollCall128.pdf
                    # both failed to fetch during the 2026-08-12 run, and each
                    # took its whole vote with it. A silent absence is worse than
                    # a labelled gap, because only the labelled one can be found
                    # again.
                    if not read_voters:
                        self.warning(
                            "MA Senate roll call unreadable for {} on {}: {} -- "
                            "recording the tally with voters_unavailable".format(
                                bill.identifier,
                                action_date,
                                rollcall_pdf or "no roll-call number in action text",
                            )
                        )
                        cached_vote.extras[
                            "voters_unavailable"
                        ] = "senate-rollcall-unreadable"

                    # OPEN-177: S 2565 reads "Yeas 39 to Yeas 0" -- the source
                    # labels its own nay count as yeas. The number is still
                    # recorded, but say that we inferred what it meant. This
                    # matters most in exactly the case above, where there are no
                    # voters to corroborate it against: without this, an inferred
                    # tally and a sourced one look identical.
                    if not nay_label_ok:
                        cached_vote.extras[
                            "tally_label_inferred"
                        ] = "source labelled the nay count as yeas"

                    # A VoteEvent needs a source. When the action cites no
                    # roll-call number there is no roll-call URL to give it, so
                    # fall back to the bill's own page -- which is where the
                    # claim actually came from.
                    #
                    # No Massachusetts action currently takes this path: of the
                    # 236 roll-call actions in the 194th, 2 are quorum calls
                    # (excluded above) and all 234 that would produce a vote
                    # carry a `Roll Call #<n>`. It exists so a future change in
                    # how the site cites roll calls degrades to a labelled vote
                    # rather than to a crash or a silent drop.
                    #
                    # The dedupe key folds in the action text because date and
                    # tally alone do not identify a roll call -- two votes on one
                    # bill on one day can share a tally, and collapsing them
                    # would silently merge two real votes. That is a worse
                    # failure than the one this branch exists to handle.
                    fallback_source = (
                        bill.sources[0]["url"]
                        if bill.sources
                        else "https://malegislature.gov"
                    )
                    cached_vote.add_source(rollcall_pdf or fallback_source)
                    cached_vote.dedupe_key = _senate_vote_dedupe_key(
                        rollcall_pdf,
                        fallback_source,
                        action_date,
                        action_name,
                        bill.identifier,
                    )
                    yield cached_vote

            attrs = self.categorizer.categorize(action_name)
            action = bill.add_action(
                action_name.strip(),
                action_date,
                chamber=action_actor,
                classification=attrs["classification"],
            )
            for com in attrs.get("committees", []):
                com = com.strip()
                action.add_related_entity(com, entity_type="organization")

    def get_house_pdf(self, vurl):
        """cache house PDFs: the year PDF serves every roll call in it"""
        if vurl not in self.house_pdf_cache:
            try:
                (path, resp) = self.urlretrieve(vurl)
            except requests.exceptions.RequestException:
                self.warning("Server Error on {}".format(vurl))
                return None
            pdflines = convert_pdf(path, "text")
            os.remove(path)
            self.house_pdf_cache[vurl] = pdflines.decode("utf-8").replace("\u2019", "'")
        return self.house_pdf_cache[vurl]

    def scrape_house_voters(self, vote, housevote_pdf, session, supplement):
        """Attach the House voters of roll call `supplement` to `vote`, from the year
        PDF or, when it is not there, from the roll call's own sheet (OPEN-443).

        Returns the URL of the PDF the voters were read from, or None when neither
        could be read.
        """
        if self.scrape_house_vote(vote, housevote_pdf, supplement):
            return housevote_pdf
        sheet_pdf = _HOUSE_ROLLCALL_URL.format(re.sub(r"\D+$", "", session), supplement)
        if self.scrape_house_vote(vote, sheet_pdf, supplement):
            return sheet_pdf
        return None

    def scrape_house_vote(self, vote, vurl, supplement):
        """Attach individual House voters to `vote`.

        OPEN-176: returns True only when at least one voter was actually
        attached. Every failure path now returns False.

        This used to be three different answers to one question. A failed fetch
        returned False, a missing supplement did a bare `return` (None), and a
        parse that read the PDF but produced no voters returned None as well --
        while the caller tested `is False`. So two of the three failures were
        indistinguishable from success, and yielded a vote event carrying the
        action's tally and an empty voter list. That is the mechanism behind
        every one of the 152 tally-only Massachusetts roll calls, and it is why
        they accumulated with nothing flagging them.
        """
        pdflines = self.get_house_pdf(vurl)
        if pdflines is None:
            return False
        # get pdf data from supplement number
        try:
            vote_text = pdflines.split("No. " + str(supplement))[1].split(
                "MASSACHUSETTS"
            )[0]
        except IndexError:
            self.info("No vote found in supplement for vote #%s" % supplement)
            return False

        # OPEN-474: read each "<letter> <name>" cell of the grid together. This
        # used to split rows on three spaces and zip the letters with the names; a
        # cell printed with one space ("X Silvia") became a name "X Silvia" with no
        # letter, and every later voter in that roll call got the letter of the
        # voter after them. OPEN-442: the grid and the sheet's own "No. <n>  <y>
        # YEAS  <n> NAYS  <x> N/V" header are read by votes.py's parser, the one
        # reader of a House roll-call sheet. The split above removed "No. <n>", so
        # it is put back for the parser to find the header line.
        sheet = HouseVoteRecordParser(
            "No. {}{}".format(supplement, vote_text), session=vote.legislative_session
        )
        # OPEN-810: the Speaker's name comes only from the manifest; a session it does not
        # list leaves "Mr. Speaker" unmatched, said once per session per run
        warned = self.__dict__.setdefault("_warned_speaker_sessions", set())
        session = vote.legislative_session
        if SPEAKER_TITLE in sheet.names and session not in warned:
            warned.add(session)
            self.warning(
                "OPEN-810: manifest ma.votes.house_speaker_by_session has no %s; "
                "%r left as printed",
                session,
                SPEAKER_TITLE,
            )
        for letter, name in zip(sheet.votes, sheet.names):
            if letter == "Y":
                vote.yes(name)
            elif letter == "N":
                vote.no(name)
            else:
                # X (not voting) and P (present), as before
                vote.vote("other", name)

        # OPEN-442: the caller set the tally from the House action text, which for
        # 16 of 234 roll calls read in the 194th disagrees with the sheet (S 3106 No.
        # 221: the action says 139 yeas, the sheet and its voters 149). When the
        # voters read equal the sheet's declared totals, the sheet is the tally;
        # otherwise the action text's stays. Only the counts change: the result is
        # left as the caller set it, because a simple majority of the sheet's
        # numbers is not the outcome of a motion that needs two thirds.
        if sheet.totals_mismatch() is None:
            vote.set_count("yes", sheet.total_yea)
            vote.set_count("no", sheet.total_nay)

        # OPEN-176: a PDF that read cleanly but named nobody is a failure, not a
        # unanimous silence.
        return bool(sheet.votes)

    def scrape_senate_vote(self, vote, vurl):
        """Attach individual Senate voters to `vote`.

        OPEN-176: returns True only when at least one voter was attached, for
        the same reason as `scrape_house_vote()` above.
        """
        # download file to server
        try:
            (path, resp) = self.urlretrieve(vurl)
        except requests.exceptions.RequestException:
            self.warning("Server Error on {}".format(vurl))
            return False
        pdflines = convert_pdf(path, "text")
        os.remove(path)

        # for y, n
        mode = None
        attached = 0

        lines = pdflines.splitlines()

        # handle individual lines in pdf to id legislator votes
        for line in lines:
            line = line.strip()
            line = line.decode("utf-8").replace("\u2212", "-")
            if line == "":
                continue
            # change mode accordingly
            elif line.startswith("YEAS"):
                mode = "y"
            elif line.startswith("NAYS"):
                mode = "n"
            elif line.startswith("ABSENT OR"):
                mode = "o"
            # else parse line with names
            else:
                nameline = line.split("   ")

                for raw_name in nameline:
                    raw_name = raw_name.strip()
                    if raw_name == "":
                        continue

                    # handles vote count lines
                    cut_name = raw_name.split("-")
                    clean_name = ""
                    if cut_name[-1].strip(" .").isdigit():
                        del cut_name[-1]
                        clean_name = "".join(cut_name)
                    else:
                        clean_name = raw_name.strip()
                    # OPEN-474: "Keenan, John F." -> "John F. Keenan", the form
                    # the people data holds
                    clean_name = senate_voter_name(clean_name)
                    # update vote object with names
                    if mode == "y":
                        vote.yes(clean_name)
                        attached += 1
                    elif mode == "n":
                        vote.no(clean_name)
                        attached += 1
                    elif mode == "o":
                        vote.vote("other", clean_name)
                        attached += 1

        # OPEN-176: an HTML error page or an amendment modal converts to text
        # without raising, reaches this loop, and matches none of the YEAS/NAYS
        # section headers -- so `attached` stays 0 and the caller is told the
        # roll call could not be read, instead of being handed a vote with
        # nobody in it.
        return attached > 0

    def get_as_ajax(self, url):
        # set the X-Requested-With:XMLHttpRequest so the server only sends along the bits we want
        s = checked_requests.Session()
        s.headers.update({"X-Requested-With": "XMLHttpRequest"})
        try:
            return s.get(url)
        except requests.exceptions.RequestException:
            self.warning("Server Error on {}".format(url))
            return None

    def replace_non_digits(self, str):
        return re.sub(r"[^\d]", "", str).strip()
