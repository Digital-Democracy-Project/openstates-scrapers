import datetime
import re
import logging
from collections import Counter

from openstates.scrape import VoteEvent, Scraper
from openstates.exceptions import EmptyScrape
from classify_motion import classify_motion
from .apiclient import OregonLegislatorODataClient
from .utils import index_legislators, get_timezone, SESSION_KEYS

logger = logging.getLogger("openstates")

# OPEN-598: Oregon needs a majority of all members (31 of 60, 16 of 30) to pass a bill and several
# motions, so a roll call can have more yes than no and still fail. The legislature's own text names
# the outcome; the tally decides only when the text does not. "Carried by <names>." names the members
# who carry the bill on the floor, not an outcome, so it is removed first.
CARRIER = re.compile(r"carried by [^.]*\.", re.I)
FAILED = re.compile(r"\bfailed\b", re.I)
PASSED = re.compile(r"\b(passed|repassed|adopted|readopted|carried)\b", re.I)


def result_from_text(text):
    """'pass' or 'fail' when the motion text states the outcome, else None."""
    t = CARRIER.sub("", text or "")
    if FAILED.search(t):
        return "fail"
    if PASSED.search(t):
        return "pass"
    return None


class ORVoteScraper(Scraper):
    tz = get_timezone()
    chamber_code = {"S": "upper", "H": "lower", "J": "legislature"}
    vote_code = {
        "Aye": "yes",
        "Nay": "no",
        "Excused": "absent",
        "Excused for Business": "absent",
        "Absent": "absent",
    }

    def scrape(self, session=None):
        self.api_client = OregonLegislatorODataClient(self)

        found = False
        for vote in self.scrape_votes(session):
            found = True
            yield vote

        # OPEN-607: a session can have bills but no roll calls yet (pre-filing). Reaching here
        # means Oregon's data service answered (api_client.get raises on an outage or error), so
        # no roll calls is "nothing to scrape", as in or/events.py, not a failed run.
        if not found:
            raise EmptyScrape

    def scrape_votes(self, session):
        self.session_key = SESSION_KEYS[session]
        self.legislators = index_legislators(self, self.session_key)
        measures_response = self.api_client.get(
            "votes", page=500, session=self.session_key
        )

        for measure in measures_response:
            bid = "{} {}".format(measure["MeasurePrefix"], measure["MeasureNumber"])

            measure_history = measure["MeasureHistoryActions"]
            for event in measure_history:
                if event["MeasureVotes"]:
                    tally = self.tally_votes(event, "measure")
                    result = result_from_text(event["ActionText"])
                    if result is None:
                        result = "pass" if self.passed_vote(tally) else "fail"

                    # OPEN-597: floor votes take the or block of config/motion_classification.yaml
                    classification = classify_motion("or", event["ActionText"])
                    when = datetime.datetime.strptime(
                        event["ActionDate"], "%Y-%m-%dT%H:%M:%S"
                    )
                    when = self.tz.localize(when)

                    vote = VoteEvent(
                        start_date=when,
                        bill_chamber=self.chamber_code[bid[0]],
                        motion_text=event["ActionText"],
                        classification=classification,
                        result=result,
                        legislative_session=session,
                        bill=bid,
                        chamber=self.chamber_code[event["Chamber"]],
                    )

                    vote.set_count("yes", tally["yes"])
                    vote.set_count("no", tally["no"])
                    vote.set_count("absent", tally["absent"])

                    vote_call = event["MeasureVotes"]
                    self.add_individual_votes(vote, vote_call, "measure")

                    vote.add_source(
                        "https://olis.leg.state.or.us/liz/{session}"
                        "/Measures/Overview/{bid}".format(
                            session=self.session_key, bid=bid.replace(" ", "")
                        )
                    )

                    yield vote

            committee_history = measure["CommitteeAgendaItems"]
            for event in committee_history:
                if event["CommitteeVotes"]:
                    # Oregon's OData API returns CommitteeVotes doubled for some
                    # committee agenda items (same VoteName/Meaning pairs repeated,
                    # differing only by CommitteeVoteId/CommitteeReportId). Dedupe
                    # by voter+meaning before tallying/recording individual votes.
                    event["CommitteeVotes"] = self.dedupe_committee_votes(
                        event["CommitteeVotes"]
                    )
                    tally = self.tally_votes(event, "committee")
                    passed = self.passed_vote(tally)

                    # there is at least one event w/o an Action listed
                    action = event["Action"] or event["Comments"]

                    # OPEN-597: a committee agenda item's roll call is the committee's vote on the
                    # measure ("Heard and Reported Out", "... with Amendments"), labelled by where it
                    # comes from rather than by its text.
                    classification = ["committee-passage"]
                    when = datetime.datetime.strptime(
                        event["MeetingDate"], "%Y-%m-%dT%H:%M:%S"
                    )
                    when = self.tz.localize(when)

                    vote = VoteEvent(
                        start_date=when,
                        bill_chamber=self.chamber_code[bid[0]],
                        motion_text=action,
                        classification=classification,
                        result="pass" if passed else "fail",
                        legislative_session=session,
                        bill=bid,
                        chamber=self.chamber_code[event["CommitteCode"][0]],
                    )

                    vote.set_count("yes", tally["yes"])
                    vote.set_count("no", tally["no"])
                    vote.set_count("absent", tally["absent"])

                    vote_call = event["CommitteeVotes"]
                    self.add_individual_votes(vote, vote_call, "committee")

                    meeting_date = when.strftime("%Y-%m-%d-%H-%M")
                    vote.add_source(
                        "https://olis.leg.state.or.us/liz/{session}/Committees"
                        "/{committee}/{meeting_date}/{bid}/Details".format(
                            session=self.session_key,
                            committee=event["CommitteCode"],
                            meeting_date=meeting_date,
                            bid=bid.replace(" ", ""),
                        )
                    )

                    yield vote

    @staticmethod
    def dedupe_committee_votes(committee_votes):
        seen = set()
        deduped = []
        for v in committee_votes:
            key = (v["VoteName"], v["Meaning"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(v)
        return deduped

    def add_individual_votes(self, vote, vote_call, vote_type):
        if vote_type == "measure":
            vote_meaning = "Vote"
        elif vote_type == "committee":
            vote_meaning = "Meaning"

        for voter in vote_call:
            try:
                voter_name = self.legislators[voter["VoteName"]]
            except KeyError:
                logger.warning(
                    "Legislator {} not found in session {}".format(
                        voter["VoteName"], self.session_key
                    )
                )
                voter_name = voter["VoteName"]
            if voter[vote_meaning] == "Aye":
                vote.yes(voter_name)
            elif voter[vote_meaning] == "Nay":
                vote.no(voter_name)
            else:
                vote.vote("absent", voter_name)

    @staticmethod
    def passed_vote(tally):
        return float(tally["yes"]) / (tally["yes"] + tally["no"]) > 0.5

    def tally_votes(self, event, vote_type):
        if vote_type == "measure":
            tally = dict(
                Counter([self.vote_code[v["Vote"]] for v in event["MeasureVotes"]])
            )
        elif vote_type == "committee":
            tally = dict(
                Counter([self.vote_code[v["Meaning"]] for v in event["CommitteeVotes"]])
            )
        for code in list(self.vote_code.values()):
            if code not in tally:
                tally[code] = 0
        return tally
