import re

from openstates.scrape import Scraper, Bill, VoteEvent

from .actions import categorize_actions
import requests
import scrapelib
import dateutil
import pytz

from classify_motion import classify_motion

# OPEN-694: an amendment roll call, labelled here because config/motion_classification.yaml only
# decides passage. Floor: the "2nd Reading Motion to Amend" action, or a motion naming the amendment
# ("AMD-HB0015.001.003 Romano DO PASS"); committee: the bills API's amendment motions.
AMENDMENT_VOTE = re.compile(
    r"motion to amend|(^|: )\s*amd-|: (be_amended|bill_is_amended_as_follows|further_amend_\w+)$",
    re.I,
)


def vote_classification(bill_action, motion=None):
    """What a roll call decides. The text is "<bill action>: <motion>" on the bills API and the
    bill action alone on the archive API, since the motion ("Do Pass") does not say whether it is
    the second or the third reading. Passage and committee-passage come from the mt block of
    config/motion_classification.yaml, else "amendment" for an amendment roll call, else nothing."""
    text = bill_action or ""
    if motion is not None:
        text = f"{text}: {motion}"
    classification = classify_motion("mt", text)
    if classification:
        return classification
    if AMENDMENT_VOTE.search(text):
        return ["amendment"]
    return []


# OPEN-801: a version's name says its stage. The legislature names each text's file after the bill and its
# version number ("HB0477_1.pdf" ... "HB0477_5.pdf", then "HB0477_X.pdf"), and the LC draft after its draft
# number ("LC0382.pdf"). Read on 2025 and 2027 bills (api.legmt.gov and the texts themselves, 2026-11-23):
# _1 is the text as introduced ("HB 477.1", "INTRODUCED BY ..."); each later number is the bill reprinted after
# an amendment (SB 260's _2 after its Senate committee report, _3 after the House committee's, _4 after a House
# 2nd reading amendment; of the 1,078 later numbers of 2025, 729 follow a committee report and 102 a 2nd reading),
# or printed at enrolling as the text passed (154: SB 1's _3 is byte-identical to its _X), so they rank just
# before it; _X (or _x before 2021) is the enrolled act ("AN ACT ..."). The LC file is the drafted
# bill before introduction ("_____ BILL NO. _____"), the site's "LC Text". "SB0260_X(3).pdf" is a later upload
# of the same version (the bill page lists it under "SB0260_X.pdf"), so it is another link of that version; it
# can hold a later text (SB 116's newest _X upload carries the governor's amendments), and core reads a version's
# last link by URL, which is its newest upload. Any other file keeps its own name.
VERSION_FILE = re.compile(r"[A-Z]{2}\d{4}_([1-9]\d*|X)(?:\(\d+\))?\.pdf", re.I)
LC_FILE = re.compile(r"LC\d{4}(?:\(\d+\))?\.pdf", re.I)


def version_name(file_name: str) -> str:
    if LC_FILE.fullmatch(file_name):
        return "Bill Draft"
    version = VERSION_FILE.fullmatch(file_name)
    if not version:
        return file_name
    number = version.group(1).upper()
    if number == "X":
        return "Enrolled"
    if number == "1":
        return "Introduced"
    return f"Amended Version {int(number)}"


# OPEN-851: a status name carries no outcome ("(H) 3rd Reading" reads the same passed or failed); the status row's
# `result` field holds it. Its 21 values in 2025 (66,235 status rows of 4,495 bills, api.legmt.gov, 2026-11-24) are
# written in the legislature's own words, the ones its archive API used for 2023 and before ("(H) 3rd Reading
# Passed", "(H) 3rd Reading Failed", "(S) 2nd Reading Not Concurred", "(H) Committee Executive Action--Bill Passed
# as Amended", "(S) 3rd Reading Conference Committee Report Adopted", "(H) 2nd Reading Motion to Amend Carried").
# "" means the status name already says it ("(H) Tabled in Committee"). A value not listed here keeps its own
# words, so it is never dropped.
OUTCOME_WORDS = {
    "BILL_PASSED": "Passed",
    "BILL_PASSED_AS_AMENDED": "Passed as Amended",
    "BILL_NOT_PASSED": "Not Passed",
    "BILL_NOT_PASSED_AS_AMENDED": "Not Passed as Amended",
    "BILL_CONCURRED": "Concurred",
    "BILL_CONCURRED_AS_AMENDED": "Concurred as Amended",
    "BILL_NOT_CONCURRED": "Not Concurred",
    "BILL_NOT_CONCURRED_AS_AMENDED": "Not Concurred as Amended",
    "RESOLUTION_ADOPTED": "Adopted",
    "RESOLUTION_ADOPTED_AS_AMENDED": "Adopted as Amended",
    "RESOLUTION_FAILED": "Not Adopted",
    "REPORT_ADOPTED": "Adopted",
    "REPORT_REJECTED": "Rejected",
    "MOTION_CARRIED": "Carried",
    "MOTION_FAILED": "Failed",
    "REVOTE_ON_PREVIOUS_ACTION": "Carried",
    "NO_REVOTE_ON_PREVIOUS_ACTION": "Failed",
    "VETO_OVERRIDDEN": "Passed",
    "VETO_NOT_OVERRIDDEN": "Failed",
    "BILL_TABLED": "",
    "BILL_REMOVED_FROM_TABLE": "",
}
OUTCOME_YES = {
    "BILL_PASSED",
    "BILL_PASSED_AS_AMENDED",
    "BILL_CONCURRED",
    "BILL_CONCURRED_AS_AMENDED",
    "RESOLUTION_ADOPTED",
    "RESOLUTION_ADOPTED_AS_AMENDED",
    "REPORT_ADOPTED",
    "VETO_OVERRIDDEN",
}
OUTCOME_NO = {
    "BILL_NOT_PASSED",
    "BILL_NOT_PASSED_AS_AMENDED",
    "BILL_NOT_CONCURRED",
    "BILL_NOT_CONCURRED_AS_AMENDED",
    "RESOLUTION_FAILED",
    "REPORT_REJECTED",
    "VETO_NOT_OVERRIDDEN",
}
STATUS_PREFIX = re.compile(r"\((?:H|S|LC)\) ")
COMMITTEE_ACTION = re.compile(r"Committee (?:Executive Action|Report)")
# the third reading is the chamber's final vote (OPEN-694's motion rules): on the bill, the other chamber's
# amendments or a conference report; the governor's amendments are not passage. Only the bill's own third
# reading lost is the bill's failure.
THIRD_READING = re.compile(
    r"3rd Reading(?:; 2nd Chamber Vote Required| Senate Amendments| House Amendments"
    r"| (?:Free )?Conference Committee Report)?"
)
BILL_THIRD_READING = re.compile(r"3rd Reading(?:; 2nd Chamber Vote Required)?")


def action_outcome(name: str, result, committee_passed: bool = False) -> tuple:
    """The words a status row's result adds to its name, and the labels it decides: (words, labels).

    Committee: "--Bill Passed" (committee-passage) or "--Bill Not Passed" (committee-failure), as the archive API
    wrote it. Third reading: passage, or failure when the bill's own third reading is lost ("3rd Reading Failed",
    the archive's words). A simple resolution is adopted on 2nd reading (passage). Veto override passed or failed.
    `committee_passed`: the same committee's last executive action on the bill passed it (see the report below).
    """
    if not result:
        return "", []
    status = STATUS_PREFIX.sub("", name, count=1)
    if COMMITTEE_ACTION.fullmatch(status):
        # a committee report's "concurred in as amended" is filed as BILL_NOT_CONCURRED_AS_AMENDED: all 273 such
        # 2025 rows follow the same committee's passing executive action (270 BILL_CONCURRED_AS_AMENDED), 248 go
        # on to be concurred in on 2nd reading, and no report row says BILL_CONCURRED_AS_AMENDED. Without that
        # passing executive action the value is kept as written.
        if (
            status == "Committee Report"
            and result == "BILL_NOT_CONCURRED_AS_AMENDED"
            and committee_passed
        ):
            result = "BILL_CONCURRED_AS_AMENDED"
        if result in OUTCOME_WORDS:
            kind = result.split("_", 1)[0].title()
            words = f"--{kind} {OUTCOME_WORDS[result]}"
        else:
            words = f"--{result.replace('_', ' ').title()}"
        if result in OUTCOME_YES:
            return words, ["committee-passage"]
        if result in OUTCOME_NO:
            return words, ["committee-failure"]
        return words, []

    words = OUTCOME_WORDS.get(result, result.replace("_", " ").title())
    labels = []
    if THIRD_READING.fullmatch(status):
        if result in OUTCOME_YES:
            labels = ["passage"]
        elif result in OUTCOME_NO and BILL_THIRD_READING.fullmatch(status):
            words, labels = "Failed", ["failure"]
    elif status == "2nd Reading" and result.startswith("RESOLUTION_"):
        if result in OUTCOME_YES:
            labels = ["passage"]
        elif result in OUTCOME_NO:
            labels = ["failure"]
    elif status == "Veto Override":
        if result in OUTCOME_YES:
            labels = ["veto-override-passage"]
        elif result in OUTCOME_NO:
            labels = ["veto-override-failure"]
    return (f" {words}" if words else ""), labels


# OPEN-952: a roll call's result is the outcome its bill action states, not yeas > nays. Some Montana bills need
# more than a majority (a constitutional amendment, 2025 HB 316: 33-17 in the Senate is short of two thirds), and the
# legislature records that vote as lost: "(S) 3rd Reading Failed; 2nd House Vote Required" (the archive API's words),
# "(S) 3rd Reading; 2nd Chamber Vote Required" with no result (the bills API's, the second vote being the retry
# of a first that fell short). Only a final vote (a passage roll call) and a bare floor motion take it; every other
# roll call keeps yeas > nays (a motion to amend or concur is carried when its yeas win, whatever the amendment did).
STATED_FAILED = re.compile(r"\b(?:Failed|Not (?:Passed|Concurred|Adopted)|Rejected)\b")
STATED_PASSED = re.compile(r"\b(?:Passed|Concurred|Adopted|Carried)\b")
# a floor motion on its own ("(H) Motion Failed": a motion to take a bill from a committee, which needs 60 votes)
BARE_MOTION = re.compile(r"\((?:H|S)\) Motion (?:Failed|Carried)")
SECOND_VOTE_REQUIRED = re.compile(r"; 2nd (?:House|Chamber) Vote Required")


def vote_result(classification, action_text, yes, no) -> str:
    """The result of a roll call, "pass" or "fail": a passage vote (or a bare floor motion) takes the outcome its action
    text states, else (no outcome stated, or any other roll call) yeas > nays. An action that says a second vote
    is required and states no outcome is a first vote that fell short."""
    if action_text and (
        "passage" in classification or BARE_MOTION.fullmatch(action_text)
    ):
        if STATED_FAILED.search(action_text):
            return "fail"
        if STATED_PASSED.search(action_text):
            return "pass"
        if SECOND_VOTE_REQUIRED.search(action_text):
            return "fail"
    return "pass" if yes > no else "fail"


class MTBillScraper(Scraper):
    tz = pytz.timezone("America/Denver")
    results_per_page = 100

    session_ord = None
    mt_session_id = None

    bill_chambers = {
        "H": "lower",
        "S": "upper",
        "L": "legislature",  # draft requests
    }

    bill_types = {"B": "bill", "J": "joint resolution", "R": "resolution", "C": "bill"}

    # legislator and action lookup tables for populating votes
    legislators_by_id = {}
    actions_by_id = {}
    # OPEN-952: the same actions with the outcome words added ("(S) 3rd Reading Failed"), for a roll call's result
    action_text_by_id = {}

    def scrape(self, session=None):

        for i in self.jurisdiction.legislative_sessions:
            if i["identifier"] == session:
                self.session_ord = i.get("extras", {}).get("legislatureOrdinal", None)
                self.mt_session_id = i["_scraped_name"]
                self.session_year = i["start_date"][0:4]
                self.new_api_session_identifier = i.get("extras", {}).get(
                    "newAPIIdentifier", None
                )

        # MT appears to have two sets of endpoints to its API: archive and [non-archive]
        # if we are missing a new_api_identifier for the session, use the archive endpoint
        if self.new_api_session_identifier is None:
            yield from self.scrape_archive_list_page(session, 0)
        else:
            # Get prerequisite data
            self.scrape_standing_committees()
            self.scrape_non_standing_committees()
            self.scrape_requesting_agencies()
            self.scrape_legislators()

            # scrape bills (TODO: votes)
            yield from self.scrape_list_page(session, 0)

    def scrape_legislators(self):
        self.legislators = []
        url = "https://api.legmt.gov/legislators/v1/legislators"
        response = requests.get(url).json()

        for legislator in response:
            self.legislators.append(
                {
                    "id": legislator["id"],
                    "first_name": legislator["firstName"],
                    "last_name": legislator["lastName"],
                    "middle_name": legislator["middleName"],
                    "start_date": legislator["startDate"],
                    "end_date": legislator["endDate"],
                    "chamber": "upper"
                    if legislator["chamber"] == "SENATE"
                    else "lower",
                    "party": legislator["politicalParty"]["name"],
                    "district": legislator["district"]["number"],
                    "email": legislator["emailAddress"],
                    "legislative_position": legislator["position"]
                    if legislator["position"]
                    else None,
                }
            )

            display_name = " ".join(
                filter(
                    None,
                    [
                        legislator["namePrefix"],
                        legislator["firstName"],
                        legislator["middleName"],
                        legislator["lastName"],
                        legislator["nameSuffix"],
                    ],
                )
            )

            self.legislators_by_id[str(legislator["id"])] = display_name

    def scrape_requesting_agencies(self):
        self.requesting_agencies = []
        url = "https://api.legmt.gov/legislators/v1/organizations"
        response = requests.get(url).json()

        for agency in response:
            self.requesting_agencies.append(
                {
                    "id": agency["id"],
                    "name": agency["name"],
                    "type": agency["type"],
                }
            )

    def scrape_non_standing_committees(self):
        self.non_standing_committees = []
        url = "https://api.legmt.gov/committees/v1/nonStandingCommittees/search"
        params = {"limit": 500, "offset": 0}
        json_data = {"legislatureIds": [self.new_api_session_identifier]}
        response = requests.post(url, params=params, json=json_data).json()

        for committee in response["content"]:
            cmte_code = committee["committeeDetails"]["committeeCode"]
            self.non_standing_committees.append(
                {
                    "id": committee["id"],
                    "committee_code_id": cmte_code["id"],
                    "name": cmte_code["name"],
                    "code": cmte_code["code"],
                    "type": cmte_code["committeeType"]["description"],
                }
            )

    def scrape_standing_committees(self):
        self.standing_committees = []
        url = f"https://api.legmt.gov/committees/v1/standingCommittees/findBySessionId?sessionId={self.new_api_session_identifier}"
        response = requests.get(url).json()

        for committee in response:
            cmte_code = committee["committeeDetails"]["committeeCode"]
            self.standing_committees.append(
                {
                    "id": committee["id"],
                    "committee_code_id": cmte_code["id"],
                    "name": cmte_code["name"],
                    "chamber": committee["chamber"],
                    "code": cmte_code["code"],
                }
            )

    def scrape_list_page(self, session, page_num: int):
        self.info(f"Scraping page {str(page_num)}")
        params = {
            "limit": "1000",
            "offset": str(page_num),
            "sort": ["billType.code,desc", "billNumber,asc", "draft.draftNumber,asc"],
        }

        json_data = {
            "sessionIds": [self.new_api_session_identifier],
        }

        response = self.post(
            "https://api.legmt.gov/bills/v1/bills/search", params=params, json=json_data
        ).json()

        for row in response["content"]:
            is_draft = False
            if row["billNumber"]:
                bill_id = f"{row['billType']['code']} {row['billNumber']}"
            else:
                bill_id = row["draft"]["draftNumber"]
                is_draft = True

            chamber = self.bill_chambers[bill_id[0]]
            title = row["draft"]["shortTitle"]
            bill = Bill(
                bill_id,
                legislative_session=session,
                chamber=chamber,
                title=title,
                classification=self.bill_types[bill_id[1]],
            )

            bills_base_url = "https://bills.legmt.gov/#"
            if is_draft:
                source_url = f"{bills_base_url}/lc/bill/{self.new_api_session_identifier}/{row['draft']['draftNumber']}"
            else:
                source_url = (
                    f"{bills_base_url}/laws/bill/{self.new_api_session_identifier}/{row['draft']['draftNumber']}"
                    f"?open_tab=sum"
                )
            bill.add_source(source_url)

            if not is_draft:
                # attempt to add a bill relation to the LC/draft version of this bill
                bill.add_related_bill(row["draft"]["draftNumber"], session, "replaces")

            self.scrape_actions(bill, row)
            self.scrape_extras(bill, row)
            self.scrape_subjects(bill, row)

            if not is_draft:
                self.scrape_versions(bill, row["billType"]["code"], row["billNumber"])
                if row["draft"]["fiscalNote"]:
                    self.scrape_fiscal_note(
                        bill, row["billType"]["code"], row["billNumber"]
                    )
            self.scrape_lc_versions(bill, row["draft"]["draftNumber"])

            if row["sponsorId"]:
                for legislator in self.legislators:
                    if row["sponsorId"] == legislator["id"]:
                        sponsor_name = (
                            f"{legislator['first_name']} {legislator['last_name']}"
                        )
                        bill.add_sponsorship(
                            sponsor_name,
                            classification="primary",
                            entity_type="person",
                            primary=True,
                        )

            yield bill
            # LC drafts have no floor or committee votes
            if not is_draft:
                yield from self.scrape_votes(bill, str(row["id"]))
                yield from self.scrape_committee_votes(bill, str(row["id"]))

        if response["totalPages"] > page_num + 1:
            yield from self.scrape_list_page(session, page_num + 1)

    def scrape_actions(self, bill: Bill, row: dict):
        # OPEN-851: each committee's last executive action result on this bill, for its report
        executive_results = {}
        for action in row["draft"]["billStatuses"]:
            name = action["billStatusCode"]["name"]
            # Try to add committee Name to description where applicable
            standing_committee_id = action["standingCommitteeId"]
            committee = None

            if standing_committee_id:
                committee = next(
                    (
                        comm
                        for comm in self.standing_committees
                        if comm.get("id") == standing_committee_id
                    ),
                    None,
                )
            # OPEN-851: the outcome follows the name ("(H) 3rd Reading Passed"), before the committee
            result = action.get("result")
            if result and result not in OUTCOME_WORDS:
                self.warning(
                    f"Unknown Montana status result {result} on {bill.identifier}"
                )
            # (statuses come oldest first: all 4,495 bills of 2025)
            if name.endswith("Committee Executive Action"):
                executive_results[standing_committee_id] = result
            words, outcome_labels = action_outcome(
                name,
                result,
                committee_passed=executive_results.get(standing_committee_id)
                in OUTCOME_YES,
            )
            description = f"{name}{words}"
            if committee:
                description = f"{description} - {committee['name']}"

            when = dateutil.parser.parse(action["timeStamp"])
            when = self.tz.localize(when)
            if "(H)" in name:
                chamber = "lower"
            elif "(S)" in name:
                chamber = "upper"
            else:
                chamber = "legislature"

            bill.add_action(
                description,
                date=when,
                chamber=chamber,
                classification=categorize_actions(name) + outcome_labels,
            )

            # we want to be able to look up the action name later for votes
            self.actions_by_id[str(action["id"])] = name
            self.action_text_by_id[str(action["id"])] = f"{name}{words}"

    def scrape_extras(self, bill: Bill, row: dict):
        bill.extras["bill_draft_number"] = row["draft"]["draftNumber"]

        # MT-specific data point of legislation requester (by_request_of)
        requester_type = row["draft"]["requesterType"]
        requester_id = row["draft"]["requesterId"]
        if requester_type == "LEGISLATOR":
            for legislator in self.legislators:
                if requester_id == legislator["id"]:
                    bill.extras[
                        "by_request_of"
                    ] = f"{legislator['first_name']} {legislator['last_name']}"
        elif requester_type == "AGENCY":
            for agency in self.requesting_agencies:
                if requester_id == agency["id"]:
                    bill.extras["by_request_of"] = agency["name"]
        elif requester_type == "NON_STANDING_COMMITTEE":
            for committee in self.non_standing_committees:
                if requester_id == committee["id"]:
                    bill.extras["by_request_of"] = committee["name"]

        # legal citation
        # TODO verify this still works with new API, currently no data populates this field
        if row["sessionLawChapterNumber"]:
            cite = f"{self.session_year} Chapter {row['sessionLawChapterNumber']}, {bill.identifier}"
            bill.add_citation("Montanta Chapter Laws", cite, "chapter")

    def scrape_subjects(self, bill: Bill, row: dict):
        for subject in row["draft"]["subjects"]:
            bill.add_subject(subject["subjectCode"]["description"])

    def scrape_archive_list_page(self, session, page_num: int):
        self.info(f"Scraping page {str(page_num)}")
        params = {
            "limit": str(self.results_per_page),
            "offset": str(page_num),
        }

        json_data = {
            "sessionId": self.mt_session_id,
            # "sortBy": "billNumber", # it appears that giving no sort defaults to revcron
        }

        page = requests.post(
            "https://api.legmt.gov/archive/v1/bills/search",
            params=params,
            json=json_data,
        ).json()

        for row in page["bills"]["content"]:
            is_draft = False
            if row["billNumber"]:
                bill_id = f"{row['billType']} {row['billNumber']}"
            else:
                bill_id = row["id"]["billDraftNumber"]
                is_draft = True

            chamber = self.bill_chambers[bill_id[0]]
            title = row["shortTitle"]
            bill = Bill(
                bill_id,
                legislative_session=session,
                chamber=chamber,
                title=title,
                classification=self.bill_types[bill_id[1]],
            )
            bill.add_source(
                f"https://bills.legmt.gov/#/bill/{self.mt_session_id}/{row['id']['billDraftNumber']}"
            )

            yield from self.scrape_archive_actions(bill, row)
            self.scrape_archive_extras(bill, row)
            self.scrape_archive_subjects(bill, row)

            if not is_draft:
                self.scrape_versions(bill, row["billType"], row["billNumber"])

            if row["hasFiscalNote"]:
                self.scrape_fiscal_note(bill, row["billType"], row["billNumber"])

            if row["coSponsor"]:
                print(row["coSponsor"])
                raise Exception("COSPONSOR HERE WRITE THE CODE BASED ON JSON VALUE")

            for sponsor in row["primarySponsorBillRoles"]:
                sponsor_name = f"{sponsor['lawEntity']['firstName']} {sponsor['lawEntity']['lastName']}"
                bill.add_sponsorship(
                    sponsor_name,
                    classification="primary",
                    entity_type="person",
                    primary=True,
                )

            yield bill

        if page["bills"]["totalPages"] > page_num:
            yield from self.scrape_archive_list_page(session, page_num + 1)

    def scrape_archive_actions(self, bill: Bill, row: dict):
        keys_seen = set()
        for action in row["billActions"]:
            name = action["actionType"]["description"]
            when = dateutil.parser.parse(action["date"])
            when = self.tz.localize(when)
            if "(H)" in name:
                chamber = "lower"
            elif "(S)" in name:
                chamber = "upper"
            else:
                chamber = "legislature"

            bill.add_action(
                name,
                date=when,
                chamber=chamber,
                classification=categorize_actions(name),
            )

            if action["yesVotes"] or action["noVotes"]:
                classification = vote_classification(name)
                vote = VoteEvent(
                    start_date=when,
                    motion_text=name,
                    bill_action=name,
                    result=vote_result(
                        classification,
                        name,
                        int(action["yesVotes"]),
                        int(action["noVotes"]),
                    ),
                    chamber=chamber,
                    bill=bill,
                    classification=classification,
                )

                vote.set_count("yes", int(action["yesVotes"]))
                vote.set_count("no", int(action["noVotes"]))
                vote.add_source(bill.sources[0]["url"])
                # OPEN-760: a floor vote carries its chamber's roll-call number for the session ("H2534",
                # "S1204"), the vote's dedupe_key with the bill's page (session, bill); a committee vote has none
                # and keeps the importer's match on motion + time + chamber
                if action.get("voteSeq"):
                    vote.dedupe_key = f"{bill.sources[0]['url']}#{action['voteSeq']}"
                    if vote.dedupe_key in keys_seen:
                        continue
                    keys_seen.add(vote.dedupe_key)
                yield vote

    def scrape_archive_extras(self, bill: Bill, row: dict):
        bill.extras["bill_draft_number"] = row["id"]["billDraftNumber"]

        # this is a for loop but there's only ever one entity
        for requester in row["requestOf"]:
            if requester["lawEntity"]:
                bill.extras["by_request_of"] = requester["lawEntity"]["lastName"]
            elif requester["legislator"]:
                bill.extras[
                    "by_request_of"
                ] = f"{requester['legislator']['firstName']} {requester['legislator']['lastName']}"

        if row["sessionLawChapterNumber"]:
            cite = f"{self.session_year} Chapter {row['sessionLawChapterNumber']}, {bill.identifier}"
            bill.add_citation("Montanta Chapter Laws", cite, "chapter")

    def scrape_fiscal_note(self, bill: Bill, bill_type: str, bill_number: str):
        url = f"https://api.legmt.gov/docs/v1/documents/getBillFiscalNotes?legislatureOrdinal={self.session_ord}&sessionOrdinal={self.mt_session_id}&billType={bill_type}&billNumber={bill_number}"
        try:
            page = self.get(url).json()
        except scrapelib.HTTPError:
            # no data = 404 instead of empty json
            return

        for doc_row in page:
            doc_url = f"https://api.legmt.gov/docs/v1/documents/getContent?documentId={str(doc_row['id'])}"
            bill.add_document_link(
                f"Fiscal Note: {doc_row['fileName']}",
                doc_url,
                media_type="application/pdf",
                on_duplicate="ignore",
            )

    def scrape_archive_subjects(self, bill: Bill, row: dict):
        for subject in row["subjects"]:
            bill.add_subject(subject["subject"]["description"])

    def scrape_versions(self, bill: Bill, bill_type: str, bill_number: str):
        for endpoint in ["Versions", "Amendments", "Other"]:
            url = f"https://api.legmt.gov/docs/v1/documents/getBill{endpoint}?legislatureOrdinal={self.session_ord}&sessionOrdinal={self.mt_session_id}&billType={bill_type}&billNumber={bill_number}"
            try:
                page = self.get(url).json()
            except scrapelib.HTTPError:
                # no data = 404 instead of empty json
                continue

            # TODO: this url returns binary data without the correct content type header,
            # we could POST to https://api.legmt.gov/docs/v1/documents/shortPdfUrl?documentId=2710 and get back a better
            # GET url, but is that worth 5x the requests?
            for doc_row in page:
                doc_url = f"https://api.legmt.gov/docs/v1/documents/getContent?documentId={str(doc_row['id'])}"
                if endpoint != "Versions":
                    # OPEN-801: amendments ("HB0313.001.001.pdf", "..._Amendments-in-Context_final-full.pdf") and
                    # the governor's veto papers ("HB0217GovVeto.pdf") are not texts of the bill
                    bill.add_document_link(
                        doc_row["fileName"],
                        doc_url,
                        media_type="application/pdf",
                        on_duplicate="ignore",
                    )
                    continue
                bill.add_version_link(
                    version_name(doc_row["fileName"]),
                    doc_url,
                    media_type="application/pdf",
                    on_duplicate="ignore",
                )

    def scrape_lc_versions(self, bill: Bill, lc_number: str):
        lc_docs_url = f"https://api.legmt.gov/docs/v1/documents/getBillLcs?legislatureOrdinal={self.session_ord}&sessionOrdinal={self.mt_session_id}&lcnumber={lc_number}"
        try:
            response = self.get(lc_docs_url).json()
        except scrapelib.HTTPError:
            # no data = 404 instead of empty json
            return

        # TODO: this url returns binary data without the correct content type header,
        # we could POST to https://api.legmt.gov/docs/v1/documents/shortPdfUrl?documentId=2710 and get back a better
        # GET url, but is that worth 5x the requests?
        for doc_row in response:
            doc_url = f"https://api.legmt.gov/docs/v1/documents/getContent?documentId={str(doc_row['id'])}"
            bill.add_version_link(
                version_name(doc_row["fileName"]),
                doc_url,
                media_type="application/pdf",
                on_duplicate="ignore",
            )

    def scrape_votes(self, bill: Bill, bill_id: str):
        yield from self.scrape_votes_page(
            f"https://api.legmt.gov/bills/v1/votes/findByBillId?billId={bill_id}",
            bill,
        )

    def scrape_committee_votes(self, bill: Bill, bill_id: str):
        yield from self.scrape_votes_page(
            f"https://api.legmt.gov/committees/v1/executiveActions/findByBillId?billId={bill_id}",
            bill,
        )

    # this scrapes both regular and committee votes, which have slightly different json
    def scrape_votes_page(self, vote_url: str, bill: Bill):
        try:
            page = self.get(vote_url).json()
        except scrapelib.HTTPError:
            # no data = 404 instead of empty json
            return

        keys_seen = set()
        for row in page:
            # OPEN-760: the API's vote id with the page it came from is the vote's dedupe_key. Floor votes
            # (bills/v1/votes) and committee votes (committees/v1/executiveActions) are numbered separately, so
            # one bill's floor and committee votes can share an id; the page tells them apart. A vote the page
            # lists twice is kept once.
            dedupe_key = f"{vote_url}#{row['id']}"
            if dedupe_key in keys_seen:
                continue
            # at least one example where this value is "null" in source
            # https://api.legmt.gov/bills/v1/votes/findByBillId?billId=2308
            motion = row["motion"] if row["motion"] else "Unknown"

            # the API sometimes repeats a legislator's vote under a new record id
            # (e.g. executiveActions billId=724, id 4221 lists all 21 members twice)
            # so keep only the first vote per legislator
            seen = set()
            legislator_votes = []
            for v in row["legislatorVotes"]:
                leg_id = (
                    v["legislatorId"]
                    if "legislatorId" in v
                    else v["membership"]["legislatorId"]
                )
                if leg_id not in seen:
                    seen.add(leg_id)
                    legislator_votes.append(v)
            row["legislatorVotes"] = legislator_votes

            counts = {
                "YES": 0,
                "NO": 0,
                "ABSENT": 0,
                "EXCUSED": 0,
                "ABSTAIN": 0,
            }
            for v in row["legislatorVotes"]:
                vote_type_key = "voteType" if "voteType" in v else "committeeVote"
                # validation doesn't allow hybrid votes eg YES_EXCUSED, YES_BY_PROXY
                # so translate these to YES and NO
                if v[vote_type_key] in ("YES_EXCUSED", "YES_BY_PROXY", "YES_VOTE"):
                    counts["YES"] += 1
                elif v[vote_type_key] in ("NO_EXCUSED", "NO_BY_PROXY", "NO_VOTE"):
                    counts["NO"] += 1
                elif v[vote_type_key] in ("ABSTAIN", "ABSTAINED"):
                    counts["ABSTAIN"] += 1
                else:
                    if v[vote_type_key] not in counts:
                        self.warning(
                            f"Unknown vote type {v[vote_type_key]} found at {vote_url}"
                        )
                    else:
                        counts[v[vote_type_key]] += 1

            status_id = None  # the bill action this roll call belongs to, for its stated outcome

            # regular vs committee votes
            if "billStatus" in row and row["billStatus"] and "id" in row["billStatus"]:
                status_id = str(row["billStatus"]["id"])
                if str(row["billStatus"]["id"]) in self.actions_by_id:
                    bill_action = self.actions_by_id[str(row["billStatus"]["id"])]
                else:
                    # somehow earlier part of scrape didn't find this action
                    # see if we can find the action in the Vote's copy of the bill data
                    action_names = [
                        status["billStatusCode"]["name"]
                        for status in row["bill"]["draft"]["billStatuses"]
                        if status["id"] == row["billStatus"]["id"]
                    ]
                    if len(action_names) > 0:
                        bill_action = action_names[0]
                    else:
                        self.warning(
                            f"Unable to find Vote's bill action matching {str(row['billStatus']['id'])} on {vote_url}"
                        )
                        bill_action = None

                if (
                    "billStatusCode" in row["billStatus"]
                    and "chamber" in row["billStatus"]["billStatusCode"]
                ):
                    chamber = (
                        "lower"
                        if row["billStatus"]["billStatusCode"]["chamber"] == "HOUSE"
                        else "upper"
                    )
                elif "systemId" in row and "chamber" in row["systemId"]:
                    chamber = (
                        "lower" if row["systemId"]["chamber"] == "HOUSE" else "upper"
                    )
                else:
                    chamber = None
                when = dateutil.parser.parse(row["dateTime"])
            elif "standingCommitteeMeeting" in row:
                if not row["billStatusId"] or not row["legislatorVotes"]:
                    # voice vote, skip it there's no data
                    self.info(f"Skipping voice vote {row['id']}")
                    continue

                chamber = (
                    "lower"
                    if row["standingCommitteeMeeting"]["standingCommittee"]["chamber"]
                    == "HOUSE"
                    else "upper"
                )
                status_id = str(row["billStatusId"])
                if str(row["billStatusId"]) in self.actions_by_id:
                    bill_action = self.actions_by_id[str(row["billStatusId"])]
                else:
                    self.warning(
                        f"Unable to find bill action {str(row['billStatusId'])}"
                    )
                    bill_action = None
                when = dateutil.parser.parse(row["voteTime"])
            elif "billStatus" in row and row["billStatus"] is None:
                # Possibly when voting on a crossover bill?
                # see the third entry on https://api.legmt.gov/bills/v1/votes/findByBillId?billId=559
                bill_action = None
                when = dateutil.parser.parse(row["dateTime"])
                chamber = "lower" if row["systemId"]["chamber"] == "HOUSE" else "upper"
            else:
                self.warning(
                    f"Found MT vote with neither an action nor a meeting. {vote_url}"
                )
                continue

            when = self.tz.localize(when)
            vote_id = f"{bill.legislative_session}-{bill.identifier}-{str(row['id'])}"

            classification = vote_classification(bill_action, motion)
            vote = VoteEvent(
                identifier=vote_id,
                start_date=when,
                motion_text=motion,
                bill_action=bill_action,
                result=vote_result(
                    classification,
                    self.action_text_by_id.get(status_id, bill_action),
                    counts["YES"],
                    counts["NO"],
                ),
                chamber=chamber,
                bill=bill,
                classification=classification,
            )

            vote.dedupe_key = dedupe_key
            for count_key in counts.keys():
                vote.set_count(count_key.lower(), counts[count_key])
            vote.add_source(bill.sources[0]["url"])

            for v in row["legislatorVotes"]:
                leg_id = (
                    v["legislatorId"]
                    if "legislatorId" in v
                    else v["membership"]["legislatorId"]
                )
                voter = self.legislators_by_id[str(leg_id)]
                vote_type_key = "voteType" if "voteType" in v else "committeeVote"

                if "YES" in v[vote_type_key]:
                    vote.yes(voter)
                elif "NO" in v[vote_type_key]:
                    vote.no(voter)
                elif v[vote_type_key] == "ABSENT":
                    vote.vote("absent", voter)
                elif v[vote_type_key] == "EXCUSED":
                    vote.vote("excused", voter)
                elif v[vote_type_key] == "ABSTAINED":
                    vote.vote("abstain", voter)
                else:
                    self.warning(
                        f"Could not match vote {vote_id} option for legislator vote: {v}"
                    )
                    vote.vote("other", voter)

            keys_seen.add(dedupe_key)
            yield vote
