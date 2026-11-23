import pytz
import datetime
import json
import re

import lxml.html

from openstates.scrape import Scraper, Bill, VoteEvent
from .actions import Categorizer
import scrapelib

from utils import LXMLMixin
from classify_motion import classify_motion


TIMEZONE = pytz.timezone("US/Mountain")
_COMMITTEE_NAME_MAPPING = {
    "Agriculture": "Agriculture, State and Public Lands and Water Resources",
    "BlockChain/Technology": "Blockchain, Financial Technology and Digital Innovation Technology Select",
    "Cap Fin & Inv": " Capital Financing and Investments Select",
    "Corporations": "Corporations, Elections and Political Subdivisions",
    "Fed Nat Res": "Federal Natural Resource Management Select",
    "Labor": "Labor, Health and Social Services",
    "Mgt Audit": "Management Audit",
    "Mgt Council": "Management Council",
    "Minerals": "Minerals, Business and Economic Development",
    "Nat Res Fund": "Natural Resource Funding Select",
    "Sel Sch Fac": "School Facilities Select",
    "Transportation": "Transportation, Highways and Military Affairs",
    "Travel": "Travel, Recreation, Wildlife and Cultural Resource",
    "Tribal Relations": "Select Committee on Tribal Relations",
    "Water": " Water Select",
}

# OPEN-675: a floor roll call's action names the chamber that voted ("S Introduced and Referred to S01 - Judiciary
# 31-0-0-0-0", "H 3rd Reading:Passed 55-2-5-0-0"), but the API's roll-call `chamber` can name the other one: in 2026
# the Senate's introduction votes on Senate files (SF 2, SF 10, ...) come back with chamber "H", so all 31 senators
# were stored on a House vote and none of them resolved. Committee votes ("S01 - ...") and amendment votes ("Amendment
# adopted ...") carry no "S "/"H " prefix and keep the API's chamber. OPEN-778: an action with no prefix that names
# a chamber's own rule was voted by that chamber: "Recalled from Committee Pursuant to Senate Rule 5-5: 29-2-0-0-0"
# on SF 50 and SF 56 (2026, 31 voters) came back with chamber "H"; the same recall on SF 84 came back "S".
VOTE_CHAMBER_RE = re.compile(r"^([SH]) |\b(S)enate Rule\b|\b(H)ouse Rule\b")


def voting_chamber(vote_json):
    """The chamber ("S"/"H") that cast a roll call: the action's "S "/"H " prefix where it has one, else the chamber
    whose rule the action names ("Senate Rule 5-5"), else the API's own `chamber` field."""
    match = VOTE_CHAMBER_RE.search(vote_json["action"] or "")
    return next(g for g in match.groups() if g) if match else vote_json["chamber"]


# OPEN-677: the kinds of roll call that are not passage, named for what they are. Which votes are passage (and
# committee-passage) is decided by the wy block of config/motion_classification.yaml; these apply only to what it
# leaves unclassified. A line-item veto override is a vote on one item of the budget bill, not on the bill. In a
# budget session a bill needs a vote to be introduced, taken on its first reading.
OTHER_VOTE_KINDS = (
    (re.compile(r"\bamendment (adopted|failed)\b", re.I), "amendment"),
    (re.compile(r"\bline item veto\b", re.I), "veto-override"),
    (
        re.compile(r"^[SH] (introduced and referred|failed introduction)\b", re.I),
        "reading-1",
    ),
)


def vote_classification(motion):
    classification = classify_motion("wy", motion)
    if classification:
        return classification
    for pattern, kind in OTHER_VOTE_KINDS:
        if pattern.search(motion):
            return [kind]
    return []


# OPEN-684: a roll call's result was "yeas beat nays", but a line-item veto override needs two thirds of the
# members elected (Wyoming Constitution art. 4, sec. 8-9): the House's "SF0001VT007: Did Not Override Line Item Veto
# 41-19-1-1-0" (2026) failed although 41 is two thirds of those voting, short of 42 of 62. The API has no outcome
# field, and a failure is in the action text ("H Failed Introduction 34-28-0-0-0" failed although yeas beat nays: a
# budget-session introduction also needs two thirds), so the text decides where it says ("Failed", "Did Not
# Override", "Passed", "Amendment adopted"). Otherwise an override ("Line Item Veto Override 23-6-2-0-0") needs two
# thirds of the chamber's 31 or 62, and any other vote yeas over nays.
FAILED_RE = re.compile(r"\b(failed|did not)\b", re.I)
PASSED_RE = re.compile(r"\b(passed|adopted)\b", re.I)
CHAMBER_SIZE = {"S": 31, "H": 62}


def vote_result(chamber, motion, yes_count, no_count):
    """'pass' or 'fail' for one roll call in chamber "S"/"H", from Wyoming's own outcome where the text gives one."""
    if FAILED_RE.search(motion):
        return "fail"
    if PASSED_RE.search(motion):
        return "pass"
    if "veto-override" in vote_classification(motion):
        return "pass" if 3 * yes_count >= 2 * CHAMBER_SIZE[chamber] else "fail"
    return "pass" if yes_count > no_count else "fail"


class WYBillScraper(Scraper, LXMLMixin):
    categorizer = Categorizer()
    chamber_abbrev_map = {"H": "lower", "S": "upper"}
    is_special = False

    def scrape(self, chamber=None, session=None):
        chambers = [chamber] if chamber is not None else ["upper", "lower"]
        for chamber in chambers:
            yield from self.scrape_chamber(chamber, session)

    def scrape_chamber(self, chamber, session):
        chamber_abbrev = {"upper": "S", "lower": "H"}[chamber]

        # pull the current session's details to tell if it's a special
        session_details = next(
            each
            for each in self.jurisdiction.legislative_sessions
            if each["identifier"] == session
        )

        if session_details["classification"] == "special":
            self.is_special = True
            bill_json_url = (
                "https://lsoservice.wyoleg.gov/api/BillInformation?"
                "$filter=Year%20eq%20{}%20and%20SpecialSessionValue%20ne%20null&$orderby=BillNum".format(
                    session[0:4]
                )
            )
        else:
            bill_json_url = (
                "https://lsoservice.wyoleg.gov/api/BillInformation?"
                "$filter=Year%20eq%20{}&$orderby=BillNum".format(session)
            )

        response = self.get(bill_json_url)
        bill_list = json.loads(response.content.decode("utf-8"))

        for bill_json in bill_list:
            if bill_json["billType"][0] == chamber_abbrev:
                yield from self.scrape_bill(bill_json["billNum"], session)

    def scrape_bill(self, bill_num, session):
        chamber_map = {"House": "lower", "Senate": "upper", "LSO": "executive"}
        # Sample with all keys: https://gist.github.com/showerst/d6cd03eff3e8b12ab01dbb219876db45
        bill_json_url = (
            "https://lsoservice.wyoleg.gov/api/BillInformation/{}/"
            "{}?calendarDate=".format(session, bill_num)
        )

        if self.is_special:
            bill_json_url = (
                "https://lsoservice.wyoleg.gov/api/BillInformation/{}/"
                "{}?specialSessionValue=1&calendarDate=".format(session[0:4], bill_num)
            )

        try:
            response = self.get(bill_json_url)
            bill_json = json.loads(response.content.decode("utf-8"))
        except scrapelib.HTTPError:
            return None

        chamber = "lower" if bill_json["bill"][0] else "upper"

        bill = Bill(
            identifier=bill_json["bill"],
            legislative_session=session,
            title=bill_json["catchTitle"],
            chamber=chamber,
            classification="bill",
        )

        bill.add_title(bill_json["billTitle"])

        source_url = "https://wyoleg.gov/Legislation/{}/{}".format(
            session, bill_json["bill"]
        )

        if self.is_special:
            source_url = (
                "https://wyoleg.gov/Legislation/{}/{}?specialSessionValue=1".format(
                    session[0:4], bill_json["bill"]
                )
            )

        bill.add_source(source_url)

        # lsoservice.wyoleg.gov lists a bill's actions newest first; they are read oldest first, so a day with several
        # actions ends on its last one and that becomes the latest action (OPEN-780, Alabama's OPEN-528)
        for action_json in bill_json["billActions"][::-1]:
            utc_action_date = self.parse_local_date(action_json["statusDate"])

            actor = None
            if action_json["location"] and action_json["location"] in chamber_map:
                actor = chamber_map[action_json["location"]]

            attrs = self.categorizer.categorize(action_json["statusMessage"].lower())
            action_type = attrs["classification"]

            action = bill.add_action(
                chamber=actor,
                description=action_json["statusMessage"],
                date=utc_action_date,
                classification=action_type,
            )

            action.extras = {"billInformationID": action_json["billInformationID"]}

        if bill_json["introduced"]:
            url = "https://wyoleg.gov/{}".format(bill_json["introduced"])

            bill.add_version_link(
                note="Introduced",
                url=url,
                media_type="application/pdf",  # optional but useful!
            )

        if bill_json["enrolledAct"]:
            url = "https://wyoleg.gov/{}".format(bill_json["enrolledAct"])

            bill.add_version_link(
                note="Enrolled",
                url=url,
                media_type="application/pdf",  # optional but useful!
            )

        if bill_json["fiscalNote"]:
            url = "https://wyoleg.gov/{}".format(bill_json["fiscalNote"])

            bill.add_document_link(
                note="Fiscal Note",
                url=url,
                media_type="application/pdf",  # optional but useful!
            )

        if bill_json["digest"]:
            url = "https://wyoleg.gov/{}".format(bill_json["digest"])

            bill.add_document_link(
                note="Bill Digest",
                url=url,
                media_type="application/pdf",  # optional but useful!
            )

        if bill_json["vetoes"]:
            for veto in bill_json["vetoes"]:
                url = "https://wyoleg.gov/{}".format(veto["vetoLinkPath"])
                bill.add_version_link(
                    note=veto["vetoLinkText"],
                    url=url,
                    media_type="application/pdf",  # optional but useful!
                )

        for amendment in bill_json["amendments"]:
            # http://wyoleg.gov/2018/Amends/SF0050H2001.pdf
            # TODO: There are no special session amendments yet,
            # but check this url format for specials
            if self.is_special:
                url = "https://wyoleg.gov/{}/Amends/{}.pdf".format(
                    session[0:4] + "Sp1", amendment["amendmentNumber"]
                )
            else:
                url = "https://wyoleg.gov/{}/Amends/{}.pdf".format(
                    session[0:4], amendment["amendmentNumber"]
                )

            if amendment["sponsor"] and amendment["status"]:
                title = "Amendment {} ({}) - {} ({})".format(
                    amendment["amendmentNumber"],
                    amendment["order"],
                    amendment["sponsor"],
                    amendment["status"],
                )
            else:
                title = "Amendment {} ({})".format(
                    amendment["amendmentNumber"], amendment["order"]
                )
            # add versions of the bill text
            version = bill.add_version_link(
                note=title, url=url, media_type="application/pdf"
            )
            version["extras"] = {
                "amendmentNumber": amendment["amendmentNumber"],
                "sponsor": amendment["sponsor"],
            }

        for sponsor in bill_json["sponsors"]:
            status = "primary" if sponsor["primarySponsor"] else "cosponsor"
            sponsor_type = "person" if sponsor["sponsorTitle"] else "organization"
            sp_chamber = (
                "lower"
                if sponsor["house"] == "H"
                else ("upper" if sponsor["house"] == "S" else None)
            )
            sponsor_name = sponsor["name"]
            if sponsor_type == "organization":
                sponsor_name = _COMMITTEE_NAME_MAPPING.get(sponsor_name, sponsor_name)
            bill.add_sponsorship(
                name=sponsor_name,
                classification=status,
                entity_type=sponsor_type,
                primary=sponsor["primarySponsor"],
                chamber=sp_chamber,
            )

        # The API's "summary"/"digest" fields are only PDF paths (e.g.
        # "2026/Summaries/HB0002.pdf"), not usable text. The actual text of
        # each is served as HTML in the "digestHTML"/"summaryHTML" fields, so
        # we extract the abstract text from those instead.
        #
        # The digest contains the "AN ACT ..." (or "A JOINT RESOLUTION ...")
        # clause -- a concise description of the bill -- which we use as the
        # primary abstract. The summary is a longer plain-language explanation
        # that we add as a secondary abstract when available.
        digest_abstract = self.extract_digest(bill_json.get("digestHTML"))
        if digest_abstract:
            bill.add_abstract(note="digest", abstract=digest_abstract)

        summary_abstract = self.extract_summary(bill_json.get("summaryHTML"))
        if summary_abstract:
            bill.add_abstract(note="summary", abstract=summary_abstract)

        if bill_json["enrolledNumber"]:
            bill.extras["wy_enrolled_number"] = bill_json["enrolledNumber"]

        if bill_json["chapter"]:
            bill.extras["chapter"] = bill_json["chapter"]

        if bill_json["effectiveDate"]:
            eff = datetime.datetime.strptime(bill_json["effectiveDate"], "%m/%d/%Y")
            bill.extras["effective_date"] = eff.strftime("%Y-%m-%d")

        bill.extras["wy_bill_id"] = bill_json["id"]

        keys_seen = set()
        for vote_json in bill_json["rollCalls"]:
            for vote in self.scrape_vote(bill, vote_json, session):
                # OPEN-769: a roll call the API lists twice for one bill is kept once
                key = getattr(vote, "dedupe_key", None)
                if key:
                    if key in keys_seen:
                        continue
                    keys_seen.add(key)
                yield vote

        yield bill

    @staticmethod
    def _split_voter_names(raw):
        """Split WY's comma-joined voter list, re-merging a bare initial
        (e.g. "Brown, G, Brown, L, Campbell, E") back onto the preceding
        surname instead of treating it as its own voter.

        OPEN-782: initials can be two letters ("Larson, JT"), which were split off as a voter "JT" on 498 stored roll calls
        of 2026. Every surname the source prints has three letters or more ("Ide", "YIN"), upper case lists
        included, so one or two capitals are always initials."""
        names = []
        for token in (raw or "").split(","):
            token = token.strip()
            if not token:
                continue
            if names and re.match(r"^(?:[A-Z]\.?){1,2}$", token):
                names[-1] = "{}, {}".format(names[-1], token)
            else:
                names.append(token)
        return names

    def scrape_vote(self, bill, vote_json, session):

        if vote_json["amendmentNumber"]:
            motion = "{}: {}".format(vote_json["amendmentNumber"], vote_json["action"])
        else:
            motion = vote_json["action"]

        chamber = voting_chamber(vote_json)
        result = vote_result(
            chamber, motion, vote_json["yesVotesCount"], vote_json["noVotesCount"]
        )

        v = VoteEvent(
            chamber=self.chamber_abbrev_map[chamber],
            start_date=self.parse_local_date(vote_json["voteDate"]),
            motion_text=motion,
            result=result,
            legislative_session=session,
            bill=bill,
            classification=vote_classification(motion),
        )

        v.set_count(option="yes", value=vote_json["yesVotesCount"])
        v.set_count("no", vote_json["noVotesCount"])
        v.set_count("absent", vote_json["absentVotesCount"])
        v.set_count("excused", vote_json["excusedVotesCount"])
        v.set_count("other", vote_json["conflictVotesCount"])

        for name in self._split_voter_names(vote_json["yesVotes"]):
            v.yes(name)

        for name in self._split_voter_names(vote_json["noVotes"]):
            v.no(name)

        # add votes with other classifications
        # option can be 'yes', 'no', 'absent',
        # 'abstain', 'not voting', 'paired', 'excused'
        for name in self._split_voter_names(vote_json["absentVotes"]):
            v.vote(option="absent", voter=name)

        for name in self._split_voter_names(vote_json["excusedVotes"]):
            v.vote(option="excused", voter=name)

        for name in self._split_voter_names(vote_json["conflictVotes"]):
            v.vote(option="other", voter=name)

        source_url = "https://lso.wyoleg.gov/Legislation/{}/{}".format(
            session, vote_json["billNumber"]
        )
        v.add_source(source_url)
        # OPEN-769: the API numbers every roll call ("voteID": Senate floor votes in the hundreds, House floor votes
        # from 5000 up, committee votes negative), and the numbers run on through a year's regular and special
        # sessions. That number with the bill's page (session, bill) is the vote's dedupe_key. The API's own
        # chamber is left out of it: it is sometimes wrong (OPEN-675).
        if vote_json.get("voteID") is not None:
            v.dedupe_key = "{}#{}".format(source_url, vote_json["voteID"])
        else:
            self.warning("No voteID on a roll call of {}".format(source_url))

        yield v

    @staticmethod
    def _html_to_text(raw_html):
        """Strip tags from an API HTML field and collapse whitespace."""
        if not raw_html:
            return ""
        text = lxml.html.fromstring(raw_html).text_content()
        return " ".join(text.split())

    def extract_digest(self, digest_html):
        """Pull the "AN ACT ..." clause out of the digest HTML.

        The digest HTML contains the bill number, sponsors, the enacting
        clause, and then the action history. We only want the enacting clause,
        which starts with "AN ACT" (bills) or "A JOINT RESOLUTION"
        (resolutions) and runs up to the first date in the action history.
        """
        text = self._html_to_text(digest_html)
        if not text:
            return None

        match = re.search(
            r"((?:AN ACT|A JOINT RESOLUTION).*?)(?=\s+\d{1,2}/\d{1,2}/\d{4})",
            text,
        )
        if not match:
            # No trailing action-history date to bound the clause; fall back to
            # everything from the enacting clause onward.
            match = re.search(r"(?:AN ACT|A JOINT RESOLUTION).*", text)
            return match.group(0).strip() if match else None

        return match.group(1).strip()

    def extract_summary(self, summary_html):
        """Pull the plain-language summary out of the summary HTML.

        The summary HTML is a form with several labeled fields; the descriptive
        text lives under the "Summary/Major Elements:" label. We also drop the
        boilerplate disclaimer that the Legislative Service Office appends.
        """
        text = self._html_to_text(summary_html)
        if not text:
            return None

        match = re.search(r"Summary/Major Elements:\s*(.*)", text)
        if not match:
            return None

        summary = match.group(1).strip()
        # Remove the trailing LSO disclaimer if present.
        summary = re.split(
            r"\s*The above summary is not an official publication",
            summary,
        )[0].strip()
        return summary or None

    def parse_local_date(self, date_str):
        # provided dates are ISO 8601, but in mountain time
        # and occasionally have fractional time at the end
        if "." not in date_str:
            date_str = date_str + ".0"

        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f")
        # Truncate microseconds; schema limits action date to 25 characters
        date_obj = date_obj.replace(microsecond=0)
        local_date = TIMEZONE.localize(date_obj)
        utc_action_date = local_date.astimezone(pytz.utc)
        return utc_action_date
