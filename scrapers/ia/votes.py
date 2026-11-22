# -*- coding: utf8 -*-
from datetime import datetime, time, timezone, timedelta
import re
import collections
import lxml.etree

from openstates.utils import _make_pseudo_id, convert_pdf, get_pseudo_id
from openstates.scrape import Scraper, VoteEvent
from openstates.exceptions import EmptyScrape

from classify_motion import classify_motion

from .sessions import is_regular, of_general_assembly, ordinal, session_for_journal

# OPEN-699: a roll call on an amendment ("Shall amendment H-1011 be adopted?", "Shall the rules be
# suspended to consider amendment H-8313?", "Shall the House concur in the Senate amendment H-8459?") or
# on the Senate's motion to concur in the House's amendments ("Shall the motion to concur be adopted?"),
# labelled here because config/motion_classification.yaml only decides passage. The bill as amended is
# then voted on by its own "Shall the bill pass?" roll call.
AMENDMENT_VOTE = re.compile(r"\bamendment\b|^shall the motion to concur\b", re.I)


def vote_classification(motion):
    """What a journal roll call decides: passage from the ia block of
    config/motion_classification.yaml, else "amendment" for an amendment roll call, else
    nothing."""
    classification = classify_motion("ia", motion)
    if classification:
        return classification
    if AMENDMENT_VOTE.search(motion):
        return ["amendment"]
    return []


def link_to_general_assembly(vote, sessions):
    """OPEN-745: a roll call is filed under the session of its journal's date, but its bill
    may be filed under another session of the same General Assembly (a 2025 bill voted on in
    2026 stays under 2025), so its bill is looked up among all of them. Bill numbers are unique
    within a General Assembly."""
    if vote.bill:
        spec = get_pseudo_id(vote.bill)
        del spec["legislative_session__identifier"]
        spec["legislative_session__identifier__in"] = sessions
        vote.bill = _make_pseudo_id(**spec)
    return vote


class IAVoteScraper(Scraper):
    def scrape(self, chamber=None, session=None):
        event_count = 0
        sessions = self.jurisdiction.legislative_sessions
        assembly = of_general_assembly(sessions, ordinal(sessions, session))
        for chamber in [chamber] if chamber else ["upper", "lower"]:
            for journal in self.scrape_chamber(chamber, session):
                for event in journal:
                    event_count += 1
                    yield link_to_general_assembly(event, assembly)
        if event_count < 1:
            raise EmptyScrape

    def scrape_chamber(self, chamber, session):
        # Each PDF index page contains just one year of the General Assembly; every session of
        # it (its two years and its extraordinary sessions) reads both (OPEN-745). Each roll call
        # is filed under its journal's session (the extraordinary session that sat that day, else
        # the year). An extraordinary session keeps only its own journals. Either year keeps both
        # years' journals: openstates-core's vote import deletes a bill's stored roll calls that
        # the same import does not bring, so a bill carried over from 2025 into 2026 keeps both
        # years' roll calls even when one year is scraped and imported alone (the same roll call
        # read by both years in one run is imported once).
        sessions = self.jurisdiction.legislative_sessions
        session_id = ordinal(sessions, session)
        regular = is_regular(sessions, session)
        for sub_session in [1, 2]:
            url = "https://www.legis.iowa.gov/legislation/journals/{}".format(
                "house" if chamber == "lower" else "senate"
            )
            params = {"ga": session_id, "session": sub_session}
            html = self.get(url, params=params).content

            doc = lxml.html.fromstring(html)
            doc.make_links_absolute(url)
            urls = [x for x in doc.xpath("//a[@href]/@href") if x.endswith(".pdf")][
                ::-1
            ]

            for url in urls:
                _, filename = url.rsplit("/", 1)
                journal_template = "%Y%m%d_{}.pdf"
                try:
                    if chamber == "upper":
                        journal_format = journal_template.format("SJNL")
                    elif chamber == "lower":
                        journal_format = journal_template.format("HJNL")
                    else:
                        raise ValueError(f"Unknown chamber: {chamber}")

                    date = datetime.strptime(filename, journal_format)
                    # OPEN-745: a journal, with its roll calls, belongs to one session only
                    owner = session_for_journal(sessions, session_id, date.date())
                    if owner is None or not (
                        owner == session or regular and is_regular(sessions, owner)
                    ):
                        continue
                    date = datetime.combine(
                        date, time(tzinfo=timezone(timedelta(hours=-5)))
                    )
                    yield self.scrape_journal(url, chamber, owner, date)
                except ValueError:
                    journal_format = "%m-%d-%Y.pdf"
                    try:
                        date = datetime.strptime(filename, journal_format)
                    except ValueError:
                        msg = "{} doesn't smell like a date. Skipping."
                        self.logger.info(msg.format(filename))

    def scrape_journal(self, url, chamber, session, date):

        filename, response = self.urlretrieve(url)
        self.logger.info(f"Saved journal to {filename}")
        all_text = convert_pdf(filename, type="text")

        lines = all_text.split(b"\n")
        lines = [line.decode("utf-8") for line in lines]
        lines = [
            line.strip()
            .replace("–", "-")
            .replace("―", '"')
            .replace("‖", '"')
            .replace("“", '"')
            .replace("”", '"')
            for line in lines
        ]

        # Do not process headers or completely empty lines
        header_date_re = re.compile(r"\d+\w{2} Day\s+\w+DAY, \w+ \d{1,2}, \d{4}\s+\d+")
        header_journal_re = re.compile(r"\d+\s+JOURNAL OF THE \w+\s+\d+\w{2} Day")
        lines = iter(
            [
                line
                for line in lines
                if not (
                    line == ""
                    or header_date_re.match(line)
                    or header_journal_re.match(line)
                )
            ]
        )

        # OPEN-713: a bill number wrapped onto a line of its own (House 2026-04-30, "Shall amendment
        # H-8439, as amended, be adopted?" / "(H.F. 2783)") is joined back onto the question it ends,
        # because the House question pattern matches as soon as the question's closing quote is read.
        bill_only_re = re.compile(r"\(\s*[HS]\.[A-Z\.]*\s\d+\s*\)$")
        joined = []
        for line in lines:
            if joined and bill_only_re.match(line):
                joined[-1] += f" {line}"
            else:
                joined.append(line)
        lines = iter(joined)

        # bill_id -> motion -> count
        motions_per_bill = collections.defaultdict(collections.Counter)

        # The bill number follows the question in brackets, "(S.F. 2385)", or, in some Senate
        # journals (2025-03-19 SF 603, 2025-04-07 SF 167), without them after the closing quote:
        # 'On the question "Shall the bill pass?" S.F. 603, the vote was:' (OPEN-713).
        bill_re = re.compile(r'(?:\(\s*([A-Z\.]+\s\d+)\s*\)|"\s+([A-Z\.]+\s\d+))')
        chamber_motion_re = {
            "upper": re.compile(r".* the vote was:\s*"),
            "lower": re.compile(r'.*Shall.*(?:\?"?|")(\s{bill_re.pattern})?\s*'),
        }

        for line in lines:
            # Go through with vote parse if any of
            # these conditions match.
            if not line.startswith("On the question") or "shall" not in line.lower():
                continue

            # Get the bill_id
            bill_id = None

            while not chamber_motion_re[chamber].match(line, re.IGNORECASE):
                line += f" {next(lines)}"

            try:
                bill_match = bill_re.search(line)
                bill_id = bill_match.group(1) or bill_match.group(2)
            except AttributeError:
                self.warning(f"This motion did not pertain to legislation: {line}")
                continue

            # Get the motion text
            motion_re = r"""
                    ^On\sthe\squestion,?\s  # Precedes any motion
                    "+  # Motion is preceded by a quote mark (or two)
                    (Shall\s.+?\??)  # The motion text begins with "Shall"
                    \s*(?:\?"?|"|’)\s+  # Motion is followed by a question mark and/or a quote mark
                    (?:{})?  # If the vote regards a bill, its number is listed
                    {}  # Senate has trailing text
                    \s*$
                    """.format(
                # in at least one case [SF 457 from 2020] the bill number is followed by )0
                # seemingly just a typo, this gets around that
                bill_re.pattern,
                r",?.*?the\svote\swas:" if chamber == "upper" else r"\d?",
            )
            # print("motion candidate line:", line)
            motion = re.search(motion_re, line, re.VERBOSE | re.IGNORECASE)
            if motion:
                motion = motion.group(1)

            for word, letter in (("Senate", "S"), ("House", "H"), ("File", "F")):

                if bill_id is None:
                    return

                bill_id = bill_id.replace(word, letter)

            bill_id = bill_id.replace(".", "")

            bill_chamber = dict(h="lower", s="upper")[bill_id.lower()[0]]
            votes, passed = self.parse_votes(lines)

            # at the very least, there should be a majority
            # for the bill to have passed, so check that,
            # but if the bill didn't pass, it could still be OK if it got a majority
            # eg constitutional amendments
            if not (
                (passed == (votes["yes_count"] > votes["no_count"])) or (not passed)
            ):
                self.error("The bill passed without a majority?")
                # raise ValueError("invalid vote")

            # also throw a warning if the bill failed but got a majority
            # it could be OK, but is probably something we'd want to check
            if not passed and votes["yes_count"] > votes["no_count"]:
                self.logger.warning(
                    f"{bill_id} got a majority but did not pass. "
                    "Could be worth confirming."
                )
            # ternary operator to define `result` cleanly
            result = "pass" if passed else "fail"

            # check for duplicate motions and number second and up if needed
            motion_text = re.sub(r"\xad", "-", motion)
            classification = vote_classification(motion_text)
            motions_per_bill[bill_id][motion_text] += 1
            new_count = motions_per_bill[bill_id][motion_text]
            if new_count > 1:
                motion_text += f" #{new_count}"

            vote = VoteEvent(
                chamber=chamber,
                start_date=date,
                motion_text=motion_text,
                result=result,
                classification=classification,
                legislative_session=session,
                bill=bill_id,
                bill_chamber=bill_chamber,
            )

            # add votes and counts
            for vtype in ("yes", "no", "absent", "abstain"):
                vcount = votes[f"{vtype}_count"] or 0
                vote.set_count(vtype, vcount)
                for voter in votes[f"{vtype}_votes"]:
                    vote.vote(vtype, voter)

            vote.add_source(url)
            yield vote

    def parse_votes(self, lines):
        counts = collections.defaultdict(list)
        DONE = 1
        boundaries = [
            # Senate journal.
            ("Yeas", "yes"),
            ("Nays", "no"),
            ("Absent", "absent"),
            ("Present", "abstain"),
            ("Amendment", DONE),
            ("Resolution", DONE),
            ("The senate joint resolution", DONE),
            ("Bill", DONE),
            # House journal.
            ("The ayes were", "yes"),
            ("The yeas were", "yes"),
            ("The nays were", "no"),
            ("Absent or not voting", "absent"),
            ("Rule 76 invoked", "abstain"),
            ("The bill", DONE),
            ("The committee", DONE),
            ("The resolution", DONE),
            ("The motion", DONE),
            ("Division", DONE),
            ("The joint resolution", DONE),
            ("Under the", DONE),
        ]
        passage_strings = ["passed", "adopted", "prevailed"]

        def is_boundary(text, patterns={}):
            for blurb, key in boundaries:
                if text.strip().startswith(blurb):
                    return key

        # last number on the line ("Rule 76 invoked, 1:" -> 1)
        vote_re = re.compile(r"\d+(?=\D*$)")
        """
        First step:
        move to the first line that has a "boundary" string
        """
        while True:
            text = next(lines)
            if is_boundary(text):
                break

        """
        Second step:
        Start actually parsing lines for votes until we find a "DONE" marker
        This step can be confusing because of the inner while loop that _also_
        iterates the `lines` object forward
        Because of this pattern, we need to handle the edge case of a vote object
        not having a clear is_boundary() demarcation before the end of the current journal.
        We currently handle this by catching StopIteration errors in both the inner
        _and_ outer loops.
        """
        while True:
            key = is_boundary(text)
            if key is DONE:
                try:
                    passage_line = text + " " + next(lines)
                except StopIteration:
                    """
                    we just don't add any additional lines here
                    no need for a log message. If it still matches
                    a passage_string, cool
                    """
                    passage_line = text
                passed = False
                # This text can appear in a line
                # "Amendment H–1011 lost. Harris of Appanoose moved that House Resolution 3 be adopted".
                if not ("lost" in passage_line) and any(
                    p in passage_line for p in passage_strings
                ):
                    passed = True
                break

            # Get the vote count.
            m = vote_re.search(text)
            if not m:
                if "none" in text:
                    votecount = 0
            else:
                votecount = int(m.group())
            counts[f"{key}_count"] = votecount

            # Get the voter names.
            while True:
                try:
                    text = next(lines)
                except StopIteration:
                    self.logger.warning("End of file while still iterating on voters")
                    # hack to force break of outer loop
                    text = "Division"
                    break
                if is_boundary(text):
                    break
                elif not text.strip() or text.strip().isdigit():
                    continue
                else:
                    counts[f"{key}_votes"].extend(
                        [name.strip() for name in self.split_names(text)]
                    )

        return counts, passed

    def split_names(self, text):
        # Journal rolls are laid out in columns, so names are separated by 2+
        # spaces, while multi-word names ("Kniff McCulla", "De Witt",
        # "Amos Jr.") only contain single spaces.
        junk = ["Presiding", "Mr. Speaker", "Speaker", "Spkr.", "."]
        names = []
        for name in re.split(r"\s{2,}", text.strip()):
            name = re.sub(r",?\s*(Spkr\.|Presiding)$", "", name).strip(" ,")
            if name and (name not in names) and (name not in junk):
                names.append(name)
        return names
