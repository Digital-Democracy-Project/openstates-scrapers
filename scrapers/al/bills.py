import pytz
import json
import lxml
import re
import dateutil
import requests
from openstates.scrape import Scraper, Bill, VoteEvent
from openstates.exceptions import EmptyScrape
from utils.media import get_media_type
from classify_motion import classify_motion
from .actions import Categorizer

# OPEN-527: a "Motion to Adopt" on a history row that names an amendment or substitute (amdSub)
# adopts that amendment; without one it adopts a resolution, which classify_motion() calls passage.
AMENDMENT_ADOPTION = re.compile(r"\bmotion to adopt\b", re.I)


# OPEN-863: ALISON leaves amdSub empty on some adoptions of an amendment or substitute (HB 605 Senate
# "Chesteen motion to Adopt - Adopted Roll Call 1316", SB 146 Senate "Albritton motion to adopt-
# Adopted Roll Call 813"). Those follow the row that offers the paper, the same day in the same chamber.
PAPER_OFFERED = re.compile(r"\b(?:amendment|substitute) offered\b", re.I)


def vote_classification(action_row: dict, after_offer: bool = False) -> list:
    if (action_row.get("amdSub") or after_offer) and AMENDMENT_ADOPTION.search(
        action_row["matter"]
    ):
        return ["amendment"]
    # the rest of the rules live in config/motion_classification.yaml (al block)
    return classify_motion("al", action_row["matter"])


# OPEN-563: ALISON writes each roll call's outcome into the history row ("... - Adopted Roll
# Call 369", "... - Lost Roll Call 520", "LocalCertificationResolutionAdopted", "BIR Lost in
# House of Origin"). On local bills most House members abstain, so a count would call adopted
# votes failed; the count is only the fallback for a row that names no outcome, and there
# (Ramon, 2026-11-15) more yeas than nays passes: abstentions do not count against the motion.
VOTE_OUTCOME = re.compile(r"adopted\b|\blost\b", re.I)


def vote_result(matter: str, yeas: int, nays: int) -> str:
    outcomes = VOTE_OUTCOME.findall(matter or "")
    if outcomes:
        return "fail" if outcomes[-1].lower() == "lost" else "pass"
    return "pass" if yeas > nays else "fail"


# OPEN-569: an amendment or substitute paper is a version of the bill only if it became part of it.
# ALISON lists the paper (amdSubFileUrl) on every history row that acts on it: the committee report
# or floor offer that introduces it, then the floor motion on it ("Motion to Adopt - Adopted Roll Call
# 895", "Moore (M) motion to Table - Adopted Voice Vote"); an adoption row right after the paper's
# row that names no paper is the vote on it too. A paper the floor adopted is a version; one
# offered on the floor and never adopted (tabled, lost, withdrawn) is a document. A paper only a
# committee acted on (reported out, never offered on the floor) stays a version: it is the bill as
# the committee reported it.
FLOOR_ACTION = re.compile(r"\boffered\b|\bmotion to\b", re.I)


def paper_is_version(rows: list) -> bool:
    for row in rows:
        outcomes = VOTE_OUTCOME.findall(row["matter"])
        if (
            AMENDMENT_ADOPTION.search(row["matter"])
            and outcomes
            and outcomes[-1].lower() == "adopted"
        ):
            return True
    return not any(FLOOR_ACTION.search(row["matter"]) for row in rows)


# OPEN-569: the date of each of the bill's own printings, from the history row that marks it, so
# openstates-core can order Alabama's versions by date (its versions had none, and the papers'
# names cannot be placed in time). Introduced: the prefiled date, else the first history row.
# Engrossed: the "Engrossed" row, else the first passage in the house of origin. Enrolled: the
# first "Enrolled" row, else the last "Ready to Enroll". Empty when no row says.
PASSAGE = re.compile(r"\bthird time and pass\b.*\badopted\b", re.I)


def version_dates(bill_row: dict, histories: list) -> dict:
    def day(row):
        return dateutil.parser.parse(row["calendarDate"]).strftime("%Y-%m-%d")

    def first(rows):
        return day(rows[0]) if rows else ""

    matters = [(row.get("matter") or "").strip() for row in histories]
    introduced = (
        dateutil.parser.parse(bill_row["prefiledDate"]).strftime("%Y-%m-%d")
        if bill_row.get("prefiledDate")
        else first(histories)
    )
    engrossed = first(
        [r for r, m in zip(histories, matters) if m == "Engrossed"]
    ) or first([r for r, m in zip(histories, matters) if PASSAGE.search(m)])
    enrolled = first(
        [r for r, m in zip(histories, matters) if m == "Enrolled"]
    ) or first([r for r, m in zip(histories, matters) if m == "Ready to Enroll"][-1:])
    return {"Introduced": introduced, "Engrossed": engrossed, "Enrolled": enrolled}


AL_COMPANION_LABEL = "Companion Bill"


class ALBillScraper(Scraper):
    categorizer = Categorizer()
    chamber_map = {"Senate": "upper", "House": "lower"}
    bill_types = {"B": "bill", "R": "resolution"}
    vote_types = {"P": "not voting", "A": "abstain", "Y": "yes", "N": "no"}
    tz = pytz.timezone("US/Eastern")
    chamber_map_short = {"S": "upper", "H": "lower"}
    gql_url = "https://alison.legislature.state.al.us/graphql"
    session_year = ""
    session_type = ""
    session_identifier = ""
    bill_ids = set()
    vote_keys = set()
    count = 0

    gql_headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        # "Authorization": "Bearer undefined",  # as of 12/4/25, this header causes "invalid token" error
        "Content-Type": "application/json",
        "Origin": "https://alison.legislature.state.al.us",
        "Referer": "https://alison.legislature.state.al.us/",
    }

    def scrape(self, session):
        scraper_ids = self.jurisdiction.get_scraper_ids(session)
        self.session_year = scraper_ids["session_year"]
        self.session_type = scraper_ids["session_type"]
        self.session_identifier = session

        for bill_type in ["B", "R"]:
            yield from self.scrape_bill_type(session, bill_type, 0, 50)

        if self.count == 0:
            raise EmptyScrape

    def scrape_bill_type(self, session: str, bill_type: str, offset: int, limit: int):
        self.info(f"Scraping {bill_type} offset {offset} limit {limit}")

        json_data = {
            "query": """query bills($googleId: ID, $category: String, $instrumentType: InstrumentType, $prefiledDateFilter: DateFilter, $sessionAbbreviation: String, $order: Order = [
            "sessionAbbreviation",
            "DESC"], $offset: Int, $limit: Int, $where: InstrumentWhere! = {}, $search: String) {
            instruments(
                googleId: $googleId
                category: $category
                where: [{sessionAbbreviation: {eq: $sessionAbbreviation}, instrumentType: {eq: $instrumentType}, prefiledDate: $prefiledDateFilter}, $where]
                order: $order
                limit: $limit
                offset: $offset
                search: $search
            ) {
                data {
                ...billModalDataFragment
                id
                sessionYear
                instrumentNbr
                sponsor
                body
                subject
                shortTitle
                assignedCommittee
                allCommittees
                prefiledDate
                firstReadDate
                currentStatus
                lastAction
                actSummary
                viewEnacted
                companionInstrumentNbr
                effectiveDateCertain
                effectiveDateOther
                instrumentType
                __typename
                }
                count
                __typename
            }
            }
            fragment billModalDataFragment on Instrument {
            id
            sessionAbbreviation
            instrumentNbr
            instrumentType
            sponsor
            introducedFileUrl
            engrossedFileUrl
            enrolledFileUrl
            companionInstrumentNbr
            sessionYear
            instrumentNbr
            actSummary
            effectiveDateCertain
            effectiveDateOther
            __typename
            }""",
            "variables": {
                "sessionAbbreviation": self.session_identifier,
                "instrumentType": bill_type,
                "orderBy": "LastActionDate",
                "direction": "DESC",
                "offset": offset,
                "limit": limit,
                "filters": {},
            },
        }

        page = requests.post(self.gql_url, headers=self.gql_headers, json=json_data)
        page = json.loads(page.content)

        if page["data"]["instruments"]["count"] < 1:
            return

        for row in page["data"]["instruments"]["data"]:
            chamber = self.chamber_map[row["body"]]
            title = row["shortTitle"].strip()

            # some recently filed bills have no title, but a good subject which is close
            if title == "":
                title = row["Subject"]

            # prevent duplicates
            bill_id = row["instrumentNbr"]
            if bill_id in self.bill_ids:
                continue
            else:
                self.bill_ids.add(bill_id)

            bill = Bill(
                identifier=bill_id,
                legislative_session=session,
                title=title,
                chamber=chamber,
                classification=self.bill_types[row["instrumentType"]],
            )

            if "sponsor" in row and row["sponsor"] and row["sponsor"].strip != "":
                sponsor = row["sponsor"]

                bill.add_sponsorship(
                    name=sponsor,
                    entity_type="person",
                    classification="primary",
                    primary=True,
                )
            else:
                self.warning(f"No sponsors for {bill_id}")
                continue

            histories = self.scrape_rest(bill, row)
            self.scrape_versions(bill, row, histories)

            bill.add_source("https://alison.legislature.state.al.us/bill-search")
            # AL removed instrumentUrl from API as of 1/20/25
            # if row["instrumentUrl"]:
            #     bill.add_source(row["instrumentUrl"])

            # some subjects are super long & more like abstracts, but it looks like whatever is before a comma or
            # semicolon is a clear enough subject. Adds the full given Subject as an Abstract & splits to add that
            # first real subject as one
            if row["subject"]:
                full_subject = row["subject"].strip()
                bill.add_abstract(full_subject, note="full subject")
                first_sub = re.split(",|;", full_subject)
                bill.add_subject(first_sub[0])

            # OPEN-644 (PLAN-companion-lineage §5.3): the legislature's own companion field, labelled with its own
            # word: ALISON lists these on its "Companion Bills" page, and its action lines call each one "a Companion
            # Bill" ("Motion to Substitute SB169 for HB243 a Companion Bill").
            if row["companionInstrumentNbr"]:
                bill.add_related_bill(
                    row["companionInstrumentNbr"],
                    session,
                    "companion",
                    label=AL_COMPANION_LABEL,
                )

            bill.extras["AL_BILL_ID"] = row["id"]

            # votes first, the bill last, so a capped scrape never keeps a vote without its bill
            yield from self.scrape_votes(bill, histories)

            self.count += 1
            yield bill

        # no need to paginate again if we max the last page
        if page["data"]["instruments"]["count"] > offset:
            yield from self.scrape_bill_type(session, bill_type, offset + 50, limit)

    # this is one api call to grab the actions, fiscalnote, and budget isolation resolutions
    def scrape_rest(self, bill: Bill, bill_row: dict):

        json_data = {
            "query": """query billModal(
            $sessionAbbreviation: String,
            $instrumentNbr: String,
            $instrumentType: InstrumentType
            ) {
            instrument: instrument(
                where: {
                sessionAbbreviation: { eq: $sessionAbbreviation }
                instrumentNbr: { eq: $instrumentNbr }
                instrumentType: { eq: $instrumentType }
                }
            ) {
                id
                instrumentNbr
                currentStatus
                shortTitle
                introducedFileUrl
                engrossedFileUrl
                enrolledFileUrl
                viewEnacted
                viewEnacted
                actNbr
                __typename
            }
            fiscalNotes(
                where: {
                sessionAbbreviation: { eq: $sessionAbbreviation }
                instrumentNbr: { eq: $instrumentNbr }
                }
            ) {
                data {
                description
                fileUrl
                sortOrder
                __typename
                }
                __typename
            }

                histories: instrumentHistories(
                where: {
                    sessionAbbreviation: { eq: $sessionAbbreviation }
                    instrumentNbr: { eq: $instrumentNbr }
                }
                ) {
                data {
                    instrumentNbr
                    sessionYear
                    calendarDate
                    body
                    matter
                    amdSub
                    amdSubFileUrl
                    committee
                    nays
                    yeas
                    voteType
                    voteTitle
                    rollCallNbr
                    amdSub
                    ...rollVoteModalInstrumentHistoryFragment
                    __typename
                }
                __typename
                }
                birs(
                where: {
                    sessionAbbreviation: { eq: $sessionAbbreviation }
                    instrumentNbr: { eq: $instrumentNbr }
                }
                ) {
                data {
                    instrumentNbr
                    sessionYear
                    # birTitle
                    calendarDate
                    matter
                    voteType
                    voteTitle
                    # roll
                    ...rollVoteModalBirFragment
                    __typename
                }
                __typename
                }
                __typename

            }
            fragment rollVoteModalInstrumentHistoryFragment on InstrumentHistory {
            __typename
            instrumentNbr
            sessionAbbreviation
            calendarDate
            body
            # voteNbr
            }
            fragment rollVoteModalBirFragment on BudgetIsolationResolution {
            __typename
            instrumentNbr
            # bir
            calendarDate
            # roll
            }
            """,
            "variables": {
                "__typename": "InstrumentOverview",
                "instrumentNbr": bill_row["instrumentNbr"],
                "sessionAbbreviation": bill_row["sessionAbbreviation"],
            },
        }

        page = self.post(self.gql_url, headers=self.gql_headers, json=json_data)
        page = json.loads(page.content)

        data = page["data"]
        histories = []
        if "data" in data["histories"]:
            # ALISON lists history rows newest first; they are read oldest first, so a day with
            # several actions ends on its last one and that becomes the latest action (OPEN-528)
            histories = data["histories"]["data"][::-1]
            self.scrape_actions(bill, histories, bill_row)

        for row in page["data"]["fiscalNotes"]["data"]:
            bill.add_document_link(
                f"Fiscal Note: {row['description']}",
                row["fileUrl"],
                media_type="application/pdf",
                on_duplicate="ignore",
            )

        for row in page["data"]["birs"]["data"]:
            # So far it looks like "birs" do not have url
            if "fileUrl" in row:
                bill.add_document_link(
                    f"Budget Isolation Resolution: {row['matter']}",
                    row["url"],
                    media_type="application/pdf",
                    on_duplicate="ignore",
                )

        return histories

    def scrape_versions(self, bill: Bill, row: dict, histories: list):
        dates = version_dates(row, histories)
        for note, key in (
            ("Introduced", "introducedFileUrl"),
            ("Engrossed", "engrossedFileUrl"),
            ("Enrolled", "enrolledFileUrl"),
        ):
            if row[key]:
                bill.add_version_link(
                    note,
                    url=row[key],
                    date=dates[note],
                    media_type="application/pdf",
                )

    # the search JSON contains the act reference, but not the final text
    # so scrape it from the SoS
    def scrape_act(self, bill: Bill, url: str, effective: str):
        try:
            page = self.get(url, timeout=120).content
        except requests.exceptions.ConnectTimeout:
            self.warning(f"SoS website {url} is currently unavailable, skipping")
            return

        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)

        act_number = (
            page.xpath("//td[contains(text(), 'ACT NUMBER')]/text()")[0]
            .replace("ACT NUMBER", "")
            .strip()
        )
        act_number = act_number.replace(" ", "")

        if page.xpath("//a[input[@value='View Image']]"):
            act_text_url = page.xpath("//a[input[@value='View Image']]/@href")[0]
            bill.add_version_link(
                f"Act {act_number}",
                act_text_url,
                media_type=get_media_type(act_text_url),
                on_duplicate="ignore",
            )

        bill.extras["AL_ACT_NUMBER"] = act_number

        if effective:
            date_effective = dateutil.parser.parse(effective).date()
            bill.add_citation(
                "Alabama Chapter Law",
                act_number,
                "chapter",
                url=act_text_url,
                effective=date_effective,
            )
        else:
            bill.add_citation(
                "Alabama Chapter Law", act_number, "chapter", url=act_text_url
            )

    def classify_action(self, action_row: dict, resolution: bool) -> list:
        classification = self.categorizer.categorize(action_row["matter"])[
            "classification"
        ]
        # OPEN-566: a resolution's "Motion to Adopt" with no amendment or substitute (amdSub)
        # adopts the resolution itself, so it is passage, as vote_classification() says of its vote
        if (
            resolution
            and not action_row.get("amdSub")
            and AMENDMENT_ADOPTION.search(action_row["matter"])
        ):
            classification = [
                "passage" if c == "amendment-passage" else c for c in classification
            ]
        return classification

    def scrape_actions(self, bill: Bill, histories: list, bill_row: dict):

        if bill_row["prefiledDate"]:
            action_date = dateutil.parser.parse(bill_row["prefiledDate"])
            action_date = self.tz.localize(action_date)
            bill.add_action(
                chamber=self.chamber_map[bill_row["body"]],
                description="Filed",
                date=action_date,
                classification="filing",
            )

        papers = {}
        last_url = None
        for row in histories:
            action_text = row["matter"]

            if not action_text or action_text == "":
                self.warning(f"Skipping blank action for {bill}")
                continue

            if row["committee"]:
                action_text = f'{row["matter"]} ({row["committee"]})'

            action_date = dateutil.parser.parse(row["calendarDate"])
            action_date = self.tz.localize(action_date)

            action_class = self.classify_action(
                row, "resolution" in bill.classification
            )
            if not row["body"] or row["body"] == "":
                self.warning(f"No chamber for {action_text}, skipping")
                continue

            bill.add_action(
                chamber=self.chamber_map[row["body"]],
                description=action_text,
                date=action_date,
                classification=action_class,
            )

            url = row["amdSubFileUrl"]
            if url:
                papers.setdefault(url, []).append(row)
            elif last_url and AMENDMENT_ADOPTION.search(row["matter"]):
                # the adoption right after the paper's row sometimes names no paper (SB 146 2026RS:
                # "Albritton motion to adopt- Adopted Roll Call 813"); it is the vote on that paper
                papers[last_url].append(row)
            last_url = url

        # OPEN-569: each amendment or substitute paper once, named after and dated by the first
        # action that carries it; a version only if it became part of the bill (paper_is_version)
        for url, rows in papers.items():
            add_link = (
                bill.add_version_link
                if paper_is_version(rows)
                else bill.add_document_link
            )
            add_link(
                rows[0]["matter"],
                url,
                date=self.transform_date(rows[0]["calendarDate"]),
                media_type=get_media_type(url),
                on_duplicate="ignore",
            )

        # if bill_row["ViewEnacted"]:
        #     self.scrape_act(
        #         bill, bill_row["ViewEnacted"], bill_row["EffectiveDateCertain"]
        #     )

    # A history row with a rollCallNbr is a recorded vote; a voice vote ("V") has none and
    # yields nothing. Budget isolation resolutions ("birs") reuse the roll call of the history
    # row they ride on (HB2 2026RS: BIR "R 534" is the Third Reading's roll call 534), so only
    # the histories are read.
    def scrape_votes(self, bill: Bill, histories: list):
        # (chamber, day) of each amendment or substitute offered and not yet voted on
        offers = set()
        for row in histories:
            key = (row.get("body"), row.get("calendarDate"))
            if PAPER_OFFERED.search(row["matter"] or ""):
                offers.add(key)
            if row.get("rollCallNbr") and row.get("body") in self.chamber_map:
                after_offer = key in offers
                offers.discard(key)
                yield from self.scrape_vote(bill, row, after_offer)

    def scrape_vote(self, bill: Bill, action_row: dict, after_offer: bool = False):
        body = action_row["body"]
        roll_call = int(action_row["rollCallNbr"])
        session = action_row["sessionAbbreviation"]

        # a roll call number is unique per chamber per session; the bill is added because
        # the importer matches a dedupe_key across every session and bill (PRIMITIVES.md)
        vote_key = f"{session}#{body}#{roll_call}#{bill.identifier}"
        if vote_key in self.vote_keys:
            return

        json_data = {
            "query": """query rollCallVotes(
                $sessionAbbreviation: String!
                $body: LegislativeBody!
                $rollCallNbr: Int!
            ) {
                rollCallVotes(
                    sessionAbbreviation: $sessionAbbreviation
                    body: $body
                    rollCallNbr: $rollCallNbr
                ) {
                    yeas
                    nays
                    abstains
                    passes
                    votes {
                        memberName
                        vote
                    }
                }
            }""",
            "variables": {
                "sessionAbbreviation": session,
                "body": body,
                "rollCallNbr": roll_call,
            },
        }

        page = self.post(self.gql_url, headers=self.gql_headers, json=json_data)
        page = json.loads(page.content)

        roll = (page.get("data") or {}).get("rollCallVotes")
        # occasionally there's a vote number, but no data for it
        if not roll or not roll["votes"]:
            self.warning(f"No roll call data for {bill.identifier} {body} {roll_call}")
            return
        self.vote_keys.add(vote_key)

        yeas = int(roll["yeas"])
        nays = int(roll["nays"])
        abstains = int(roll["abstains"])
        passes = int(roll["passes"])

        vote = VoteEvent(
            start_date=self.transform_date(action_row["calendarDate"]),
            motion_text=action_row["matter"],
            bill_action=action_row["matter"],
            result=vote_result(action_row["matter"], yeas, nays),
            chamber=self.chamber_map[body],
            bill=bill,
            classification=vote_classification(action_row, after_offer),
        )
        vote.dedupe_key = vote_key
        # OPEN-863: ALISON gives a vote its day only; its roll-call number rises in the order the
        # chamber took its votes (HB 460's House, 2026-02-24: Roll Call 520 lost, then 521 adopted).
        # The broker reads this key into Motion.rollcall_num to order two same-day votes in one
        # chamber (as OPEN-628 and OPEN-685 did for the other states).
        vote.extras[
            "senate-rollcall-num" if body == "Senate" else "house-rollcall-num"
        ] = str(roll_call)

        vote.set_count("yes", yeas)
        vote.set_count("no", nays)
        vote.set_count("abstain", abstains)
        # Pass in AL is "i am passing on voting" not "i want the bill to pass"
        vote.set_count("not voting", passes)

        vote.add_source("https://alison.legislature.state.al.us/bill-search")

        for row in roll["votes"]:
            vote.vote(self.vote_types.get(row["vote"], "other"), row["memberName"])

        # the counts are ALISON's own totals; its member list can be one short of them
        # (2026RS House roll calls of Feb 5-24 total 105 voters but list 104 members)
        listed = len(roll["votes"])
        if listed != yeas + nays + abstains + passes:
            self.warning(
                f"{bill.identifier} {body} roll call {roll_call}: totals count "
                f"{yeas + nays + abstains + passes} voters, member list has {listed}"
            )

        yield vote

    # The api gives us dates as m-d-Y but needs them in Y-m-d
    def transform_date(self, date: str) -> str:
        date = dateutil.parser.parse(date)
        return date.strftime("%Y-%m-%d")
