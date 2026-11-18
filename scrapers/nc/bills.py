import datetime as dt

import lxml.etree
import lxml.html
import re
from openstates.scrape import Bill, Scraper, VoteEvent
from openstates.utils.ddp_manifest import manifest_value
import pytz
from collections import defaultdict
from classify_motion import classify_motion


eastern = pytz.timezone("US/Eastern")


# The one session whose votes are already stored with a bare roll-call number as their key (774 votes, OPEN-397).
# OPEN-555: read from the manifest's votes.bare_key_session; "2025" is the fallback until both hosts and the image
# carry the field.
_BARE_KEY_SESSION = manifest_value("nc", "votes.bare_key_session", "2025")


def vote_dedupe_key(session, rcs):
    """NC restarts its roll-call numbers in every session, and the importer matches a vote on its dedupe_key
    alone (not session or bill), so the 2025E1 extra session reusing "[S]-1" collided with the regular
    session's vote and failed the whole load (OPEN-397). Every session but 2025 gets the session in the key
    (so the next regular session, 2027, is safe too); 2025 keeps the bare number so its stored votes keep
    their keys and ids."""
    return rcs if session == _BARE_KEY_SESSION else f"{session}-{rcs}"


def roll_call_votes(vdoc):
    """(vote type, voter name) for every name on an NC roll-call transcript page.

    The page lists each vote type as a header line and then one line of names separated by "; ", for example
    "Ayes (Republican)" then "Adams; D. Hall (Speaker); Carson Smith; von Haefen". Each name is stripped on
    its own, so a two-word name keeps its space: removing every space in the row first turned "John Lowery"
    into "JohnLowery", which matches no one (OPEN-234)."""
    # only one table that looks like this
    for row in vdoc.xpath("//div[@class='row ncga-row-no-gutters']"):
        votes_names = []
        row = row.text_content()
        if "None" in row:
            vote_type = "Nope"
        elif "Ayes (" in row:
            vote_type = "yes"
        elif "Noes (" in row:
            vote_type = "no"
        elif "Excused Absence (" in row:
            vote_type = "absent"
        elif "Not Voting (" in row:
            vote_type = "not voting"
        elif "Excused Vote (" in row:
            vote_type = "excused"
        else:
            vote_type = "Not a vote"
        if vote_type not in ("Nope", "Not a vote"):
            # [0] is the blank before the header line, [1] the header, [-1] the blank after the names
            parts = row.replace("\n", ";").split(";")
            votes_names = [part.strip() for part in parts][2:-1]
        for name in votes_names:
            name = name.replace("\r", "")
            # Resolves names that have '(Chair)' in them
            if "(" in name:
                name = name[: name.find("(")].strip()
            # Adds a space to names inbetween initial and last name
            # eg: L.Johnson -> L. Johnson
            if name[1] == "." and name[2] != " ":
                name = name[:2] + " " + name[2:]
            yield vote_type, name


# OPEN-572: a roll call on a reading of the bill itself (not an amendment or a motion made on that reading)
READING_ROLL_CALL = re.compile(r"^(second|third) reading$", re.I)


def vote_classification(subject, rcs, roll_calls):
    """The vote's motion classification. `rcs` is the page's roll-call number ("[H]-794": a chamber's numbers
    only grow within a session); `roll_calls` is (subject, rcs) of every roll call on the bill page.

    NC passes most bills on a second-reading roll call and reads them a third time the same day without one;
    a revenue bill or a bill ruled material gets a third-reading roll call too, and that one is the passage.
    So a "Second Reading" roll call is passage only when no later second- or third-reading roll call of the
    same chamber follows it on the bill (OPEN-572, measured on all stored NC votes). Everything else is the
    nc block of config/motion_classification.yaml."""
    if subject.strip().lower() == "second reading":
        chamber, number = rcs.strip().split("-")
        for other_subject, other_rcs in roll_calls:
            other_chamber, other_number = other_rcs.strip().split("-")
            if (
                other_chamber == chamber
                and int(other_number) > int(number)
                and READING_ROLL_CALL.match(other_subject.strip())
            ):
                return []
        return ["passage"]
    return classify_motion("nc", subject)


class NCBillScraper(Scraper):

    archived_votes = defaultdict(lambda: defaultdict(list))

    _action_classifiers = {
        "Vetoed": "executive-veto",
        "Signed By Gov": "executive-signature",
        "Signed by Gov": "executive-signature",
        "Pres. To Gov.": "executive-receipt",
        "Withdrawn from ": "withdrawal",
        "Ref ": "referral-committee",
        "Re-ref ": "referral-committee",
        "Reptd Fav": "committee-passage-favorable",
        "Reptd Unfav": "committee-passage-unfavorable",
        "Passed 1st Reading": "reading-1",
        "Passed 2nd Reading": "reading-2",
        "Passed 3rd Reading": ["passage", "reading-3"],
        "Passed 2nd & 3rd Reading": ["passage", "reading-2", "reading-3"],
        "Failed 3rd Reading": ["failure", "reading-3"],
        "Filed": "introduction",
        "Adopted": "passage",  # resolutions
        "Concurred In": "amendment-passage",
        "Com Amend Adopted": "amendment-passage",
        "Assigned To": "referral-committee",
        "Amendment Withdrawn": "amendment-withdrawal",
        "Amendment Offered": "amendment-introduction",
        "Amend Failed": "amendment-failure",
        "Amend Adopted": "amendment-passage",
        "Became Law W/o Signature": "became-law",
        "Ch.": "became-law",
        "Veto Overridden": "veto-override-passage",
    }

    def scrape_bill(self, chamber, session, bill_id, bill_type, bill_title):
        # there will be a space in bill_id if we're doing a one-off bill scrape
        # convert HB 102 into H102
        if " " in bill_id:
            bill_id = bill_id[0] + bill_id.split(" ")[-1]

        # if chamber comes in as House/Senate convert to lower/upper
        if chamber == "Senate":
            chamber = "upper"
        elif chamber == "House":
            chamber = "lower"

        bill_detail_url = f"https://www.ncleg.gov/BillLookUp/{session}/{bill_id}"

        # parse the bill data page, finding the latest html text
        data = self.get(bill_detail_url).text
        doc = lxml.html.fromstring(data)
        doc.make_links_absolute(bill_detail_url)

        if "JR" in bill_type:
            bill_type = "joint resolution"
            bill_id = bill_id[0] + "JR " + bill_id[1:]
        elif "R" in bill_type:
            bill_type = "resolution"
            bill_id = bill_id[0] + "R " + bill_id[1:]
        elif "B" in bill_type:
            bill_type = "bill"
            bill_id = bill_id[0] + "B " + bill_id[1:]

        # For special cases where bill title is blank, a new title is created using Bill ID
        if not bill_title:
            bill_title = bill_id.replace(" ", "")

        bill = Bill(
            bill_id,
            legislative_session=session,
            title=bill_title,
            chamber=chamber,
            classification=bill_type,
        )
        bill.add_source(bill_detail_url)

        # skip first PDF link (duplicate link to cur version)
        if chamber == "lower":
            link_xpath = '//a[contains(@href, "/Bills/House/PDF/")]'
        else:
            link_xpath = '//a[contains(@href, "/Bills/Senate/PDF/")]'
        for vlink in doc.xpath(link_xpath)[1:]:
            # get the name from the PDF link...
            version_name = vlink.text.replace("\xa0", " ")
            version_url = vlink.attrib["href"]

            media_type = "text/html"
            if version_url.lower().endswith(".pdf"):
                media_type = "application/pdf"

            bill.add_version_link(
                version_name, version_url, media_type=media_type, on_duplicate="ignore"
            )

        # rows with a 'adopted' in the text and an amendment link, skip failed amds
        for row in doc.xpath(
            '//div[@class="card-body"]/div[contains(., "Adopted")'
            ' and contains(@class,"row")]//a[@title="Amendment"]'
        ):
            version_url = row.xpath("@href")[0]
            version_name = row.xpath("string(.)").strip()
            bill.add_version_link(
                version_name,
                version_url,
                media_type="application/pdf",
                on_duplicate="ignore",
            )

        # sponsors
        try:
            spon_row = doc.xpath("//main/div[3]/div[2]/div/div[4]")[0]
            spon_lines = spon_row.text_content().replace("\r\n", ";").replace("\n", ";")
            # first sponsors are primary, until we see (Primary)
            spon_type = "primary"
            for leg in spon_lines.split(";"):
                name = leg.replace("\xa0", " ").strip()
                if name.startswith("(Primary)") or name.endswith("(Primary)"):
                    name = name.replace("(Primary)", "").strip()
                    spon_type = "cosponsor"
                if not name:
                    continue
                entity_type = "person"
                if "rules, calendar, and operations of the house" in name.lower():
                    name = name.replace(")", "")
                    entity_type = "organization"
                bill.add_sponsorship(
                    name,
                    classification=spon_type,
                    entity_type=entity_type,
                    primary=(spon_type == "primary"),
                )
        except IndexError:
            self.warning("No sponsors")
            pass

        # keywords
        try:
            kw_row = doc.xpath(
                '//div[contains(text(), "Keywords:")]/following-sibling::div'
            )[0]
            for subject in kw_row.text_content().split(", "):
                bill.add_subject(subject)
        except IndexError:
            self.warning("No subjects")
            pass

        self.scrape_actions(bill, doc)

        # TODO: Fix vote scraper
        for row in doc.xpath("//h6[@id='vote-header']"):
            yield from self.scrape_votes(bill, doc)

        # For archived votes
        if session in ["1997", "1999"]:
            yield from self.add_archived_votes(bill, bill_id)

        yield bill

    def scrape_actions(self, bill, doc):
        action_tr_xpath = (
            '//h6[contains(text(), "History")]'
            '/ancestor::div[contains(@class, "gray-card")]'
            '//div[@class ="card-body"]'
            '/div[contains(@class, "row")]'
        )

        # The bill page lists the history newest first, a day's actions included (its own oldest-first view,
        # /BillLookUp/{session}/{bill}/True, is exactly this list reversed). The rows are read oldest first, a
        # plain reverse and not a date sort, so a day ends on its last action and that becomes the latest
        # action (OPEN-543, as OPEN-534/535 for Louisiana and Nebraska)
        for row in reversed(doc.xpath(action_tr_xpath)):
            cols = row.xpath("div")
            act_date = cols[1].text
            actor = cols[3].text or ""
            # if text is blank, try diving in
            action = (cols[5].text or "").strip() or cols[5].text_content().strip()

            if act_date is None:
                search_action_date = action.split()
                for act in search_action_date:
                    try:
                        if "/" in act:
                            # try:
                            act_date = dt.datetime.strptime(act, "%m/%d/%Y").strftime(
                                "%Y-%m-%d"
                            )
                    except KeyError:
                        raise Exception("No Action Date Provided")
            else:
                act_date = dt.datetime.strptime(act_date, "%m/%d/%Y").strftime(
                    "%Y-%m-%d"
                )

            if actor == "Senate":
                actor = "upper"
            elif actor == "House":
                actor = "lower"
            else:
                actor = "executive"

            for pattern, atype in self._action_classifiers.items():
                if action.startswith(pattern):
                    break
            else:
                atype = None
            if act_date is not None:
                bill.add_action(action, act_date, chamber=actor, classification=atype)

    def scrape_votes(self, bill, doc):
        # The page shows a bill's latest two roll calls as class "row" and puts the rest in a collapsed
        # "Show All Votes" block as class "row mx-0"; matching only "row" dropped every older roll call
        # (HB 116 has 7, only 2 were stored: OPEN-573). Any div whose classes include "row" is a vote row.
        vote_tr_path = (
            '//h6[@id="vote-header"]'
            '/ancestor::div[contains(@class, "gray-card")]'
            '//div[contains(@class, "card-body")]'
            '//div[contains(concat(" ", normalize-space(@class), " "), " row ")]'
        )

        vote_rows = [
            (row, [each.text_content() for each in row.xpath("div")[1:-1:2]])
            for row in doc.xpath(vote_tr_path)
        ]
        roll_calls = [(entries[1], entries[2]) for _, entries in vote_rows]

        for vote_row, entries in vote_rows:
            date, subject, rcs, aye, no, nv, abs, exc, total = entries
            result = vote_row.xpath("div/a")[0]
            result_text = result.text
            result_link = result.get("href")

            if "H" in rcs:
                chamber = "lower"
            elif "S" in rcs:
                chamber = "upper"

            # "8/4/2026 5:51 p.m.": %I, the 12-hour field, so the a.m./p.m. counts (%H ignored it and stored
            # every afternoon vote 12 hours early: OPEN-575)
            date = eastern.localize(
                dt.datetime.strptime(date.replace(".", ""), "%m/%d/%Y %I:%M %p")
            )
            date = date.isoformat()

            ve = VoteEvent(
                chamber=chamber,
                start_date=date,
                motion_text=subject,
                result="pass" if "PASS" in result_text else "fail",
                bill=bill,
                classification=vote_classification(subject, rcs, roll_calls),
            )
            ve.dedupe_key = vote_dedupe_key(bill.legislative_session, rcs)
            ve.set_count("yes", int(aye))
            ve.set_count("no", int(no))
            ve.set_count("not voting", int(nv))
            ve.set_count("absent", int(abs))
            ve.set_count("excused", int(exc))
            ve.add_source(result_link)

            data = self.get(result_link).text
            vdoc = lxml.html.fromstring(data)

            for vote_type, name in roll_call_votes(vdoc):
                ve.vote(vote_type, name)

            yield ve

    # Adds archived votes
    def add_archived_votes(self, bill, bill_id):
        bill_id = bill_id.split()
        bill_id[0] = bill_id[0][0]
        if len(bill_id[-1]) == 2:
            bill_id[-1] = "00" + bill_id[-1]
        if len(bill_id[-1]) == 3:
            bill_id[-1] = "0" + bill_id[-1]
        bill_id = "".join(bill_id)

        if bill_id in self.archived_votes:

            for vote_key, legislator_votes in self.archived_votes[bill_id].items():
                (
                    vote_date,
                    r_number,
                    action_number,
                    action_vote_result,
                    archive_url,
                    cod,
                    _,
                ) = vote_key

                if archive_url[-1] == "S":
                    chamber = "upper"
                else:
                    chamber = "lower"

                vote_date = eastern.localize(vote_date)
                vote_date = vote_date.isoformat()

                motion_text = (
                    action_number + r_number + cod + action_vote_result
                ).replace(" ", "_")

                ve = VoteEvent(
                    chamber=chamber,  # TODO: check this
                    start_date=vote_date,
                    motion_text=motion_text,
                    bill=bill,
                    result=action_vote_result,
                    # No indication on classification for archived votes
                )
                ve.add_source(archive_url)

                for lv in legislator_votes:
                    ve.vote(lv["how_voted"], lv["leg"])

                yield ve

    # Specifically meant for scraping 1997 and 1999 sessions
    def scrape_archived_votes(self, chamber, session):
        chamber_abbr = "S" if chamber == "upper" else "H"
        archive_url = f"https://www.ncleg.gov/Legislation/Votes/MemberVoteHistory/{session}/{chamber_abbr}"
        data = self.get(archive_url).text
        doc = lxml.html.fromstring(data)
        doc.make_links_absolute(archive_url)

        rep_links = doc.xpath("//option/@value")[1:]
        for rep_link in rep_links:
            rep_url = f"https://www.ncleg.gov/Legislation/Votes/MemberVoteHistory/{session}/{chamber_abbr}/{rep_link}"

            # Special case as page has had some issues
            if rep_link == "boyd-mcintyre-348":
                continue

            # Scrapping detailed vote pages for archived representatives
            rep_data = self.get(rep_url).text
            rep_doc = lxml.html.fromstring(rep_data)
            rep_doc.make_links_absolute(rep_url)

            rep_name = rep_doc.xpath("//div[@class='section-title']")[0].text.split()[
                1:-2
            ]
            rep_name = " ".join(rep_name)

            # Designates where the X is placed to indicate a vote
            yes_location = 59
            no_location = 64
            noVt_location = 69
            exAb_location = 74
            # exVt_location = 79

            vote_text = rep_doc.xpath("//pre")[0].text.splitlines()
            for x in range(len(vote_text)):
                line = vote_text[x].split()
                if line and re.match(r"[H, S]\d\d\d\d", line[0]):
                    bill_id = line[0]

                    # Counting by 2 to find each line. 50 is an arbitrary number that is
                    # high enough to find all votes for a bill
                    for y in range(1, 50, 2):
                        if not re.match(r"[H, S]\d\d\d\d", vote_text[x + y]) and (
                            (x + y + 2) < len(vote_text)
                        ):

                            vote_details_line = vote_text[x + y]
                            vote_date = vote_details_line[2:20]
                            vote_date = dt.datetime.strptime(
                                vote_date, "%b %d, %Y %H:%M"
                            )
                            r_number = vote_details_line[21:23]
                            action_number = vote_details_line[25:28]
                            cod = vote_details_line[29:33]

                            # Determining how the bill was voted
                            vote_numbers = vote_details_line.split()
                            yes_votes = int(vote_numbers[-5])
                            no_votes = int(vote_numbers[-4])
                            noVt_votes = int(vote_numbers[-3])
                            exAb_votes = int(vote_numbers[-2])
                            exVt_votes = int(vote_numbers[-1])
                            if yes_votes > (
                                no_votes + noVt_votes + exAb_votes + exVt_votes
                            ):
                                action_vote_result = "pass"
                            else:
                                action_vote_result = "fail"

                            rep_vote = vote_text[x + y + 1]
                            vote_location = rep_vote.rfind("X")

                            if vote_location == yes_location:
                                how_voted = "yes"
                            elif vote_location == no_location:
                                how_voted = "no"
                            elif vote_location == noVt_location:
                                how_voted = "other"
                            elif vote_location == exAb_location:
                                how_voted == "absent"
                            else:
                                how_voted = "excused"

                            self.archived_votes[bill_id][
                                (
                                    vote_date,
                                    r_number,
                                    action_number,
                                    action_vote_result,
                                    archive_url,
                                    cod,
                                    chamber,
                                )
                            ].append({"leg": rep_name, "how_voted": how_voted})
                        else:
                            break

    def scrape(self, session=None, chamber=None, start=None):
        # OPEN-321: `start` is accepted and ignored. run-scrape.sh and cloud_collector.py both
        # append start=<watermark minus one hour> whenever a watermark exists (every run after a
        # jurisdiction's first), and without this parameter NC's second run died with
        # "unexpected keyword argument 'start'". The
        # FiledBillsFeed has no changed-since filter to hand it to, so NC full-walks every run
        # (same as MA, which also ignores start).
        chambers = [chamber] if chamber else ["upper", "lower"]

        if session in ["1997", "1999"]:
            self.scrape_archived_votes("upper", session)
            self.scrape_archived_votes("lower", session)

        for chamber in chambers:
            yield from self.scrape_chamber(chamber, session)

    def scrape_chamber(self, chamber, session):
        chamber = {"lower": "House", "upper": "Senate"}[chamber]
        chamber_abbr = "S" if chamber == "Senate" else "H"
        url = f"https://www.ncleg.gov/Legislation/Bills/FiledBillsFeed/{session}/{chamber_abbr}"

        page = self.get(url).content
        data = lxml.etree.fromstring(page)

        for item in data[0][4:]:
            bill_id = item[1].text
            bill_type = item[7].text
            bill_title = item[4].text

            # Special cases for a page that 404s
            if session == "2009" and bill_id == "H234":
                continue
            if session == "2003E3" and bill_id == "S2":
                continue
            yield from self.scrape_bill(
                chamber, session, bill_id, bill_type, bill_title
            )


def vote_list_to_names(names):
    title, rest = names.split(": ", 1)
    if "None" in rest:
        return []
    return rest.split("; ")
