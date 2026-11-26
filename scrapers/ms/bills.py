from openstates.scrape import Scraper, Bill, VoteEvent
from openstates.utils import convert_pdf
from datetime import datetime
from .utils import append_parens
from .voter_names import add_voter
import lxml.etree
import os
import re
import pytz
import scrapelib

from classify_motion import classify_motion


# OPEN-808: where an author's page lives says the author's chamber
# ("../../House_authors/Boyd_(19th).xml", "../../Senate_authors/Boyd.xml")
_AUTHOR_CHAMBERS = {"House_authors": "lower", "Senate_authors": "upper"}


def author_name_and_chamber(name, link):
    """OPEN-808: an author as the bill's history XML prints it (P_NAME / CO_NAME) and the
    chamber of their page (P_LINK / CO_LINK), or None when there is no member page (the
    Governor and other appointing authorities on nominations). The name is kept whole: the
    legislature prints a district or an initial when two members of a chamber share a
    surname ("Simmons (12th)", "Boyd (19th)"), and a bare surname is unique within its
    chamber, so the chamber is what tells "Blackwell" in the House from "Blackwell" in the
    Senate. A trailing "*" marks a bill filed by request ("By: Representative Hines (By
    Request)" on the bill) and is not part of the name."""
    name = re.sub(r"\s*\*$", "", " ".join(name.split()))
    match = re.search(r"\b(House_authors|Senate_authors)/", link)
    return name, _AUTHOR_CHAMBERS[match.group(1)] if match else None


def _combine_lines(lines):
    newlines = []
    lastline = "."
    for line in lines:
        # OPEN-735: a count printed without a closing period ("Total--110", "Nays-0",
        # 2026 HB 1924 House override) also ends its line
        ended = lastline and (lastline[-1] in ".,:" or re.search(r"-+ ?\d+$", lastline))
        # OPEN-899: a line that breaks after a member's first initial ("... Simmons D." /
        # "T. (12th), ...") is not at a name's end: the "." belongs to the initial
        if ended and re.search(r"\s[A-Z]\.$", lastline):
            ended = False
        if ended and not line.startswith("("):
            newlines.append(line)
            lastline = line
        else:
            lastline = newlines[-1] = newlines[-1] + " " + line
    return newlines


def vote_classification(motion, line_item_veto=False):
    """What a roll call decides. Passage from the ms block of
    config/motion_classification.yaml (OPEN-693); a veto override on a bill the
    governor only partially vetoed is a line-item override, "veto-override", not
    passage; a committee substitute adopted on the floor is labelled "amendment"
    (the YAML only decides passage); anything else stays unlabelled."""
    if line_item_veto and motion == "Override Veto":
        return ["veto-override"]
    classification = classify_motion("ms", motion)
    if classification:
        return classification
    if motion == "Adopt Committee Substitute":
        return ["amendment"]
    return []


class MSBillScraper(Scraper):
    _tz = pytz.timezone("CST6CDT")
    _action_types = (
        ("Died in Committee", "committee-failure"),
        ("Enrolled Bill Signed", None),
        ("Immediate Release", None),
        ("Passed", "passage"),
        ("Adopted", "passage"),
        ("Amended", "amendment-passage"),
        ("Failed", "failure"),
        ("Committee Substitute Adopted", "substitution"),
        ("Amendment Failed", "amendment-failure"),
        ("Amendment Withdrawn", "amendment-withdrawal"),
        ("Referred To", "referral-committee"),
        ("Rereferred To", "referral-committee"),
        ("Transmitted To", "introduction"),
        ("Approved by Governor", "executive-signature"),
        ("Vetoed", "executive-veto"),
        ("Partially Vetoed", "executive-veto-line-item"),
        ("Title Suff Do", "committee-passage"),
        ("Read the Third Time", "reading-3"),
        ("Law W/out Governor's Signature", "became-law"),
    )

    def scrape(self, chamber=None, session=None):
        chambers = [chamber] if chamber else ["upper", "lower"]
        for chamber in chambers:
            yield from self.scrape_bills(chamber, session)

    def scrape_bills(self, chamber_to_scrape, session):
        url = (
            "https://billstatus.ls.state.ms.us/%s/pdf/all_measures/allmsrs.xml"
            % session
        )

        bill_dir_page = self.get(url)
        root = lxml.etree.fromstring(bill_dir_page.content)
        for mr in root.xpath("//LASTACTION/MSRGROUP"):
            bill_id = mr.xpath("string(MEASURE)").replace(" ", "")
            if bill_id[0] == "S":
                chamber = "upper"
            else:
                chamber = "lower"

            bill_type = {
                "B": "bill",
                "C": "concurrent resolution",
                "R": "resolution",
                "N": "nomination",
            }[bill_id[1]]

            # just skip past bills that are of the wrong chamber
            if chamber != chamber_to_scrape:
                continue

            link = mr.xpath("string(ACTIONLINK)").replace("..", "")
            main_doc = mr.xpath("string(MEASURELINK)").replace("../../../", "")
            main_doc_url = "https://billstatus.ls.state.ms.us/%s" % main_doc
            bill_details_url = "https://billstatus.ls.state.ms.us/%s/pdf%s" % (
                session,
                link,
            )
            try:
                details_page = self.get(bill_details_url)
            except scrapelib.HTTPError:
                self.warning("Bill page not loading for {}; skipping".format(bill_id))
                continue

            page = details_page.content
            # Some pages have the (invalid) byte 11 sitting around. Just drop
            # them out. Might as well.

            details_root = lxml.etree.fromstring(page)
            title = details_root.xpath("string(//SHORTTITLE)")
            title = "[No title given by state]" if title == "" else title
            longtitle = details_root.xpath("string(//LONGTITLE)")

            bill = Bill(
                bill_id,
                legislative_session=session,
                chamber=chamber,
                title=title,
                classification=bill_type,
            )
            bill.extras["summary"] = longtitle
            bill.add_source(main_doc_url)
            # sponsors
            main_sponsor_link = details_root.xpath("string(//P_LINK)").replace(" ", "_")
            main_sponsor, main_chamber = author_name_and_chamber(
                details_root.xpath("string(//P_NAME)"), main_sponsor_link
            )
            if main_sponsor:
                main_sponsor_url = ("http://billstatus.ls.state.ms.us/%s/" "pdf/%s") % (
                    session,
                    main_sponsor_link.strip("../"),
                )
                type = "primary"
                bill.add_source(main_sponsor_url)
                if main_chamber is None and main_sponsor.upper() == "GOVERNOR":
                    # OPEN-828: a nomination the Governor makes prints the office as its
                    # author, with no member page; its sponsor is Mississippi's executive
                    # organization (core's metadata executive_name), as Hawaii's governor's
                    # messages (OPEN-805). "GOVERNOR" as a person matched no one. The other
                    # appointing offices (LT. GOVERNOR, ATTORNEY GENERAL, a commission) have
                    # no organization in core and stay as printed.
                    bill.add_sponsorship(
                        "Office of the Governor",
                        classification=type,
                        entity_type="organization",
                        primary=True,
                    )
                else:
                    bill.add_sponsorship(
                        self.clean_voter_name(main_sponsor),
                        classification=type,
                        entity_type="person",
                        primary=True,
                        chamber=main_chamber,
                    )

            for author in details_root.xpath("//AUTHORS/ADDITIONAL"):
                co_link = author.xpath("string(CO_LINK)").replace(" ", "_")
                co_name, co_chamber = author_name_and_chamber(
                    author.xpath("string(CO_NAME)"), co_link
                )
                leg = co_name.replace(" ", "_")
                if leg:
                    # OPEN-808: the author's own page, a Senate author's under Senate_authors
                    leg_url = ("http://billstatus.ls.state.ms.us/%s/pdf/%s") % (
                        session,
                        co_link.strip("../"),
                    )
                    type = "cosponsor"
                    bill.add_source(leg_url)
                    bill.add_sponsorship(
                        self.clean_voter_name(leg),
                        classification=type,
                        entity_type="person",
                        primary=False,
                        chamber=co_chamber,
                    )
            # Versions
            intro_version = details_root.xpath("string(//INTRO_OTHER)").replace(
                "../../../../", ""
            )
            if intro_version != "":
                intro_version_url = "http://billstatus.ls.state.ms.us/" + intro_version
                bill.add_version_link(
                    "As Introduced",
                    intro_version_url,
                    on_duplicate="ignore",
                    media_type="text/html",
                )
                intro_pdf_url = re.sub("html?", "pdf", intro_version_url)
                bill.add_version_link(
                    "As Introduced",
                    intro_pdf_url,
                    on_duplicate="ignore",
                    media_type="application/pdf",
                )

            comm_version = details_root.xpath("string(//CMTESUB_OTHER" ")").replace(
                "../../../../", ""
            )
            if comm_version.find("documents") != -1:
                comm_version_url = "http://billstatus.ls.state.ms.us/" + comm_version
                bill.add_version_link(
                    "Committee Substitute",
                    comm_version_url,
                    on_duplicate="ignore",
                    media_type="text/html",
                )
                comm_pdf_url = re.sub("html?", "pdf", comm_version_url)
                bill.add_version_link(
                    "Committee Substitute",
                    comm_pdf_url,
                    on_duplicate="ignore",
                    media_type="application/pdf",
                )

            passed_version = details_root.xpath("string(//PASSED_OTHER" ")").replace(
                "../../../../", ""
            )
            if passed_version.find("documents") != -1:
                passed_version_url = (
                    "http://billstatus.ls.state.ms.us/" + passed_version
                )
                title = "As Passed the " + chamber
                bill.add_version_link(
                    title,
                    passed_version_url,
                    on_duplicate="ignore",
                    media_type="text/html",
                )
                passed_pdf_url = re.sub("html?", "pdf", passed_version_url)
                bill.add_version_link(
                    title,
                    passed_pdf_url,
                    on_duplicate="ignore",
                    media_type="application/pdf",
                )

            asg_version = details_root.xpath("string(//ASG_OTHER)").replace(
                "../../../../", ""
            )
            if asg_version.find("documents") != -1:
                asg_version_url = "http://billstatus.ls.state.ms.us/" + asg_version
                bill.add_version_link(
                    "Approved by the Governor",
                    asg_version_url,
                    on_duplicate="ignore",
                    media_type="text/html",
                )
                asg_pdf_url = re.sub("html?", "pdf", asg_version_url)
                bill.add_version_link(
                    "Approved by the Governor",
                    asg_pdf_url,
                    on_duplicate="ignore",
                    media_type="application/pdf",
                )

            # OPEN-807: "Current version" (CURRENT_OTHER) is the file of the newest of the
            # texts above (IN, CS, PS or SG: 4,014 of 4,124 bills in 2026 and 20261E name the
            # same file under INTRO/CMTESUB/PASSED/ASG), so it comes after them: the same URL is
            # then ignored and the text keeps its stage name. Added first, it took the URL and
            # the stage-named link was ignored, leaving "Current version" with no stage.
            curr_version = details_root.xpath("string(//CURRENT_OTHER" ")").replace(
                "../../../../", ""
            )
            if curr_version != "":
                curr_version_url = "http://billstatus.ls.state.ms.us/" + curr_version
                bill.add_version_link(
                    "Current version",
                    curr_version_url,
                    on_duplicate="ignore",
                    media_type="text/html",
                )
                curr_pdf_url = re.sub("html?", "pdf", curr_version_url)
                bill.add_version_link(
                    "Current version",
                    curr_pdf_url,
                    on_duplicate="ignore",
                    media_type="application/pdf",
                )

            # amendments
            # ex: http://billstatus.ls.state.ms.us/2018/pdf/history/HB/HB1040.xml
            for amd in details_root.xpath("//AMENDMENTS/*"):
                if amd.tag == "HAM":
                    name = amd.xpath("HAM_DESC[1]/text()")[0]
                    name = append_parens(amd, "HAM_DISP", name)
                    name = append_parens(amd, "HAM_VDESC", name)

                    pdf_url = amd.xpath("string(HAM_PDF" ")").replace("../", "")

                    html_url = amd.xpath("string(HAM_OTHER" ")").replace("../", "")
                elif amd.tag == "SAM":
                    name = amd.xpath("SAM_DESC[1]/text()")[0]
                    name = append_parens(amd, "SAM_DISP", name)
                    name = append_parens(amd, "SAM_VDESC", name)

                    pdf_url = amd.xpath("string(SAM_PDF" ")").replace("../", "")

                    html_url = amd.xpath("string(SAM_OTHER" ")").replace("../", "")
                elif amd.tag == "AMRPT":
                    name = amd.xpath("AMRPT_DESC[1]/text()")[0]
                    pdf_url = amd.xpath("string(AMRPT_PDF" ")").replace("../", "")

                    html_url = amd.xpath("string(AMRPT_OTHER" ")").replace("../", "")

                pdf_url = "http://billstatus.ls.state.ms.us/" + pdf_url
                html_url = "http://billstatus.ls.state.ms.us/" + html_url

                if "adopted" in name.lower() or "amendment report" in name.lower():
                    bill.add_version_link(
                        name,
                        pdf_url,
                        on_duplicate="ignore",
                        media_type="application/pdf",
                    )
                    bill.add_version_link(
                        name, html_url, on_duplicate="ignore", media_type="text/html"
                    )

            # avoid duplicate votes
            seen_votes = set()
            # OPEN-693: True once the governor has partially vetoed the bill, so an
            # override after it is a line-item override (2026 HB 1924)
            line_item_veto = False

            # Actions
            for action in details_root.xpath("//HISTORY/ACTION"):
                # action_num  = action.xpath('string(ACT_NUMBER)').strip()
                # action_num = int(action_num)
                act_vote = action.xpath("string(ACT_VOTE)").replace("../../../..", "")
                action_desc = action.xpath("string(ACT_DESC)")
                date, action_desc = action_desc.split(" ", 1)
                date = date + "/" + session[0:4]
                date = datetime.strptime(date, "%m/%d/%Y")

                if action_desc.startswith("(H)"):
                    actor = "lower"
                    action = action_desc[4:]
                elif action_desc.startswith("(S)"):
                    actor = "upper"
                    action = action_desc[4:]
                else:
                    actor = "executive"
                    action = action_desc

                if actor == "executive" and action.startswith("Partially Vetoed"):
                    line_item_veto = True

                if "Veto" in action and actor == "executive":
                    version_path = details_root.xpath("string(//VETO_OTHER)")
                    version_path = version_path.replace("../../../../", "")
                    version_url = "http://billstatus.ls.state.ms.us/" + version_path
                    bill.add_document_link("Veto", version_url)

                atype = "other"
                for prefix, prefix_type in self._action_types:
                    if action.startswith(prefix):
                        atype = prefix_type
                        break

                bill.add_action(
                    action,
                    self._tz.localize(date),
                    chamber=actor,
                    classification=atype if atype != "other" else None,
                )

                # use committee names as scraped subjects
                subjects = details_root.xpath("//H_NAME/text()")
                subjects += details_root.xpath("//S_NAME/text()")

                for subject in subjects:
                    if subject not in bill.subject:
                        bill.add_subject(subject)

                if act_vote:
                    vote_url = "http://billstatus.ls.state.ms.us%s" % act_vote
                    if vote_url not in seen_votes:
                        seen_votes.add(vote_url)
                        yield from self.scrape_votes(
                            vote_url, action, date, actor, bill, line_item_veto
                        )

            bill.add_source(bill_details_url)
            yield bill

    _vote_mapping = {
        "Passed": ("Passage", True),
        "Adopted": ("Passage", True),
        "Failed": ("Passage", False),
        "Failed to Concur": ("Failed To Concur", False),
        "Passed As Amended": ("Passage as Amended", True),
        "Adopted As Amended": ("Passage as Amended", True),
        "Appointment Confirmed": ("Appointment Confirmation", True),
        "Appointment Not Confirmed": ("Appointment Confirmation", False),
        "Committee Substitute Adopted": ("Adopt Committee Substitute", True),
        "Committee Substitute Failed": ("Adopt Committee Substitute", False),
        "Conference Report Filed": ("Conference Report Filed", True),
        "Conference Report Adopted": ("Adopt Conference Report", True),
        "Conference Report Failed": ("Adopt Conference Report", False),
        "Tabled Failed": ("Motion to Table", False),
        "Motion to Reconsider Tabled": ("Table Motion to Reconsider", True),
        "Motion to Recnsdr Tabled Lost": ("Table Motion to Reconsider", False),
        "Veto Overridden": ("Override Veto", True),
        "Veto Sustained": ("Override Veto", False),
        "Concurred in Amend From House": ("Concurrence in Amendment From House", True),
        "Concurred in Amend From Senate": (
            "Concurrence in Amendment From Senate",
            True,
        ),
        "Decline to Concur/Invite Conf": ("Decline to Concur", True),
        "Decline Concur/Inv Conf Lost": ("Decline to Concur", False),
        "Failed to Suspend Rules": ("Motion to Suspend Rules", False),
        # OPEN-693: was True; the roll call (2025 SB 2515, Senate, 15-34) says "the
        # motion to recommit ... failed"
        "Motion to Recommit Lost": ("Motion to Recommit", False),
        "Reconsidered": ("Reconsideration", True),
        "Motion to Concur Failed": ("Motion to Concur", False),
        "Recommitted to Committee": ("Recommit to Committee", True),
    }

    def scrape_votes(self, url, motion, date, chamber, bill, line_item_veto=False):
        try:
            vote_pdf, resp = self.urlretrieve(url)
        except scrapelib.HTTPError:
            self.warning("Can't find vote file {}, skipping".format(url))
            return

        text = convert_pdf(vote_pdf, "text")
        os.remove(vote_pdf)

        if motion in self._vote_mapping:
            motion, passed = self._vote_mapping[motion]
        else:
            # OPEN-708: an action missing from the map (2026 HB 1653 "Veto Referred
            # To Appropriations A") used to raise KeyError and stop the whole scrape.
            # Keep the roll call with its own action text as the motion (unlabelled
            # under the ms rules); the result comes from the PDF's own heading
            # ("... failed to pass by the following vote", "it passed", "they were
            # adopted"). A heading that says neither is skipped, not guessed.
            head = " ".join(text.decode().split("Yeas--")[0].split())
            if re.search(r"\b(fail|lost\b)", head, re.I):
                passed = False
            elif re.search(r"\b(passed|adopted|concurred|consent)\b", head, re.I):
                passed = True
            else:
                self.warning(
                    "Unknown vote action {!r} on {} ({}) and no result in the "
                    "roll call's heading; skipping".format(motion, bill.identifier, url)
                )
                return
            self.warning(
                "Unknown vote action {!r} on {} ({}); keeping it unlabelled".format(
                    motion, bill.identifier, url
                )
            )

        yes_votes = []
        no_votes = []
        other_votes = []
        absent_votes = []
        not_voting_votes = []
        # point at array to add names to
        cur_array = None

        precursors = (
            ("yeas--", yes_votes),
            ("nays--", no_votes),
            ("absent or those not voting--", absent_votes),
            ("absent and those not voting--", absent_votes),
            ("not voting--", not_voting_votes),
            ("voting present--", other_votes),
            ("present--", other_votes),
            ("disclaimer", None),
        )

        # split lines on newline, recombine lines that don't end in punctuation
        lines = _combine_lines(text.decode().split("\n"))

        for line in lines:

            # check if the line starts with a precursor, switch to that array
            for pc, arr in precursors:
                if pc in line.lower():
                    cur_array = arr
                    line = line.replace(pc, "")

            # split names
            for name in line.split(","):
                name = name.strip()

                # move on if that's all there was
                if not name:
                    continue

                # None or a Total indicate the end of a section
                if "None." in name:
                    cur_array = None

                # OPEN-733: some roll calls print one dash ("Younger. Total-51.", 2026
                # SB 2096 Senate); "Total--" alone dropped the name before the total
                match = re.match(r"(.+?)\. Total-+.*", name)
                if match and cur_array is not None:
                    cur_array.append(match.groups()[0])
                # OPEN-735: a total on its own line ("Total--110") ends the list too
                if "Total-" in name:
                    cur_array = None

                # append name if it looks ok
                junk_in_name = False
                for junk in (
                    "on final passage",
                    "Necessary",
                    "who would have",
                    "being a tie",
                    "therefore",
                    "Vacancies",
                    "a pair",
                    "Total-",
                    "ATTORNEY",
                    "on final passage",
                    "SPEAKER",
                    "BOARD",
                    "TREASURER",
                    "GOVERNOR",
                    "ARCHIVES",
                    "SECRETARY",
                ):
                    if junk in name:
                        junk_in_name = True
                        break
                if cur_array is not None and not junk_in_name:
                    # strip trailing .
                    if name[-1] == ".":
                        name = name[:-1]
                    name = self.clean_voter_name(name)
                    cur_array.append(name)

        # return vote object
        yes_count = len(yes_votes)
        no_count = len(no_votes)
        absent_count = len(absent_votes)
        not_voting_count = len(not_voting_votes)
        other_count = len(other_votes)

        vote = VoteEvent(
            chamber=chamber,
            start_date=self._tz.localize(date),
            motion_text=motion,
            result="pass" if passed else "fail",
            classification=vote_classification(motion, line_item_veto),
            bill=bill,
        )
        vote.dedupe_key = url + "#" + bill.identifier

        vote.set_count("yes", yes_count)
        vote.set_count("no", no_count)
        vote.set_count("absent", absent_count)
        vote.set_count("not voting", not_voting_count)
        vote.set_count("other", other_count)
        vote.add_source(url)
        # OPEN-731: "Mr. Speaker" on a House roll call is the session's Speaker (manifest)
        session = bill.legislative_session
        for option, names in (
            ("yes", yes_votes),
            ("no", no_votes),
            ("absent", absent_votes),
            ("not voting", not_voting_votes),
            ("other", other_votes),
        ):
            for name in names:
                add_voter(vote, option, self.clean_voter_name(name), chamber, session)
        yield vote

    def clean_voter_name(self, name):
        if "--" in name:
            name = " ".join(name.split("--")[1:])
        if "_" in name:
            name = name.replace("_", " ")
        if "Absent or those" in name:
            name = name.replace("Absent or those", "")
        if "Absent and those " in name:
            name = name.replace("Absent and those ", "")
        return name.strip()
