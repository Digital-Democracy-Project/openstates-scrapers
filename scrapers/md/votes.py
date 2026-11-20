import re
import datetime
import itertools
from collections import defaultdict
from utils import LXMLMixin
from utils.votes import check_counts
from openstates.scrape import Scraper, VoteEvent
from openstates.utils import convert_pdf

from classify_motion import classify_motion

# OPEN-700: an amendment roll call, labelled here because config/motion_classification.yaml only
# decides passage: a House floor amendment ("FLA Del. Buckel /613520/1"), a Senate one ("Floor
# Amendment Ready /123456/1"), and the floor vote on a committee's amendments ("Committee
# Amendments", "committee amendment #2", "Favorable with 3 amendments /513122/1").
AMENDMENT_VOTE = re.compile(
    r"^(fla\b|floor amendment\b|committee amendments?\b|favorable with \d+ amendments? /)",
    re.I,
)
# A vote on a ruling or a motion about an amendment is procedure, not the amendment itself:
# "FLA Del. Miller /.../1 Ruled Out of Order Decision of the Chair", "... Motion to Lay Over".
PROCEDURAL_VOTE = re.compile(r"decision of the chair|motion to lay over", re.I)


def vote_classification(motion):
    """What a roll call decides: passage from the md block of
    config/motion_classification.yaml, else "amendment" for an amendment roll call, else
    nothing. Used by both the votes scraper and the bills scraper's vote parsers."""
    classification = classify_motion("md", motion)
    if classification:
        return classification
    motion = (motion or "").strip()
    if AMENDMENT_VOTE.search(motion) and not PROCEDURAL_VOTE.search(motion):
        return ["amendment"]
    return []


# OPEN-700, Ramon's two pairing rules, decided per bill and per chamber over all its roll calls:
# - a conference committee report adoption ("Conference Committee Report - Adoption", 2025's "Question
#   is on the adoption of the Conference Committee Report.") is passage unless the same chamber holds
#   its own final passage roll call on the bill after it (the Maine pattern: final passage is sometimes
#   by voice). Every one seen is followed by "Bill is on Third Reading for Final Passage.".
# - when a third reading is reconsidered and voted again ("On Third Reading (Reconsidered)"), only the
#   later vote is passage (SB 283, House, 2026).
CCR_ADOPTION = re.compile(
    r"conference committee report - adoption|adoption of the conference committee report",
    re.I,
)
# the chamber's own final passage roll call that replaces a CCR adoption: the Senate's "Bill is on
# Third Reading for Final Passage." and the House's "On Third Reading and Final Passage (...)"
FINAL_PASSAGE = re.compile(
    r"^((the )?bill (is )?on third reading for final passage|on third reading and final passage)\b",
    re.I,
)
# the only reconsidered text seen: "On Third Reading (Reconsidered) (Amend)"
RECONSIDERED = re.compile(r"^on third reading \(reconsidered\)", re.I)


def _seq(vote):
    # the roll call's session and sequence number in its chamber: ".../2026RS/votes/senate/0740.pdf"
    # (or .htm, or "...pdf#HB 7" for a consent calendar). A special session numbers its roll calls
    # from 1 again, and "2025RS" sorts before "2025S1", so its veto overrides come last (OPEN-718).
    code = re.search(r"/(\d{4}(?:rs|s\d+))/", vote.dedupe_key, re.I)
    seq = int(re.search(r"/(\d+)\.(pdf|htm)", vote.dedupe_key).group(1))
    return (code.group(1).upper() if code else "", seq)


def final_vote_only(votes):
    """Unlabel, in place, the passage votes a later roll call on the same bill in the same
    chamber replaces: a conference report adoption followed by a final passage roll call,
    and a third reading followed by its reconsidered revote."""
    passage = sorted(
        (v for v in votes if "passage" in v.motion_classification), key=_seq
    )
    replaced = []
    for i, vote in enumerate(passage):
        later = [
            v
            for v in passage[i + 1 :]
            if (v.organization, v.bill) == (vote.organization, vote.bill)
        ]
        if CCR_ADOPTION.search(vote.motion_text):
            if any(FINAL_PASSAGE.search(v.motion_text.strip()) for v in later):
                replaced.append(vote)
        elif later and RECONSIDERED.search(later[0].motion_text.strip()):
            replaced.append(vote)
    for vote in replaced:
        vote.motion_classification = []
    return votes


class MDVoteScraper(Scraper, LXMLMixin):
    def scrape(self, chamber=None, session=None):
        chambers = [chamber] if chamber is not None else ["upper", "lower"]
        for chamber in chambers:
            votes = list(self.scrape_chamber(chamber, session))
            votes.extend(self.scrape_special_session_overrides(chamber, session))
            # a chamber's roll calls are labelled together (final_vote_only)
            yield from final_vote_only(votes)

    def scrape_chamber(self, chamber, session):
        # without ?ys= the site shows its newest session, which is empty until it starts
        # (OPEN-717): 2026 -> 2026rs, 2026s1 -> 2026s1.
        session_code = session.lower()
        if "s" not in session_code:
            session_code += "rs"
        for vote_url in self.vote_urls(chamber, session_code):
            yield from self.scrape_vote(vote_url, session)

    def scrape_special_session_overrides(self, chamber, session):
        """OPEN-718: a veto override is a vote on a bill of the regular session it was vetoed
        in, so that session's run collects the overrides taken in the year's special sessions
        (2025S1, 2026S1). The special session's own run leaves them out (scrape_vote): bringing
        them in under another session's run would make the importer drop the bill's other
        votes, which that run does not carry."""
        if "s" in session.lower():
            return
        for n in itertools.count(1):
            # an index for a special session that never met lists no session days
            urls = list(self.vote_urls(chamber, f"{session}s{n}"))
            if not urls:
                return
            for vote_url in urls:
                yield from self.scrape_vote(vote_url, session, overrides_only=True)

    def vote_urls(self, chamber, session_code):
        chamber_name = "senate" if chamber == "upper" else "house"
        # despite visible pagination on page, the HTML seems to contain everything. The day
        # links the index lists already carry their session (?year=2026RS).
        url = "http://mgaleg.maryland.gov/mgawebsite/FloorActions/Index/" + chamber_name
        url += "?ys=" + session_code
        doc = self.lxmlize(url)
        links = doc.xpath("//table[1]/tbody/tr/td[3]/a/@href")

        seen_urls = set()

        for link in links:
            doc = self.lxmlize(link)

            for vote_url in doc.xpath('//a[contains(@href, "/votes/")]/@href'):
                if vote_url not in seen_urls:
                    yield vote_url
                    seen_urls.add(vote_url)

    def scrape_vote(self, url, session, overrides_only=False):
        """The VoteEvents of one roll-call PDF: none, one, or one per bill of a consent
        calendar. With overrides_only, only a veto override (scrape_special_session_overrides)."""
        fname, _ = self.urlretrieve(url)
        text = convert_pdf(fname, type="text").decode()
        lines = text.splitlines()

        chamber = "upper" if "senate" in url else "lower"
        if "Maryland" not in text:
            self.warning(f"empty vote from {url}")
            return []
        date = re.findall(r"Legislative Date: (\w+ \d+, \d{4})", text)[0]

        section = "preamble"
        motion = None
        bill_id = None
        how = None
        voters = defaultdict(list)
        # OPEN-718: a veto override ("2025 Vetoed Senate Bills", "CALENDAR OF VETOED HOUSE BILLS
        # NO. 2") and the year of the session the bill was vetoed in, when its header gives one
        override = False
        vetoed_year = None
        # OPEN-718: a Senate third-reading consent calendar ("Consent Calendar No. 10") lists its
        # bills on one or more lines after that header, and the roll call is a vote on each
        consent_bills = None
        consent_lines = []

        for line in lines:
            if section == "preamble":
                if "vetoed" in line.lower():
                    override = True
                    year = re.search(r"(\d{4})\s+vetoed", line, re.I)
                    if year:
                        vetoed_year = year.group(1)
                if re.search(r"consent calendar no", line, re.I):
                    consent_bills = []
                possible_bill_id = re.findall(r"([HS][BJR] \d+)", line)
                if possible_bill_id:
                    bill_id = possible_bill_id[0]
                    if consent_bills is not None:
                        consent_bills.extend(possible_bill_id)
                        consent_lines.append(line.strip())

                # preamble has metadata, then motion, then counts.  our process then is to
                # store the last line as the motion, but if the last line looks like a
                # continuation, append it to the prior line

                line = line.strip()
                counts = re.findall(
                    r"(\d+) Yeas\s+(\d+) Nays\s+(\d+) Not Voting\s+(\d+) Excused\s+(\d+) Absent",
                    line,
                )
                if counts:
                    yes_count, no_count, nv_count, excused_count, absent_count = counts[
                        0
                    ]
                    yes_count = int(yes_count)
                    no_count = int(no_count)
                    nv_count = int(nv_count)
                    excused_count = int(excused_count)
                    absent_count = int(absent_count)
                    section = "votes"
                elif line and line != "(Const)":
                    # questions seem to be split across two lines
                    if line.endswith("?"):
                        motion = motion + " " + line
                    else:
                        motion = line
            elif section == "votes":
                if line.startswith("Voting Yea"):
                    how = "yes"
                elif line.startswith("Voting Nay"):
                    how = "no"
                elif line.startswith("Not Voting"):
                    how = "not voting"
                elif line.startswith("Excused from Voting"):
                    how = "excused"
                elif line.startswith("Excused (Absent)"):
                    how = "absent"
                elif how:
                    names = re.split(r"\s{2,}", line)
                    voters[how].extend(names)

        if overrides_only and not override:
            return []
        if not bill_id and not motion:
            return []
        elif bill_id and not motion:
            self.warning(f"got {bill_id} but no motion, not registering as a vote")
        elif motion and not bill_id:
            self.warning(f"got {motion} but no bill_id, not registering as a vote")
            return []

        if override:
            # the bill is from the session it was vetoed in: the header's year, else the year
            # of the special session holding the roll call (".../2025S1/votes/..."). Only that
            # session's run records it; any other run would put it on the wrong bill (the check
            # this replaces skipped every override for that reason, 2021RS voting on 2020 bills).
            if not vetoed_year:
                special = re.search(r"/(\d{4})s\d+/votes/", url, re.I)
                vetoed_year = special.group(1) if special else None
            if vetoed_year != session:
                self.warning(
                    f"skipping veto override of a {vetoed_year or 'prior session'} bill "
                    f"in {session}: {bill_id}, {url}"
                )
                return []

        if consent_bills:
            bill_ids = list(dict.fromkeys(consent_bills))
            motion = " ".join(consent_lines)
        else:
            bill_ids = [bill_id]

        # bleh - result not indicated anywhere
        result = "pass" if yes_count > no_count else "fail"
        date = datetime.datetime.strptime(date, "%b %d, %Y").strftime("%Y-%m-%d")
        votes = []
        for bill_id in bill_ids:
            vote = VoteEvent(
                chamber=chamber,
                start_date=date,
                result=result,
                classification=vote_classification(motion),
                motion_text=motion,
                legislative_session=session,
                bill=bill_id,
                bill_chamber="upper" if bill_id.startswith("S") else "lower",
            )
            # URL includes sequence ID, will be unique; a consent calendar's roll call is one
            # vote per bill, so its key adds the bill (as the bills scraper's parse_vote_pdf does)
            vote.dedupe_key = f"{url}#{bill_id}" if consent_bills else url
            vote.add_source(url)
            vote.set_count("yes", yes_count)
            vote.set_count("no", no_count)
            vote.set_count("not voting", nv_count)
            vote.set_count("excused", excused_count)
            vote.set_count("absent", absent_count)
            for how, names in voters.items():
                for name in names:
                    name = name.strip().replace("*", "")
                    if (
                        name
                        and "COPY" not in name
                        and "Indicates Vote Change" not in name
                    ):
                        vote.vote(how, name)
            check_counts(vote, raise_error=True)
            votes.append(vote)
        return votes
