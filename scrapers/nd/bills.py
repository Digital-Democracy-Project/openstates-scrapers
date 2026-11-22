import logging
import re
from dateutil import parser
from openstates.scrape import Scraper, Bill, VoteEvent
import pytz
from spatula import JsonPage
from .actions import NDCategorizer
import lxml.html
import requests

from classify_motion import classify_motion

# OPEN-679: a vote modal's title is "Final Passage" (passage, from the nd block of
# config/motion_classification.yaml) or "Consideration of Amendments" (a division or amendment
# roll call, labelled here because the YAML only decides passage). Any other title stays unlabelled.
OTHER_VOTE_KINDS = (
    (re.compile(r"^motion for consideration of amendments on ", re.I), "amendment"),
)


def vote_classification(motion):
    classification = classify_motion("nd", motion)
    if classification:
        return classification
    for pattern, kind in OTHER_VOTE_KINDS:
        if pattern.search(motion):
            return [kind]
    return []


def site_session(session):
    """OPEN-746: the Legislative Assembly whose bill list holds a session's bills on ndlegis.gov
    ("69-2025") and the tag the site gives each of that session's bills (`session_id`, "202502"
    for the Special Session of January 2026). A special session names both in its `extras`; a
    regular session's are its identifier and start year ("69-2025", "202501")."""
    extras = session.get("extras", {})
    year = session["start_date"][:4]
    return (
        extras.get("assembly", f"{session['identifier']}-{year}"),
        extras.get("site_session_id", f"{year}01"),
    )


class BillList(JsonPage):
    categorizer = NDCategorizer()
    member_name_re = re.compile(r"^(Sen\.|Rep\.)\s*(.+),\s(.+)")
    comm_name_re = re.compile(r"^(House|Senate)\s*(.+)")
    version_name_re = re.compile(r"introduced|engrossment|enrollment")
    members_cache = {}
    title_re = re.compile(r"^(Representative|Senator)\s+")

    _tz = pytz.timezone("US/Central")

    def __init__(self, input_data):
        super().__init__()
        self.input = input_data
        self.source = self.create_source_url()

    def create_source_url(self):
        """
        Returns the API URL of the bill list of the session's Legislative Assembly.
        """
        return (
            f"https://ndlegis.gov/api/assembly/"  # noqa: E231
            f"{self.input.get('assembly')}/data/bills.json"
        )

    def get_voter_name_from_url_request(self, url: str) -> str:
        """
        Description:
            Get the full name from URL Request

        Example:
            - https://ndlegis.gov/biography/liz-conmy -> Liz Conmy
            - https://ndlegis.gov/biography/randy-a-schobinger -> Randy A. Schobinger

        """
        if url in self.members_cache:
            return self.members_cache[url]

        html_content = requests.get(url).content
        doc = lxml.html.fromstring(html_content)
        doc.make_links_absolute(url)

        fullname = doc.xpath("string(//h1)").strip()

        if fullname == "":
            # at least one ND biography page is returning 404 as of 1/15/25
            # so here's a dumb fallback to get name literally from the URL
            url_name = url.replace("https://ndlegis.gov/biography/", "")
            name_with_spaces = url_name.replace("-", " ")
            fullname = name_with_spaces.title()

        # OPEN-722: return the same title-stripped name that is cached; returning the raw <h1> text
        # gave each member's first roll call of a run "Representative X" / "Senator X", matching no one.
        # Only a leading title word is removed, never one inside the name.
        name = self.title_re.sub("", fullname).strip()
        self.members_cache[url] = name

        return name

    def process_page(self):
        json_response = self.response.json()
        bills = json_response.get("bills")
        for bill_key in bills.keys():
            bill_data = bills[bill_key]
            bill_id = bill_data["name"]
            # OPEN-746: the assembly's list holds its regular session's bills and its special
            # sessions'; keep only this session's, by the site's own tag on the bill. Its roll
            # calls, read from its own bill-actions page below, go with it.
            if bill_data.get("session_id") != self.input.get("site_session_id"):
                continue

            bill_type_abbr = bill_id[0:3].strip()
            bill_type = "bill"
            if bill_type_abbr in ("HR", "SR"):
                bill_type = "resolution"
            if bill_type_abbr in ("HCR", "SCR"):
                bill_type = "concurrent resolution"
            if bill_type_abbr in ("HMR", "SMR"):
                bill_type = "memorial"

            bill = Bill(
                identifier=bill_id,
                legislative_session=self.input.get("session"),
                title=bill_data["title"],
                chamber="lower" if bill_data["chamber"] == "House" else "upper",
                classification=bill_type,
            )

            bill.add_source(bill_data["url"], note="HTML bill detail page")
            bill.add_source(self.source.url, note="JSON page of session bills")

            if bill_data["summary"]:
                bill.add_abstract(bill_data["summary"], note="summary")

            chambers = {
                "House": "lower",
                "Senate": "upper",
            }

            sponsors_list = bill_data["sponsors"]

            for sponsor in sponsors_list:
                primary = True if sponsor["primary"] else False
                entity_types = {
                    "legislator": "person",
                    "committee": "organization",
                }
                chamber_val = sponsor["chamber"]
                sponsor_chamber = (
                    chambers[chamber_val] if chamber_val else "legislature"
                )
                raw_sponsor_name = sponsor["name"]
                chamber_comm_match = self.comm_name_re.search(raw_sponsor_name)
                member_match = self.member_name_re.search(raw_sponsor_name)
                if chamber_comm_match:
                    sponsor_name = chamber_comm_match.groups()[1]
                elif member_match:
                    last, first = member_match.groups()[1:]
                    sponsor_name = f"{first} {last}"
                else:
                    sponsor_name = raw_sponsor_name

                bill.add_sponsorship(
                    name=sponsor_name,
                    classification="primary" if primary else "cosponsor",
                    entity_type=entity_types[sponsor["type"]],
                    primary=primary,
                    chamber=sponsor_chamber,
                )

            action_list = bill_data["actions"]
            for action in action_list:
                chamber_val = action["chamber"]
                actor = chambers[chamber_val] if chamber_val else "legislature"
                description = action["description"]
                classifier = self.categorizer.categorize(description)
                bill.add_action(
                    description=description,
                    date=parser.parse(action["date"]).strftime("%Y-%m-%d"),
                    chamber=actor,
                    classification=classifier["classification"],
                )

            version_list = bill_data["versions"]
            for version in version_list:
                description = version["description"]
                if description == "":
                    description = version["document_url"].split("/")[-1]
                version_match = self.version_name_re.search(description.lower())
                if version_match:
                    bill.add_version_link(
                        note=description,
                        url=version["document_url"],
                        media_type="application/pdf",
                    )
                else:
                    bill.add_document_link(
                        note=description,
                        url=version["document_url"],
                        media_type="application/pdf",
                    )

            yield bill

            # Get bill-actions url from bill-overview url
            action_url = (
                bill_data["url"]
                .replace("/bo", "/ba")
                .replace("bill-overview", "bill-actions")
            )

            html_content = requests.get(action_url).content
            doc = lxml.html.fromstring(html_content)
            doc.make_links_absolute(action_url)
            votes_list = doc.xpath(
                '//div[@aria-labelledby="vote-modal"]//div[@class="modal-content"]'
            )
            votes_seen_for_bill = []
            for vote_modal in votes_list:
                motion_text = (
                    vote_modal.xpath('.//h5[@class="modal-title"]')[0]
                    .text_content()
                    .strip()
                )
                modal_id = vote_modal.xpath("../..")[0].attrib["id"]
                # OPEN-757: the modal id is the site's roll-call id ("vote-modal-202501S01000": session,
                # chamber, roll-call number), so it is the vote's dedupe_key, with the page URL (assembly,
                # bill). Without a key the importer matches on motion text + time + chamber, and HB 1015's
                # two Senate division roll calls (04/22/2025 01:47 PM) collided and stopped the load.
                dedupe_key = f"{action_url}#{modal_id}"
                if dedupe_key in votes_seen_for_bill:
                    # at least one ND bill has duplicate votes
                    # so skip if we have seen this vote already
                    self.logger.warning(
                        f"Skipped duplicate vote {modal_id} on {bill_id}"
                    )
                    continue
                else:
                    votes_seen_for_bill.append(dedupe_key)
                date = parser.parse(
                    vote_modal.xpath(
                        './/div[@class="modal-body"]/span[@class="float-right"]'
                    )[0]
                    .text_content()
                    .strip()
                )
                start_date = self._tz.localize(date)
                status = (
                    vote_modal.xpath('.//div[@class="modal-body"]/span[@class="bold"]')[
                        0
                    ]
                    .text_content()
                    .strip()
                )
                chamber = "lower" if "house" in status.lower() else "upper"
                status = "pass" if "passed" in status.lower() else "fail"
                motion = f"Motion for {motion_text} on {bill_id}"
                vote = VoteEvent(
                    chamber=chamber,
                    start_date=start_date,
                    motion_text=motion,
                    result=status,
                    legislative_session=self.input.get("session"),
                    classification=vote_classification(motion),
                    bill=bill_id,
                    bill_chamber="lower" if bill_id[0] == "H" else "upper",
                )
                vote.dedupe_key = dedupe_key
                vote.add_source(action_url)
                yes_count = (
                    vote_modal.xpath(
                        './/div[@class="modal-body"]/div[./h6[contains(., "Yea")]]/h6'
                    )[0]
                    .text_content()
                    .strip()
                    .split(" ")[0]
                )
                no_count = (
                    vote_modal.xpath(
                        './/div[@class="modal-body"]/div[./h6[contains(., "Nay")]]/h6'
                    )[0]
                    .text_content()
                    .strip()
                    .split(" ")[0]
                )
                other_count = (
                    vote_modal.xpath(
                        './/div[@class="modal-body"]/div[./h6[contains(., "Absent")]]/h6'
                    )[0]
                    .text_content()
                    .strip()
                    .split(" ")[0]
                )

                vote.set_count("yes", int(yes_count))
                vote.set_count("no", int(no_count))
                vote.set_count("other", int(other_count))
                for vote_link in vote_modal.xpath(
                    './/div[@class="modal-body"]/div[./h6[contains(., "Yea")]]//a'
                ):
                    voter_url = vote_link.attrib["href"]
                    voter_name = self.get_voter_name_from_url_request(voter_url)
                    vote.yes(voter_name)
                for vote_link in vote_modal.xpath(
                    './/div[@class="modal-body"]/div[./h6[contains(., "Nay")]]//a'
                ):
                    voter_url = vote_link.attrib["href"]
                    voter_name = self.get_voter_name_from_url_request(voter_url)
                    vote.no(voter_name)
                for vote_link in vote_modal.xpath(
                    './/div[@class="modal-body"]/div[./h6[contains(., "Absent")]]//a'
                ):
                    voter_url = vote_link.attrib["href"]
                    voter_name = self.get_voter_name_from_url_request(voter_url)
                    vote.vote("other", voter_name)

                yield vote


class NDBillScraper(Scraper):
    def scrape(self, session=None):
        (found,) = [
            i
            for i in self.jurisdiction.legislative_sessions
            if i["identifier"] == session
        ]
        assembly, site_session_id = site_session(found)
        logging.getLogger("scrapelib").setLevel(logging.WARNING)
        bill_list = BillList(
            {
                "session": session,
                "assembly": assembly,
                "site_session_id": site_session_id,
            }
        )
        yield from bill_list.do_scrape()
