import datetime
import mimetypes
import urllib.parse
from typing import Literal

import lxml.etree
import pytz

old_base_url = "https://www.legis.state.pa.us"
base_url = "https://www.palegis.us"
urls = {
    "people": {
        "upper": "{}/senate/members".format(base_url),
        "lower": "{}/house/members".format(base_url),
    },
    "committees": {
        "upper": "{}/senate/committees/committee-list".format(base_url),
        "lower": "{}/house/committees/committee-list".format(base_url),
    },
    "events": {
        "upper": "{}/senate/committees/meeting-schedule".format(base_url),
        "lower": "{}/house/committees/meeting-schedule".format(base_url),
    },
    "contacts": {
        "upper": "{}/senate/committees/member-assignments".format(base_url),
        "lower": "{}/house/committees/member-assignments".format(base_url),
    },
}


def bill_abbr(chamber):
    if chamber == "upper":
        return "S"
    else:
        return "H"


def start_year(session):
    return session[0:4]


def bill_list_url(chamber, session, special):
    return (
        "https://www.palegis.us/legislation/bills/bill-index?&display=index"
        "&sessyr=%s&sessind=%s&billbody=%s"
        % (start_year(session), special, bill_abbr(chamber))
    )


def bill_history_url(session, special):
    # OPEN-574: the legislature's "Bill History Data" download (https://www.palegis.us/data),
    # one zipped XML file per session, rebuilt daily, with every bill's lastUpdate time and
    # full action history
    return (
        "https://www.palegis.us/data/file?documentType=BillHistoryData&session=%s_%s"
        % (start_year(session), special)
    )


def bill_key(bill_id):
    # "HB 17" (bill-index link text) -> "HB17"
    return bill_id.replace(" ", "").upper()


def _export_time(text):
    # "November 15, 2026 7:30:14 PM EST" -> aware datetime
    text, zone = text.strip().rsplit(" ", 1)
    offset = {"EST": -5, "EDT": -4}[zone]
    naive = datetime.datetime.strptime(text, "%B %d, %Y %I:%M:%S %p")
    return naive.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=offset)))


def bills_changed_since(xml_bytes, since):
    """OPEN-574: read a Bill History Data export and return (export_date, changed, known).

    `since` is an aware datetime. A bill is changed when its lastUpdate is at or after
    `since`, or when any of its actions is dated on or after `since`'s Eastern date. The
    action dates are needed as well: lastUpdate is not always moved when an action is
    added (HR 590 of 2025: "Adopted, Sept. 9, 2026" is dated 09/10/26, its lastUpdate is
    09/08/26). `known` is every bill in the export, so a caller can still scrape a bill the
    export does not list yet. Keys are "HB17"-style, as bill_key() makes them.
    """
    root = lxml.etree.fromstring(xml_bytes)
    export_date = _export_time(root.get("exportDate"))
    since_day = since.astimezone(pytz.timezone("America/New_York")).date()
    changed, known = set(), set()
    for bill in root.iter("bill"):
        key = "%s%s%d" % (
            bill.findtext("body"),
            bill.findtext("type"),
            int(bill.findtext("number")),
        )
        known.add(key)
        if _export_time(bill.get("lastUpdate")) >= since:
            changed.add(key)
            continue
        for action_date in bill.iterfind("actionHistory/action/date"):
            if (
                action_date.text
                and datetime.datetime.strptime(action_date.text, "%m/%d/%y").date()
                >= since_day
            ):
                changed.add(key)
                break
    return export_date, changed, known


def supporting_documents(xml_bytes):
    """OPEN-576: the fiscal and actuarial notes a Bill History export lists, as
    {"HB1088": [(note, url), ...]}, named as the bill page's links are named by
    PABillScraper.parse_bill_versions ("House Fiscal Note", "Senate Fiscal Note",
    "Actuarial Note PN1888"), in the export's order. Other document kinds are left out,
    as the page parser leaves them out.

    Addresses are decoded: the export writes a space as %20 ("ALTR_HB%20349_PN3943.pdf")
    where the page, and so the stored row, has the space itself, and the two must match
    for add_document_link's duplicate check (HB 349, HB 797).
    """
    root = lxml.etree.fromstring(xml_bytes)
    documents = {}
    for bill in root.iter("bill"):
        key = "%s%s%d" % (
            bill.findtext("body"),
            bill.findtext("type"),
            int(bill.findtext("number")),
        )
        notes = []
        for pn_docs in bill.iterfind("supportingDocuments/pnSupportingDocuments"):
            for doc in pn_docs.iterfind("document"):
                title = (doc.text or "").strip()
                url = urllib.parse.unquote(doc.get("documentUrl") or "")
                if not url:
                    continue
                if "Fiscal Note" in title:
                    notes.append((title, url))
                elif "Actuarial Note" in title:
                    notes.append(
                        ("Actuarial Note PN%s" % pn_docs.get("relatedPN"), url)
                    )
        if notes:
            documents[key] = notes
    return documents


def document_media_type(url):
    # the export gives no type; the page's icons say PDF for every note link seen so far
    return mimetypes.guess_type(urllib.parse.urlsplit(url).path)[0] or ""


def info_url(session, special, bill_number):
    bill_number = bill_number.replace(" ", "").lower()
    if special == 0:
        return "https://www.palegis.us/legislation/bills/%s/%s" % (
            start_year(session),
            bill_number,
        )
    else:
        return "https://www.palegis.us/legislation/bills/%s/%s/%s" % (
            start_year(session),
            special,
            bill_number,
        )


def vote_url(chamber, year, special, rc_number):
    return (
        "https://www.palegis.us/%s/roll-calls/summary?sessYr=%s&sessInd=%s&rcNum=%s"
        % (
            chamber,
            year,
            special,
            rc_number,
        )
    )


def committee_vote_url(
    chamber, year, special, bill_body, biil_type, bill_num, comm_code
):
    return (
        "https://www.palegis.us/%s/committees/roll-call-votes/vote-list?"
        "sessYr=%s&sessInd=%s&billBody=%s&billType=%s&billNum=%s&committeeCode=%s"
        % (
            chamber,
            year,
            special,
            bill_body,
            biil_type,
            bill_num,
            comm_code,
        )
    )


def parse_action_date(date_str):
    date_str = date_str.lower()
    date_str = date_str.replace("sept", "september")
    date_str = date_str.replace(",", "").replace(".", "")
    try:
        return datetime.datetime.strptime(date_str, "%B %d %Y")
    except ValueError:
        return datetime.datetime.strptime(date_str, "%b %d %Y")


def get_sponsor_chamber(name: str) -> Literal["upper", "lower"]:
    chamber = None
    if "Sen." in name or "Senator" in name:
        chamber = "upper"
    elif "Rep." in name or "Representative" in name:
        chamber = "lower"
    return chamber


def clean_sponsor_name(name: str) -> str:
    if name:
        name = (
            name.replace("Senator", "")
            .replace("Representative", "")
            .replace("Sen.", "")
            .replace("Rep.", "")
            .strip()
            .title()
        )
        # Bill pages put "Sponsor Withdrew" where a withdrawn sponsor's name was
        if name == "Sponsor Withdrew":
            return ""
        return name
    else:
        return ""
