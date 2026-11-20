import re
import datetime
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
    # the roll call's sequence number in its chamber: ".../votes/senate/0740.pdf" (or .htm)
    return int(re.search(r"/(\d+)\.(pdf|htm)", vote.dedupe_key).group(1))


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
            # a chamber's roll calls are labelled together (final_vote_only)
            yield from final_vote_only(list(self.scrape_chamber(chamber, session)))

    def scrape_chamber(self, chamber, session):
        chamber_name = "senate" if chamber == "upper" else "house"
        # despite visible pagination on page, the HTML seems to contain everything
        url = "http://mgaleg.maryland.gov/mgawebsite/FloorActions/Index/" + chamber_name
        doc = self.lxmlize(url)
        links = doc.xpath("//table[1]/tbody/tr/td[3]/a/@href")

        seen_urls = set()

        for link in links:
            doc = self.lxmlize(link)

            for vote_url in doc.xpath('//a[contains(@href, "/votes/")]/@href'):
                if vote_url not in seen_urls:
                    v = self.scrape_vote(vote_url, session)
                    if v:
                        yield v
                    seen_urls.add(vote_url)

    def scrape_vote(self, url, session):
        fname, _ = self.urlretrieve(url)
        text = convert_pdf(fname, type="text").decode()
        lines = text.splitlines()

        chamber = "upper" if "senate" in url else "lower"
        if "Maryland" not in text:
            self.warning(f"empty vote from {url}")
            return
        date = re.findall(r"Legislative Date: (\w+ \d+, \d{4})", text)[0]

        section = "preamble"
        motion = None
        bill_id = None
        how = None
        voters = defaultdict(list)

        for line in lines:
            if section == "preamble":
                if "vetoed" in line.lower():
                    self.warning(
                        f"skipping vote that appears to be on prior session: {line}, {bill_id}"
                    )
                    return
                possible_bill_id = re.findall(r"([HS][BJR] \d+)", line)
                if possible_bill_id:
                    bill_id = possible_bill_id[0]

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

        if not bill_id and not motion:
            return
        elif bill_id and not motion:
            self.warning(f"got {bill_id} but no motion, not registering as a vote")
        elif motion and not bill_id:
            self.warning(f"got {motion} but no bill_id, not registering as a vote")
            return

        # bleh - result not indicated anywhere
        result = "pass" if yes_count > no_count else "fail"
        bill_chamber = "upper" if bill_id.startswith("S") else "lower"
        date = datetime.datetime.strptime(date, "%b %d, %Y").strftime("%Y-%m-%d")
        vote = VoteEvent(
            chamber=chamber,
            start_date=date,
            result=result,
            classification=vote_classification(motion),
            motion_text=motion,
            legislative_session=session,
            bill=bill_id,
            bill_chamber=bill_chamber,
        )
        # URL includes sequence ID, will be unique
        vote.dedupe_key = url
        vote.add_source(url)
        vote.set_count("yes", yes_count)
        vote.set_count("no", no_count)
        vote.set_count("not voting", nv_count)
        vote.set_count("excused", excused_count)
        vote.set_count("absent", absent_count)
        for how, names in voters.items():
            for name in names:
                name = name.strip().replace("*", "")
                if name and "COPY" not in name and "Indicates Vote Change" not in name:
                    vote.vote(how, name)
        check_counts(vote, raise_error=True)
        return vote
