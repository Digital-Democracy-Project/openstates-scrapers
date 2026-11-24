import re
import datetime
import collections
import unicodedata

from lxml import html
from utils import checked_requests
import scrapelib

from urllib import parse

from openstates.scrape import Scraper, Bill, VoteEvent as Vote
from .actions import Categorizer
from .sessions import listing_session, session_for_day

from classify_motion import classify_motion
from utils import presiding_officers

# What separates two voters on a vote-roll line (OPEN-802). The pages print names in
# fixed-width Courier columns padded with spaces, so two names are always two or more spaces
# apart, while the words of one entry are one space apart: a surname of two or more words
# ("Crosswhite Hader"), a title ("Mr. Speaker"), a disambiguator ("West (J)"). Measured on
# all 3,741 House and Senate vote pages of 2025-2026: every section yields exactly its
# declared count this way. No member's name is written here.
NAME_GAP = re.compile(r"\s{2,}")

# OPEN-687: a floor amendment roll call ("Adopt Amendment", "Table Amendment"), labelled
# here because config/motion_classification.yaml only decides passage.
AMENDMENT_VOTE = re.compile(r"\bamendment\b", re.I)


def vote_classification(motion, committee):
    """What a roll call decides. A committee roll call is committee-passage, whatever
    its text (the Senate's is often just the committee's name). A floor roll call is
    passage from the ok block of config/motion_classification.yaml, else "amendment"
    for an amendment roll call, else nothing."""
    if committee:
        return ["committee-passage"]
    classification = classify_motion("ok", motion)
    if classification:
        return classification
    if AMENDMENT_VOTE.search(motion):
        return ["amendment"]
    return []


# OPEN-704: the House page states each roll call's outcome on its own line above the
# counts ("THIRD PASSED", "FAILED" for an emergency clause); the Senate page does not.
STATED_RESULT = re.compile(r"\b(PASSED|FAILED)$")

# OPEN-790: House roll calls print the presiding Speaker as "Mr. Speaker"; who that is comes
# from the manifest (utils/presiding_officers.py). The Senate prints no title.
PRESIDING_OFFICERS = {"Mr. Speaker": ("lower", "house_speaker_by_session")}

# Members elected to each chamber, which the constitution's supermajorities count from.
CHAMBER_SIZE = {"lower": 101, "upper": 48}


def vote_result(chamber, motion, committee, stated, yes_count, no_count):
    """'pass' or 'fail' for one roll call: the outcome the page states, else the vote's
    own threshold. Oklahoma Constitution Art. V sec. 58: an emergency clause needs
    two-thirds of all members elected to each House, and a vetoed emergency measure
    three-fourths of each House; Art. VI sec. 11: a veto override needs two-thirds of
    the members elected. Everything else (committee votes included) passes on more yeas
    than nays."""
    if stated:
        return "pass" if stated == "PASSED" else "fail"
    if not committee:
        size = CHAMBER_SIZE[chamber]
        if re.match(r"veto override with emer", motion, re.I):
            return "pass" if 4 * yes_count >= 3 * size else "fail"
        if re.match(r"veto override", motion, re.I) or motion.lower() == "emergency":
            return "pass" if 3 * yes_count >= 2 * size else "fail"
    return "pass" if yes_count > no_count else "fail"


def extract_names(line, limit):
    """Extract up to `limit` legislator names from a vote-roll line.

    The line is split on the column gaps (NAME_GAP), so a name of several words stays one
    voter. Stopping at `limit` (the declared count for this vote type, read from the same
    block) keeps trailing free text -- e.g. a "STRIKE THE TITLE - ADOPTED" outcome line
    that sometimes follows a zero-count section before the "*****" separator -- from being
    mistaken for votes.
    """
    names = []
    for name in NAME_GAP.split(line.replace("\n", " ").strip()):
        if len(names) >= limit:
            break
        if not name or "HOUSE" in name or "SENATE" in name:
            continue
        names.append(name)
    return names


class OKBillScraper(Scraper):
    bill_types = ["B", "JR", "CR", "R"]
    subject_map = collections.defaultdict(list)

    categorizer = Categorizer()

    # Can be found in the session select dropdown at
    # http://www.oklegislature.gov/TextOfMeasures.aspx
    meta_session_id = {
        "2011": "1100",
        "2012": "1200",
        "2012SS1": "121X",
        "2013SS1": "131X",
        "2013": "1300",
        "2014": "1400",
        "2015": "1500",
        "2016": "1600",
        "2017SS1": "171X",
        "2017SS2": "172X",
        "2017": "1700",
        "2018": "1800",
        "2019": "1900",
        "2020": "2000",
        "2020SS1": "201X",
        "2021": "2100",
        "2021SS1": "211X",
        "2022": "2200",
        "2022SS2": "222X",
        "2022SS3": "223X",
        "2023": "2300",
        "2023S1": "231X",
        "2023S2": "232X",
        "2024": "2400",
        "2024S3": "243X",
        "2024S4": "244X",
        "2025": "2500",
        "2026": "2600",
        "2027": "2700",
    }

    def listing_code(self, session):
        """The search form's code for the list the scrape of `session` reads (OPEN-758): a
        regular session reads its Legislature's newest list, which holds both years' bills."""
        return self.meta_session_id[
            listing_session(self.jurisdiction.legislative_sessions, session)
        ]

    def scrape(self, chamber=None, session=None, only_bills=None):
        chambers = [chamber] if chamber else ["upper", "lower"]
        for chamber in chambers:
            yield from self.scrape_chamber(chamber, session, only_bills)

    def scrape_chamber(self, chamber, session, only_bills):
        # start by building subject map
        self.scrape_subjects(chamber, session)

        url = "https://webapps.oklegislature.gov/WebApplication3/WebForm1.aspx"
        requests_session = checked_requests.Session()
        form_page = html.fromstring(requests_session.get(url).text)

        if chamber == "upper":
            chamber_letter = "S"
        else:
            chamber_letter = "H"

        session_id = self.listing_code(session)
        self.debug("Using session slug `{}`".format(session_id))
        values = {
            "cbxSessionId": session_id,
            "cbxActiveStatus": "All",
            "RadioButtonList1": "On Any day",
            "Button1": "Retrieve",
        }

        lbxTypes = []
        for bill_type in self.bill_types:
            lbxTypes.append(chamber_letter + bill_type)
        values["lbxTypes"] = lbxTypes

        for hidden in form_page.xpath("//input[@type='hidden']"):
            values[hidden.attrib["name"]] = hidden.attrib["value"]

        headers = {
            "Cookie": f"ASP.NET_SessionId={requests_session.cookies.get('ASP.NET_SessionId')}",
            "x-oxylabs-force-headers": "1",
        }
        response = requests_session.post(url, data=values, headers=headers)
        page = response.text
        page = html.fromstring(page)
        page.make_links_absolute(url)

        bill_nums = []
        for row in page.xpath("//tr"):  # [0].xpath("./td[last()]")[0].text_content()
            title = row.xpath("./td[last()]")[0].text_content()
            if title.strip() == "Title":
                # Skip the header row
                continue
            if "test bill" in title.lower() or "please disregard" in title.lower():
                # Skip test bills
                # some test bills are in a bill number range < 9900
                # which can overlap with real bills (historically, eg 2024 SB 9134)
                # so added a title text check for these test bills as well as
                # the number check below
                self.warning("skipping likely bad bill due to title %s" % title)
                continue
            link = row.xpath(".//a")[0]
            bill_id = link.text.strip()
            bill_num = int(re.findall(r"\d+", bill_id)[0])
            if bill_num >= 9900:
                # We should have skipped test bills with new method above
                # but leaving this here just in case
                self.warning("skipping likely bad bill due to identifier %s" % bill_id)
                continue
            if only_bills is not None and bill_id not in only_bills:
                self.warning("skipping bill we are not interested in %s" % bill_id)
                continue
            bill_nums.append(bill_num)
            yield from self.scrape_bill(chamber, session, bill_id, link.attrib["href"])

    def scrape_bill(self, chamber, session, bill_id, url):
        try:
            page = html.fromstring(self.get(url).text)
        except scrapelib.HTTPError as e:
            self.warning("error (%s) fetching %s, skipping" % (e, url))
            return

        title = page.xpath(
            "string(//span[contains(@id, 'PlaceHolder1_txtST')])"
        ).strip()
        if not title:
            self.warning("blank bill on %s - skipping", url)
            return

        if "JR" in bill_id:
            bill_type = ["joint resolution"]
        elif "CR" in bill_id:
            bill_type = ["concurrent resolution"]
        elif "R" in bill_id:
            bill_type = ["resolution"]
        else:
            bill_type = ["bill"]

        bill = Bill(
            bill_id,
            legislative_session=session,
            chamber=chamber,
            title=title,
            classification=bill_type,
        )
        bill.add_source(url)
        bill.subject = self.subject_map[bill_id]

        for link in page.xpath("//a[contains(@id, 'Auth')]"):
            name = link.xpath("string()").strip()
            if "author not found" in name.lower():
                continue

            if ":" in name:
                raise Exception(name)
            if "otherAuth" in link.attrib["id"]:
                bill.add_sponsorship(
                    name,
                    classification="cosponsor",
                    entity_type="person",
                    primary=False,
                )
            else:
                bill.add_sponsorship(
                    name, classification="primary", entity_type="person", primary=True
                )

        act_table = page.xpath("//table[contains(@id, 'Actions')]")[0]
        for tr in act_table.xpath("tr")[2:]:
            action = tr.xpath("string(td[1])").strip()
            if not action or action == "None":
                continue

            date = tr.xpath("string(td[3])").strip()
            date = datetime.datetime.strptime(date, "%m/%d/%Y").date()

            actor = tr.xpath("string(td[4])").strip()
            if actor == "H":
                actor = "lower"
            elif actor == "S":
                actor = "upper"

            attrs = self.categorizer.categorize(action)
            related_entities = []
            for item in attrs["committees"]:
                related_entities.append({"type": "committee", "name": item})
            for item in attrs["legislators"]:
                related_entities.append({"type": "legislator", "name": item})
            bill.add_action(
                description=action,
                date=date.strftime("%Y-%m-%d"),
                chamber=actor,
                classification=attrs["classification"],
                related_entities=related_entities,
            )

        # OPEN-758: both years of a Legislature read the same list; a bill belongs to one session
        # only, the one its first dated action falls in (sessions.py)
        sessions = self.jurisdiction.legislative_sessions
        first_action = min(
            (datetime.date.fromisoformat(a["date"]) for a in bill.actions), default=None
        )
        owner = session_for_day(sessions, session, first_action)
        if owner is None:
            self.warning(f"Skipping {bill_id}: no dated action on {url}")
            return
        if owner != session:
            self.info(f"Skipping {bill_id}: it belongs to {owner}")
            return

        version_table = page.xpath("//table[contains(@id, 'Versions')]")[0]
        # Keep track of already seen versions to prevent processing duplicates.
        version_urls = []
        for link in version_table.xpath(".//a[contains(@href, '.PDF')]"):
            version_url = link.attrib["href"]
            if version_url in version_urls:
                self.warning("Skipping duplicate version URL.")
                continue
            else:
                version_urls.append(version_url)

            if link.text is None:
                self.warning("Skipping unnamed version.")
                continue

            name = link.text.strip()

            if re.search("COMMITTEE REPORTS|SCHEDULED CCR", version_url, re.IGNORECASE):
                bill.add_document_link(
                    note=name, url=version_url, media_type="application/pdf"
                )
                continue

            bill.add_version_link(
                note=name, url=version_url, media_type="application/pdf"
            )

        self.scrape_amendments(bill, page)

        for link in page.xpath(".//a[contains(@href, '_VOTES')]"):
            if "HT_" not in link.attrib["href"]:
                for vote in self.scrape_votes(
                    bill, self.urlescape(link.attrib["href"])
                ):
                    # OPEN-758: a roll call is filed under the session of its own date, and
                    # stays linked to its bill (a 2025 bill's 2026 roll call goes to 2026)
                    vote.legislative_session = session_for_day(
                        sessions, session, datetime.date.fromisoformat(vote.start_date)
                    )
                    yield vote

        # # If the bill has no actions and no versions, it's a bogus bill on
        # # their website, which appears to happen occasionally. Skip.
        has_no_title = bill.title == "Short Title Not Found."
        if has_no_title:
            # If there's no title, this is an empty page. Skip!
            return

        else:
            # Otherwise, save the bills.
            yield bill

    def scrape_amendments(self, bill, page):
        amd_xpath = (
            '//table[@id="ctl00_ContentPlaceHolder1_'
            'TabContainer1_TabPanel2_tblAmendments"]//a[contains(@href,".PDF")]'
        )

        for link in page.xpath(amd_xpath):
            version_url = link.xpath("@href")[0]
            version_name = link.xpath("string(.)").strip()
            bill.add_version_link(
                version_name, version_url, media_type="application/pdf"
            )

    def scrape_votes(self, bill, url):
        html_content = unicodedata.normalize(
            "NFKD", self.get(url).text.replace("\r\n", " ")
        )
        page = html.fromstring(html_content)

        seen_rcs = set()
        motions = {}
        # roll calls the page's link list marks as committee votes
        committee_rcs = set()
        headers_xpath = page.xpath('//p[contains(., "Top_of_Page")]')

        for motion in page.xpath(
            '//a[contains(@href, "#")][not(contains(@href,"Top_of_Page"))]'
        ):
            motion_text = motion.xpath("string()").strip("#").replace("_", " ")
            motion_link = motion.xpath("@href")[0].strip("#").replace("RCS", "")

            if "committee" in motion_text.lower() and "RCS" not in motion_text:
                motion_index = (
                    motion_link.lstrip("0").zfill(1)
                    if motion_link.isdigit()
                    else motion_link.split("_")[1].lstrip("0").zfill(1)
                )
                do_pass_motion = motion_link.split("_")
                do_index = do_pass_motion.index("DO") if "DO" in do_pass_motion else -1
                passed_index = (
                    do_pass_motion.index("PASSED")
                    if "PASSED" in do_pass_motion
                    else do_pass_motion.index("FAILED")
                    if "FAILED" in do_pass_motion
                    else -1
                )
                do_pass_motion = (
                    " ".join(do_pass_motion[do_index:passed_index]).strip().title()
                )
                motion_text = do_pass_motion or "Do Pass"
                committee_rcs.add(motion_index)
            else:
                motion_index = motion_link.lstrip("0").zfill(1)
                if "OKLAHOMA" in motion_text:
                    motion_text = "Committee Vote"
                else:
                    motion_text = motion_text.split("(")[0].strip().title()
                if motion_text == "Committee Vote":
                    committee_rcs.add(motion_index)

            motions[motion_index] = motion_text

        for header in headers_xpath:
            bad_vote = False
            # Each chamber has the motion name on a different line of the file
            if "house" in url.lower():
                chamber = "lower"
            else:
                chamber = "upper"

            rcs_xpath = header.xpath(
                "following-sibling::p[contains(., '***')][1]/preceding-sibling::p[contains(., 'RCS#')][1]"
            )

            if rcs_xpath:
                rcs_p = rcs_xpath[0]
                rcs_line = rcs_p.xpath("string()").replace("\xa0", " ")
                rcs = re.search(r"RCS#\s+(\d+)", rcs_line).group(1)
                if rcs in seen_rcs:
                    continue
                else:
                    seen_rcs.add(rcs)
            else:
                continue
            committees = [
                "Administrative Rules",
                "Aeronautics And Transportation",
                "Aeronautics & Transportation",
                "Agriculture And Rural Affairs",
                "Agriculture & Rural Affairs",
                "Appropriations",
                "Business and Commerce",
                "Business & Commerce",
                "Education",
                "Energy And Telecommunications",
                "Energy & Telecommunications",
                "Finance",
                "General Government",
                "Health And Human Services",
                "Health & Human Services",
                "Judiciary",
                "Public Safety",
                "Retirement And Insurance",
                "Retirement & Insurance",
                "Rules",
                "Tourism And Wildlife",
                "Tourism & Wildlife",
                "Veterans And Military Affairs",
                "Veterans & Military Affairs",
                "Committee",
                "Subcommittee",
            ]

            motion_text = motions.get(rcs, "Committee Vote")
            # committee only when the link list says so; a roll call missing from it
            # stays unlabelled (its motion text "Committee Vote" matches no rule)
            committee = rcs in committee_rcs
            committee_motion = ""

            if "Do Pass" in motion_text or "Committee" in motion_text:
                for line in header.xpath("following-sibling::p"):
                    line_text = (
                        line.xpath("string()").replace("  ", " ").title().strip()
                    )
                    if "*****" in line_text:
                        break
                    if not committee_motion:
                        filter_motion = [
                            committee
                            for committee in committees
                            if committee in line_text
                            and "Motion By Senator" not in line_text
                        ]
                        if len(filter_motion) > 0:
                            committee_motion = line_text
                        continue

                    if "Motion By Senator" in line_text:
                        committee_motion += ": " + line_text
                        break

                    if "Do Pass" in line_text and (
                        "Passed" in line_text or "Failed" in line_text
                    ):
                        do_pass_motion = (
                            motion_text
                            if "Do Pass" in motion_text
                            else line_text.replace("Passed", "")
                            .replace("Failed", "")
                            .replace("Recommendation:", "")
                            .replace("Strike The T", "Strike The Title")
                            .replace("Strike The E", "Strike The Enacting Clause")
                            .strip()
                        )
                        committee_motion += ": " + do_pass_motion
                        break

            motion = committee_motion or motion_text

            if not motion:
                self.warning("Motion text not found")
                continue

            stated = None

            date_line = rcs_p.getnext().xpath("string()")
            date = re.search(r"\d+/\d+/\d+", date_line)
            if not date:
                continue
            date = date.group(0)
            date = datetime.datetime.strptime(date, "%m/%d/%Y").date()

            vtype = None
            counts = collections.defaultdict(int)
            votes = collections.defaultdict(list)

            seen_yes = False

            for sib in header.xpath("following-sibling::p"):
                line = sib.xpath("string()").strip()
                if "*****" in line or "motion by" in line:
                    break
                regex = (
                    r"(YEAS|AYES|NAYS|EXCUSED|VACANT|VACANCY|CONSTITUTIONAL "
                    r"PRIVILEGE|NOT VOTING|N/V)\s*:\s*(\d+)(.*)"
                )
                if not seen_yes and not stated:
                    stated_match = STATED_RESULT.search(line)
                    if stated_match:
                        stated = stated_match.group(1)
                match = re.match(regex, line)
                if match:
                    if (match.group(1) in ["YEAS", "AYES"]) and "RCS#" not in line:
                        vtype = "yes"
                        seen_yes = True
                    elif match.group(1) == "NAYS" and seen_yes:
                        vtype = "no"
                    elif match.group(1) == "EXCUSED" and seen_yes:
                        vtype = "excused"
                    elif match.group(1) in ["NOT VOTING", "N/V"] and seen_yes:
                        vtype = "not voting"
                    elif match.group(1) in ["VACANT", "VACANCY"]:
                        continue  # skip these
                    elif seen_yes:
                        vtype = "other"
                    if seen_yes and match.group(3).strip():
                        self.warning("Bad vote format, skipping.")
                        bad_vote = True
                    counts[vtype] += int(match.group(2))
                elif seen_yes:
                    remaining = counts[vtype] - len(votes[vtype])
                    if remaining > 0:
                        votes[vtype].extend(extract_names(line, remaining))

            if bad_vote:
                continue

            vote = Vote(
                chamber=chamber,
                start_date=date.strftime("%Y-%m-%d"),
                motion_text=motion,
                result=vote_result(
                    chamber, motion, committee, stated, counts["yes"], counts["no"]
                ),
                bill=bill,
                classification=vote_classification(motion, committee),
            )
            vote.set_count("yes", counts["yes"])
            for name in votes["yes"]:
                self.add_voter(vote, "yes", name, chamber, bill.legislative_session)
            vote.set_count("no", counts["no"])
            for name in votes["no"]:
                if ":" in name:
                    raise Exception(name)
                self.add_voter(vote, "no", name, chamber, bill.legislative_session)
            for option in ("excused", "not voting"):
                if option in counts:
                    vote.set_count(option, counts[option])
                    for name in votes[option]:
                        self.add_voter(
                            vote, option, name, chamber, bill.legislative_session
                        )
            vote.set_count("other", counts["other"])
            for name in votes["other"]:
                self.add_voter(vote, "other", name, chamber, bill.legislative_session)
            vote.dedupe_key = url + "#" + rcs
            # OPEN-872: oklegislature.gov gives a roll call its day only; its RCS# rises in the order the
            # chamber took its votes (HB 1003's House, 2025-03-26: RCS 432, then 446, both Third Reading).
            # The broker reads this key into Motion.rollcall_num to order two same-day votes in one
            # chamber (as OPEN-628, OPEN-685 and OPEN-863 did for the other states). Committee and floor
            # roll calls are numbered in separate runs and 2026's restarts at 1, so compare two numbers
            # only for two floor votes (the passage ones) of one chamber on one day, nothing else.
            vote.extras[
                "senate-rollcall-num" if chamber == "upper" else "house-rollcall-num"
            ] = rcs

            vote.add_source(url)

            yield vote

    def add_voter(self, vote, option, name, chamber, session):
        """Record `name`'s vote; "Mr. Speaker" on a House roll call gets the session's Speaker
        from the manifest (OPEN-790), else stays as printed with one warning per session."""
        unnamed = presiding_officers.add_voter(
            vote, option, name, chamber, session, "ok", PRESIDING_OFFICERS
        )
        warned = self.__dict__.setdefault("_warned_officers", set())
        if unnamed and (unnamed, session) not in warned:
            warned.add((unnamed, session))
            self.warning(
                "OPEN-790: manifest ok.votes.%s has no %s; %r left as printed",
                unnamed,
                session,
                name,
            )

    def scrape_subjects(self, chamber, session):
        form_url = "https://webapps.oklegislature.gov/WebApplication3/WebForm1.aspx"
        form_html = self.get(form_url).text
        fdoc = html.fromstring(form_html)

        # bill types
        letter = "H" if chamber == "lower" else "S"
        types = [letter + t for t in self.bill_types]

        session_id = self.listing_code(session)

        # do a request per subject
        for subj in fdoc.xpath('//select[@name="lbxSubjects"]/option/@value'):
            # these forms require us to get hidden session keys
            values = {
                "cbxInclude": "All",
                "Button1": "Retrieve",
                "RadioButtonList1": "On Any Day",
                "cbxSessionID": session_id,
                "lbxSubjects": subj,
                "lbxTypes": types,
            }
            for hidden in fdoc.xpath("//input[@type='hidden']"):
                values[hidden.attrib["name"]] = hidden.attrib["value"]
            # values = urllib.urlencode(values, doseq=True)
            page_data = self.post(form_url, data=values).text
            page_doc = html.fromstring(page_data)

            # all links after first are bill_ids
            for bill_id in page_doc.xpath("//a/text()")[1:]:
                self.subject_map[bill_id].append(subj)

    def urlescape(self, url):
        scheme, netloc, path, qs, anchor = parse.urlsplit(url)
        path = parse.quote(path, "/%")
        qs = parse.quote_plus(qs, ":&=")
        return parse.urlunsplit((scheme, netloc, path, qs, anchor))
