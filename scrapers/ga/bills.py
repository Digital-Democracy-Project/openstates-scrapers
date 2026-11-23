import datetime
import re
import requests
from collections import defaultdict

import pytz
from openstates.exceptions import EmptyScrape
from openstates.scrape import Scraper, Bill, VoteEvent
from classify_motion import classify_motion, needs_two_thirds

from .util import (
    get_client,
    get_url,
    backoff,
    get_token,
    published_session_id,
    SESSION_SITE_IDS,
    SPECIAL_SESSION_SITE_URL_PARTS,
)

#         Methods (7):
#            GetLegislationDetail(xs:int LegislationId, )
#
#            GetLegislationDetailByDescription(ns2:DocumentType DocumentType,
#                                              xs:int Number, xs:int SessionId)
#
#            GetLegislationForSession(xs:int SessionId, )
#
#            GetLegislationRange(ns2:LegislationIndexRangeSet Range, )
#
#            GetLegislationRanges(xs:int SessionId,
#                           ns2:DocumentType DocumentType, xs:int RangeSize, )
#
#            GetLegislationSearchResultsPaged(ns2:LegislationSearchConstraints
#                                               Constraints, xs:int PageSize,
#                                               xs:int StartIndex, )
#            GetTitles()


member_cache = {}
SOURCE_URL = "https://www.legis.ga.gov/legislation/{bid}"

vote_name_pattern = re.compile(r"(.*), (\d+(?:ST|ND|RD|TH))", re.IGNORECASE)

OUTCOME_STATUS = r"Reconsidered|Passed|Adopted|Agreed|Lost"
# "Local Calendar", "Previous Local Calendar", "LOCAL CONSENT CALENDAR"
CALENDAR = re.compile(r"calendar", re.IGNORECASE)
# Ga. Const. art. V, sec. II, para. IV: a veto is overridden by two thirds of the members
# to which each house is entitled (House 180 seats, Senate 56), not of those voting.
TWO_THIRDS_OF_MEMBERS = {"House": 120, "Senate": 38}

# OPEN-604: catch-up runs. Georgia's service dates are Eastern local time, and its search
# compares them by calendar day (both ends inclusive, the time of day ignored; measured
# 2026-11-16). Georgia publishes some records days after the date they carry, so a run
# cannot ask only for what is dated since the last run. Measured on 2025_26 from the
# publish order (a record whose id follows one dated later was published after it):
# House Votes #113-#122 (HB 307 and nine more, 2025-02-28 10:11-11:12) came after Senate
# Vote #134 (2025-03-03 20:37), at least 3 days 9-10 h late, the most of any of the 1,870
# roll calls (none other is a day late); SB 185 and SB 201's "Signed by Governor"
# (2025-05-08 11:28) came after a status dated 2025-05-09 16:13, at least 28 h 45 m late.
# These are lower bounds. Seven days of lookback, at worst about 6.5 days before the
# previous run listed its bills (12 h runs, start = watermark - 1 h), covers both.
# A correction entered months later (SR 5's 2025-01-13 statuses, entered in May 2025)
# is out of reach of any lookback: only a full walk picks it up.
EASTERN = pytz.timezone("America/New_York")
CHANGED_LOOKBACK = datetime.timedelta(days=7)
# the service refuses a page size over 250; StartIndex is a row offset
SEARCH_PAGE_SIZE = 250


def changed_cutoff(start):
    """The first Eastern day a catch-up run asks for, from the runners' start= (UTC)."""
    start_dt = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
    eastern = pytz.utc.localize(start_dt).astimezone(EASTERN)
    return eastern.date() - CHANGED_LOOKBACK


def bills_voted_since(cutoff, votes, index):
    """Ids of the bills with a roll call dated on or after the cutoff day.

    A roll call does not always add a status: SB 8 (2025_26) has the Senate's 26-26 vote to
    agree to the House substitute (2026-04-02, #964) and no status after 2026-03-27, so the
    status filter alone misses it. votes are GetVotes' listings; their Legislation is the
    bill ("SB 8", the index's Description), or empty for a vote on no bill.
    """
    ids = {leg["Description"]: leg["Id"] for leg in index}
    return {
        ids[v["Legislation"].strip()]
        for v in votes
        if v["Legislation"]
        and v["Legislation"].strip() in ids
        and v["Date"].date() >= cutoff
    }


def vote_classification(caption, reconsidered=False):
    """Classify a vote from its Caption, the motion voted on.

    The rules are the ga block of config/motion_classification.yaml. One case the
    caption cannot tell: the House reconsiders a local calendar under the same caption
    ("Local Calendar"), so a calendar roll call that pair_outcomes() pairs with a
    "Reconsidered" status is the reconsideration, not passage.
    """
    classification = classify_motion("ga", caption)
    if reconsidered and classification == ["passage"]:
        return []
    return classification


def vote_result(listed_vote, lost):
    """The result, "pass" or "fail", of one roll call.

    lost: pair_outcomes() paired it with a "Lost" status. A motion in the ga block's
    two_thirds list (a veto override) needs two thirds of the chamber's members, so a
    majority is not enough: HB 1192's override (2026_ss, House #11) won 94-77 and failed.
    Anything else passes on yeas > nays, as before.
    """
    if lost:
        return "fail"
    if needs_two_thirds("ga", listed_vote["Caption"] or ""):
        needed = TWO_THIRDS_OF_MEMBERS[listed_vote["Branch"]]
        return "pass" if listed_vote["Yeas"] >= needed else "fail"
    return "pass" if listed_vote["Yeas"] > listed_vote["Nays"] else "fail"


def pair_outcomes(listed_votes, history):
    """Pair a bill's passage votes with the outcomes in its status history.

    GetVote has no result, and yeas > nays isn't enough to pass (HB 1324: 87-76,
    short of the 91 needed). The status history logs each outcome ("House Third
    Reading Lost", "House Reconsidered", "Senate Passed/Adopted") minutes to an
    hour after the vote, so pair a chamber's outcomes for the day, in order, with
    its passage votes for the day, in order. Returns the ids of the votes paired
    with a "Lost" status, and of the calendar votes paired with a "Reconsidered"
    one ("House Lost Reconsidered Bill/Resolution" is the failed vote after it).

    A "Reconsidered" status pairs only with a House calendar vote: any other
    reconsideration has its own caption ("Reconsider", "Recon SB 234, 235, & 336",
    the Senate's "MOTION TO RECONSIDER LOCAL CONSENT CALENDAR"), is not a passage
    vote, and the re-vote after it gets its own outcome (SB 234, 2025: "House
    Reconsidered" 19:18, then "House Passed/Adopted" 19:22).
    """
    lost, reconsidered = set(), set()
    unpaired = sorted(
        (
            v
            for v in listed_votes
            if vote_classification(v["Caption"] or "") == ["passage"]
        ),
        key=lambda v: v["Date"],
    )
    for status in sorted(history, key=lambda s: s["Date"]):
        branch = {"H": "House", "S": "Senate"}.get(status["Code"][0])
        if not branch or not re.search(OUTCOME_STATUS, status["Description"]):
            continue
        is_lost = "Lost" in status["Description"]
        is_reconsidered = not is_lost and "Reconsidered" in status["Description"]
        for v in unpaired:
            if (
                v["Branch"] == branch
                and v["Date"].date() == status["Date"].date()
                and v["Date"] <= status["Date"]
                and (
                    not is_reconsidered
                    or (branch == "House" and CALENDAR.search(v["Caption"] or ""))
                )
            ):
                unpaired.remove(v)
                if is_lost:
                    lost.add(v["VoteId"])
                elif is_reconsidered:
                    reconsidered.add(v["VoteId"])
                break
    return lost, reconsidered


class GABillScraper(Scraper):
    lclient = get_client("Legislation")
    lservice = lclient.service
    vservice = get_client("Votes").service
    mservice = get_client("Members").service
    lsource = get_url("Legislation")
    msource = get_url("Members")
    vsource = get_url("Votes")

    def get_member(self, member_id):
        if member_id in member_cache:
            return member_cache[member_id]

        mem = backoff(self.mservice.GetMember, member_id)
        member_cache[member_id] = mem
        return mem

    def search_current_status(self, session_id, cutoff):
        """Ids of the session's bills whose current status is dated on or after the cutoff
        day (GetLegislationSearchResultsPaged with a CurrentStatusConstraint).

        Only the current status can be searched: an ExistingStatusConstraint (any status in
        the range) fails on the service with "Object reference not set to an instance of an
        object" (2026-11-16). The current status is the one with the latest date, so a
        status dated on or after the cutoff leaves the current one on or after it too: a
        status entered since the last run is found when its date is within the lookback
        (CHANGED_LOOKBACK). One entered with an older date than that (SR 5's, four months
        late) is found only by a full walk. The open-ended DateEnd keeps a later status from hiding one in range.
        """
        constraints = self.lclient.factory.create("ns2:LegislationSearchConstraints")
        constraints.Session.Id = session_id
        status = self.lclient.factory.create("ns2:CurrentStatusConstraint")
        status.Status = "Any"
        status.DateStart = datetime.datetime.combine(cutoff, datetime.time())
        status.DateEnd = datetime.datetime(cutoff.year + 10, 1, 1)
        constraints.StatusConstraints.StatusConstraint.append(status)

        ids, offset = set(), 0
        while True:
            result = backoff(
                self.lservice.GetLegislationSearchResultsPaged,
                constraints,
                SEARCH_PAGE_SIZE,
                offset,
            )
            page = result["Page"]["LegislationSearchResult"] if result["Page"] else []
            ids.update(row["Id"] for row in page)
            offset += len(page)
            if not page or offset >= result["Total"]:
                break
        # a short or overlapping listing cannot say which bills changed (pm-review)
        if len(ids) < result["Total"]:
            raise ValueError(
                "search listed %d of %d bills" % (len(ids), result["Total"])
            )
        return ids

    def changed_since(self, session_id, start, legislation):
        """OPEN-604: ids of the bills to read on a catch-up run (a status or a roll call
        since start=), or None for a full walk when the service cannot say."""
        try:
            cutoff = changed_cutoff(start)
        except ValueError:
            self.warning("GA OPEN-604: invalid start=%r, doing a full walk", start)
            return None
        try:
            by_status = self.search_current_status(session_id, cutoff)
            votes = []
            for branch in ("House", "Senate"):
                # an empty answer is a failure, not "no roll calls" (pm-review): a
                # chamber's list is never empty after its first day
                votes += backoff(self.vservice.GetVotes, branch, session_id)[
                    "VoteListing"
                ]
            by_vote = bills_voted_since(cutoff, votes, legislation)
        except Exception as e:
            self.warning(
                "GA OPEN-604: could not list the changed bills (%s), doing a full walk",
                e,
            )
            return None
        changed = by_status | by_vote
        self.info(
            "GA OPEN-604: %d of %d bills changed since %s (start=%s, Eastern day minus "
            "%s): %d by status, %d more by roll call only",
            len(changed),
            len(legislation),
            cutoff,
            start,
            CHANGED_LOOKBACK,
            len(by_status),
            len(by_vote - by_status),
        )
        return changed

    def scrape_subjects(self, session_id):
        """Build a mapping of legislation_id -> [subject names] via the REST API."""
        self._subjects = defaultdict(list)
        headers = {
            "Authorization": get_token(),
            "Content-Type": "application/json",
        }

        try:
            titles_resp = requests.get(
                "https://www.legis.ga.gov/api/georgia-code/titles",
                headers=headers,
                timeout=30,
            )
            titles = titles_resp.json()
        except Exception:
            self.warning("Could not load subject titles, skipping subjects.")
            return

        self.info(f"Found {len(titles)} subject categories")

        for title in titles:
            title_name = title["name"].strip()
            title_id = title["id"]

            try:
                page = 0
                while True:
                    resp = requests.post(
                        f"https://www.legis.ga.gov/api/Legislation/Search/250/{page}",
                        json={"sessionId": session_id, "titleIds": [title_id]},
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break

                    for r in results:
                        lid = r["legislationId"]
                        self._subjects[lid].append(title_name)

                    if len(results) < 250:
                        break
                    page += 1
            except Exception:
                self.warning(
                    f"Could not load bills for subject '{title_name}', skipping."
                )
                continue

        self.info(f"Loaded subjects for {len(self._subjects)} bills")

    def scrape(self, session=None, chamber=None, start=None):
        bill_type_map = {
            "B": "bill",
            "R": "resolution",
            "JR": "joint resolution",
            "CR": "concurrent resolution",
        }

        chamber_map = {
            "H": "lower",
            "S": "upper",
            "J": "joint",
            "E": "legislature",  # Effective date
        }

        action_code_map = {
            "HI": None,
            "SI": None,
            "HH": ["introduction"],
            "SH": ["introduction"],
            "HPF": ["filing"],
            "HDSAS": None,
            "SPF": ["filing"],
            "HSR": ["reading-2"],
            "SSR": ["reading-2"],
            "HFR": ["reading-1"],
            "SFR": ["reading-1"],
            "HRECM": ["withdrawal", "referral-committee"],
            "SRECM": ["withdrawal", "referral-committee"],
            "SW&C": ["withdrawal", "referral-committee"],
            "HW&C": ["withdrawal", "referral-committee"],
            "HRA": ["passage"],
            "SRA": ["passage"],
            "HPA": ["passage"],
            "HRECO": None,
            "SPA": ["passage"],
            "HTABL": None,  # 'House Tabled' - what is this?
            "SDHAS": None,
            "HCFR": ["committee-passage-favorable"],
            "SCFR": ["committee-passage-favorable"],
            "HRAR": ["referral-committee"],
            "SRAR": ["referral-committee"],
            "STR": ["reading-3"],
            "SAHAS": ["concurrence"],
            "SE": ["passage"],
            "SR": ["referral-committee"],
            "HTRL": ["reading-3", "failure"],
            "HTR": ["reading-3"],
            "S3RLT": ["reading-3", "failure"],
            "HASAS": ["concurrence"],
            "S3RPP": None,
            "STAB": None,
            "SRECO": None,
            "SAPPT": None,
            "HCA": None,
            "HNOM": None,
            "HTT": None,
            "STT": None,
            "SRECP": None,
            "SCRA": None,
            "SNOM": None,
            "S2R": ["reading-2"],
            "H2R": ["reading-2"],
            # engrossment closes a bill to amendment before third reading
            "SENG": None,
            "HENG": None,
            "HPOST": None,
            "HCAP": None,
            "SDSG": ["executive-signature"],
            "SSG": ["executive-receipt"],
            "Signed Gov": ["executive-signature"],
            "HDSG": ["executive-signature"],
            "HSG": ["executive-receipt"],
            "EFF": None,
            "HRP": None,
            "STH": None,
            "HTS": None,
        }
        sid = SESSION_SITE_IDS.get(session)
        if sid is None:
            # OPEN-605: a session we list before Georgia publishes it (2027_28): its id comes from
            # Georgia's own session list; until Georgia lists it there are no bills to read yet.
            name = next(
                s["_scraped_name"]
                for s in self.jurisdiction.legislative_sessions
                if s["identifier"] == session
            )
            sid = published_session_id(name)
            if sid is None:
                self.warning(
                    "GA OPEN-605: Georgia does not list %r yet; no bills to read", name
                )
                raise EmptyScrape

        legislation = backoff(self.lservice.GetLegislationForSession, sid)[
            "LegislationIndex"
        ]

        # OPEN-604: the runners append start=<watermark> on every run after the first. With
        # it, only the bills with a status or a roll call since then are read; without it
        # (or if the service cannot list them) every bill is, as before.
        changed = self.changed_since(sid, start, legislation) if start else None
        if changed is not None:
            listed = len(legislation)
            legislation = [leg for leg in legislation if leg["Id"] in changed]
            # A quiet week is a real answer, not a broken scrape: tell do_scrape() so (as
            # PA, OPEN-574). An empty session index still fails as before.
            if listed and not legislation:
                self.info("GA OPEN-604: no bill changed since %s", start)
                raise EmptyScrape

        self.scrape_subjects(sid)

        for leg in legislation:
            lid = leg["Id"]
            instrument = backoff(self.lservice.GetLegislationDetail, lid)
            history = [x for x in instrument["StatusHistory"][0]]

            actions = reversed(
                [
                    {
                        "code": x["Code"],
                        "action": x["Description"],
                        "_guid": x["Id"],
                        "date": x["Date"],
                    }
                    for x in history
                ]
            )

            guid = instrument["Id"]

            # A little bit hacky.
            bill_prefix = instrument["DocumentType"]
            bill_chamber = chamber_map[bill_prefix[0]]
            bill_type = bill_type_map[bill_prefix[1:]]

            bill_id = "%s %s" % (bill_prefix, instrument["Number"])
            if instrument["Suffix"]:
                bill_id += instrument["Suffix"]

            # special session bills get a suffix that doesn't show up in the site
            bill_id = bill_id.replace("EX", "")

            title = instrument["Caption"]
            description = instrument["Summary"]

            if title is None:
                continue

            bill = Bill(
                bill_id,
                legislative_session=session,
                chamber=bill_chamber,
                title=title,
                classification=bill_type,
            )
            bill.add_abstract(description, note="description")
            bill.extras = {"guid": guid}

            if instrument["Votes"]:
                listed_votes = [
                    backoff(self.vservice.GetVote, v["VoteId"])
                    for v in instrument["Votes"]["VoteListing"]
                ]

                lost_votes, reconsidered_votes = pair_outcomes(listed_votes, history)

                for listed_vote in listed_votes:
                    date = listed_vote["Date"].strftime("%Y-%m-%d")
                    # Description is the roll call ("House Vote #665 - ..."),
                    # Caption the motion ("PASSAGE", "MOTION TO ENGROSS")
                    identifier = listed_vote["Description"] or str(
                        listed_vote["VoteId"]
                    )
                    caption = (listed_vote["Caption"] or "").strip()

                    result = vote_result(
                        listed_vote, listed_vote["VoteId"] in lost_votes
                    )

                    vote = VoteEvent(
                        start_date=date,
                        motion_text=caption or identifier,
                        identifier=identifier,
                        chamber={"House": "lower", "Senate": "upper"}[
                            listed_vote["Branch"]
                        ],
                        result=result,
                        classification=vote_classification(
                            caption, listed_vote["VoteId"] in reconsidered_votes
                        ),
                        bill=bill,
                    )
                    vote.set_count("yes", listed_vote["Yeas"])
                    vote.set_count("no", listed_vote["Nays"])

                    vote.add_source(self.vsource, note="api")
                    # captions repeat on a bill and day, the roll call doesn't
                    vote.dedupe_key = f"{bill}#{date}#{identifier}"

                    methods = {"Yea": "yes", "Nay": "no"}

                    # the source counts vacant seats as NotVoting
                    vacant = 0
                    if listed_vote["Votes"] is not None:
                        for vdetail in listed_vote["Votes"][0]:
                            whom = vdetail["Member"]
                            how = vdetail["MemberVoted"]
                            if whom["Name"] == "VACANT":
                                vacant += 1
                                continue
                            district = vote_name_pattern.search(whom["Name"]).group(2)
                            member = self.get_member(whom["Id"])
                            name = "{First} {Last}".format(**dict(member["Name"]))
                            vote.vote(methods.get(how, "other"), name, note=district)
                    vote.set_count(
                        "other",
                        listed_vote["Excused"] + listed_vote["NotVoting"] - vacant,
                    )

                    yield vote

            ccommittees = defaultdict(list)
            committees = instrument["Committees"]
            if committees:
                for committee in committees[0]:
                    ccommittees[
                        {"House": "lower", "Senate": "upper"}[committee["Type"]]
                    ].append(committee["Name"])

            for action in actions:
                action_chamber = chamber_map[action["code"][0]]

                try:
                    action_types = action_code_map[action["code"]]
                except KeyError:
                    error_msg = (
                        "Code {code} for action {action} not recognized.".format(
                            code=action["code"], action=action["action"]
                        )
                    )

                    self.logger.warning(error_msg)

                    action_types = None

                # vetos carry the same status as executive signed, "Signed Gov".
                # see https://www.legis.ga.gov/legislation/64713
                if "veto" in action["action"].lower():
                    action_types = ["executive-veto"]

                committees = []
                if action_types and any(("committee" in x for x in action_types)):
                    committees = [str(x) for x in ccommittees.get(action_chamber, [])]

                act = bill.add_action(
                    action["action"],
                    action["date"].strftime("%Y-%m-%d"),
                    classification=action_types,
                    chamber=action_chamber,
                )
                for committee in committees:
                    act.add_related_entity(committee, "organization")
                act.extras = {"code": action["code"], "guid": action["_guid"]}

                if action["action"].startswith("Act "):
                    act_year = action["date"].strftime("%Y")
                    bill.add_citation(
                        f"Acts of Georgia, {act_year}",
                        action["action"],
                        citation_type="chapter",
                    )

            sponsors = []
            if instrument["Authors"]:
                sponsors = instrument["Authors"]["Sponsorship"]
                if "Sponsors" in instrument and instrument["Sponsors"]:
                    sponsors += instrument["Sponsors"]["Sponsorship"]

            # 4976 is Sheila McNeill
            # whose profile is currently causing 500 errors
            sponsors = [
                (x["Type"], self.get_member(x["MemberId"]))
                for x in sponsors
                if x["MemberId"] != 4976
            ]

            for typ, sponsor in sponsors:
                name = "{First} {Last}".format(**dict(sponsor["Name"]))
                bill.add_sponsorship(
                    name,
                    entity_type="person",
                    classification="primary" if "Author" in typ else "secondary",
                    primary="Author" in typ,
                )

            for version in instrument["Versions"]["DocumentDescription"]:
                name, url, doc_id, version_id = [
                    version[x] for x in ["Description", "Url", "Id", "Version"]
                ]
                if session == "2021_ss":
                    # gets http://www.legis.ga.gov/Legislation/2021EX/202712.pdf
                    # need https://www.legis.ga.gov/api/legislation/document/2021EX/202712
                    bill_bit = re.search(r"n/(.*)\.pdf", url).group(1)
                    url = (
                        f"https://www.legis.ga.gov/api/legislation/document/{bill_bit}"
                    )
                if session in ["2023_ss", "2026_ss"]:
                    # Last couple special sessions the url provided in instrument["Versions"]["DocumentDescription"]
                    # is wrong, so it'll look like http://www.legis.ga.gov/Legislation/2026EX/249298.pdf
                    # but that URL does not resolve (gets 404 on GA page)
                    # the web UI actually gets to you to a path that uses a varient session ID and the doc_id
                    # like https://www.legis.ga.gov/api/legislation/document/2026EX/249298
                    url = f"https://www.legis.ga.gov/api/legislation/document/{SPECIAL_SESSION_SITE_URL_PARTS[session]}/{doc_id}"
                link = bill.add_version_link(name, url, media_type="application/pdf")
                link["extras"] = {
                    "_internal_document_id": doc_id,
                    "_version_id": version_id,
                }

            for subject in self._subjects.get(lid, []):
                bill.add_subject(subject)

            bill.add_source(self.msource, note="api")
            bill.add_source(self.lsource, note="api")
            bill.add_source(SOURCE_URL.format(**{"session": session, "bid": guid}))

            yield bill
