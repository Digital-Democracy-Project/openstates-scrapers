"""OPEN-711: the bills a Rhode Island Senate consent-calendar roll call passed.

The Senate passes its consent calendar in one roll call whose vote report names no bill
(its whole header is "CONSENT CALENDAR", "Consent #2" or "#2"). The Senate Journal of that
day (a PDF on rilegislature.gov) prints each consent calendar in an appendix:

    CONSENT CALENDAR II
    IN ORDER FOR THURSDAY, JUNE 11, 2026:
    1.     2026-H 7630 SUB A
           ...
    Upon motion of Senator Tikoian, ... the following measures on
    Today's Consent Calendar, by unanimous consent, are read and passed, upon a roll call vote:
    YEAS – 38: ...
    NAYS – 0:

An item can be taken off before the vote ("Removed from the Consent Calendar and placed on
the Calendar on ..."); a nomination item has no bill number. The journal also prints the next
day's consent calendar ("IN ORDER FOR TUESDAY, APRIL 22, 2025:"), which was not voted that
day and is not read.
"""
import datetime as dt
import re

JOURNAL_URLS = [
    # 2026 names its journals "SJ 06-11-2026.pdf", 2025 "06-20-2025.pdf"
    "https://www.rilegislature.gov/journals/senatejournals/{year}%20Senate%20Journals/SJ%20{date}.pdf",
    "https://www.rilegislature.gov/journals/senatejournals/{year}%20Senate%20Journals/{date}.pdf",
]

# a consent roll call's whole header on the Senate vote report
CONSENT_HEADER = re.compile(r"^(consent calendar|consent\s*#\s*\d+|#\s*\d+)$", re.I)
# the appendix heading: "CONSENT CALENDAR", "CONSENT CALENDAR II", "CONSENT CALENDAR #3"
CALENDAR_HEADING = re.compile(r"^\s*CONSENT CALENDAR(\s+[IVX]+|\s*#\s*\d+)?\s*$")
IN_ORDER_FOR = re.compile(r"^\s*IN ORDER FOR \w+,\s+(\w+ \d{1,2}, \d{4}):?\s*$", re.I)
ITEM = re.compile(r"^\s*\d+\.\s+(\S.*)$")
ITEM_BILL = re.compile(r"^(?P<year>\d{4})-(?P<chamber>[HS])\s*(?P<bill>[1-9][0-9]*)\b")
REMOVED = re.compile(r"removed from the consent calendar", re.I)
# "The Appointment of ...", "The Reappointment of ...", "The Nomination of ...": not a bill
NOMINATION = re.compile(r"^the (re)?(appointment|nomination) of\b", re.I)
PASSED = re.compile(r"are read and passed,\s+upon a roll call vote:")
TALLY = re.compile(r"^\s*(YEAS|NAYS)\s*[–-]\s*(\d+)")
# any other appendix heading ("CALENDAR", "CONSENT CALENDAR III") or the next day's
# "IN ORDER FOR" ends a consent calendar that was not voted
OTHER_HEADING = re.compile(r"^\s*(CONSENT\s+)?CALENDAR(\s+[IVX]+|\s*#\s*\d+)?\s*$")


def journal_urls(date):
    """The Senate Journal URLs to try for a vote date such as "6/11/2026"."""
    d = dt.datetime.strptime(date, "%m/%d/%Y")
    return [u.format(year=d.year, date=d.strftime("%m-%d-%Y")) for u in JOURNAL_URLS]


def consent_calendars(text, date):
    """The consent calendars the Senate voted on `date` (a datetime.date), in journal order:
    a list of {"bills": [(year, "H"|"S", number), ...], "skipped": [first line of each
    nomination or removed item], "unread": [first line of any other item, neither a bill
    nor a nomination], "yeas": n, "nays": n}. A calendar printed for another day, or one
    with no roll call after it, is not returned."""
    lines = text.splitlines()
    found = []
    i = 0
    while i < len(lines):
        if not CALENDAR_HEADING.match(lines[i]):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        m = IN_ORDER_FOR.match(lines[j]) if j < len(lines) else None
        if not m or dt.datetime.strptime(m.group(1), "%B %d, %Y").date() != date:
            i = j
            continue
        items, k = [], j + 1
        while k < len(lines):
            line = lines[k]
            if (
                PASSED.search(line)
                or OTHER_HEADING.match(line)
                or IN_ORDER_FOR.match(line)
            ):
                break
            item = ITEM.match(line)
            if item:
                items.append([item.group(1).strip()])
            elif items:
                items[-1].append(line.strip())
            k += 1
        if k == len(lines) or not PASSED.search(lines[k]):
            i = k
            continue
        tally = {}
        n = k + 1
        while n < len(lines) and len(tally) < 2:
            t = TALLY.match(lines[n])
            if t:
                tally[t.group(1)] = int(t.group(2))
            elif CALENDAR_HEADING.match(lines[n]) or IN_ORDER_FOR.match(lines[n]):
                break
            n += 1
        if len(tally) == 2:
            bills, skipped, unread = [], [], []
            for item in items:
                b = ITEM_BILL.match(item[0])
                removed = any(REMOVED.search(x) for x in item)
                if b and not removed:
                    bills.append((b["year"], b["chamber"], b["bill"]))
                elif b or removed or NOMINATION.match(item[0]):
                    skipped.append(item[0])
                else:
                    unread.append(item[0])
            found.append(
                {
                    "bills": bills,
                    "skipped": skipped,
                    "unread": unread,
                    "yeas": tally["YEAS"],
                    "nays": tally["NAYS"],
                }
            )
        i = n
    return found


def match_consent_votes(roll_calls, calendars):
    """Pairs each of the day's consent roll calls (in report order, each with "yeas" and
    "nays") with the day's journal consent calendar in the same place. Nothing is paired
    unless the day has as many voted calendars as consent roll calls. With more than one,
    every pair's yeas and nays must also agree, since they are what shows the order is the
    same. A day's only roll call and only calendar are the same vote even when the journal
    counts one member differently from the vote report (2/11/2025 and 6/10/2025 list 35
    yeas against the report's 36): a consent roll call is never tied to a list it cannot be
    shown to belong to."""
    if not roll_calls or len(roll_calls) != len(calendars):
        return []
    pairs = list(zip(roll_calls, calendars))
    if len(pairs) > 1 and any(
        (r["yeas"], r["nays"]) != (c["yeas"], c["nays"]) for r, c in pairs
    ):
        return []
    return pairs
