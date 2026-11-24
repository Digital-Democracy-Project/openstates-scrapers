"""OPEN-709: who sat in each Hawaii chamber on a given day, from DDP's people fork.

Hawaii's House floor tallies ("Passed Third Reading with none voting aye with reservations;
Representative(s) Garcia voting no (1) and none excused (0).") and the Senate's resolution
adoption name only the members who did not vote a plain aye, and print no aye count. Their ayes
are the members seated in that chamber that day, minus those listed no or excused (those listed
"aye with reservations" are ayes, already named). That rule matches the House journal's aye
counts (see the ticket).

Seated members come from the role start and end dates (both days included) in the people fork's
data/hi/legislature and data/hi/retired YAML, fetched from GitHub's main at scrape start (Ramon,
2026-11-20: people changes nightly, so it is not bundled into the scraper image). When the files
cannot be read, or a listed name does not match exactly one seated member, the caller keeps no
roll call for that tally: it never guesses.

OPEN-825: the Senate floor tally prints an aye count but names only the exceptions ("Ayes, 25;
Aye(s) with reservations: none .  Noes, 0 (none). Excused, 0 (none)."). Its plain ayes come from
the same rule, kept only when they and the ayes with reservations come to the printed count;
otherwise the roll call keeps its counts and printed names (it was kept before this rule).
"""
import datetime as dt
import glob
import logging
import os
import re

import yaml

logger = logging.getLogger(__name__)

PEOPLE_REPO = "Digital-Democracy-Project/people"
LIST_URL = (
    "https://api.github.com/repos/"
    + PEOPLE_REPO
    + "/contents/data/hi/{folder}?ref=main"
)
FOLDERS = ("legislature", "retired")
# A local people checkout's data/ folder (the Mac dev checkout, tests): read data/hi from it
# instead of GitHub.
PEOPLE_DIR_ENV = "DDP_PEOPLE_DATA"


def _date(value):
    if value in (None, ""):
        return None
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


class Members:
    def __init__(self, people):
        # (person, chamber, first day, last day); None is an open end
        self.roles = []
        for person in people:
            for role in person.get("roles", []):
                if role.get("type") in ("upper", "lower"):
                    self.roles.append(
                        (
                            person,
                            role["type"],
                            _date(role.get("start_date")),
                            _date(role.get("end_date")),
                        )
                    )

    def seated(self, chamber, day):
        """The members seated in the chamber on that day, or None when the data does not give one
        clear list: a role that could cover the day has no start date (older records), or one
        person holds two roles in the chamber that day."""
        day = _date(day)
        seated = []
        for person, kind, start, end in self.roles:
            if kind != chamber or (end is not None and end < day):
                continue
            if start is None:
                return None
            if start <= day:
                seated.append(person)
        if len({p["id"] for p in seated}) != len(seated):
            return None
        return seated

    @staticmethod
    def _matches(person, name):
        """A name as the status page prints it: a family name ("Reyes Oda"), or a family name and
        an initial ("Lee, M") where two members share it."""
        family, _, initial = (part.strip() for part in name.partition(","))
        names = {person.get("family_name"), person.get("name")}
        names.update(o.get("name") for o in person.get("other_names", []))
        if family not in names:
            return False
        initial = initial.rstrip(".")
        return not initial or person.get("given_name", person["name"]).startswith(
            initial
        )

    def find(self, seated, name):
        """The one seated member a listed name means, or None (none or several)."""
        found = [p for p in seated if self._matches(p, name)]
        return found[0] if len(found) == 1 else None


def _load_yaml(texts):
    return Members([yaml.safe_load(text) for text in texts])


def load_members(scraper):
    """Hawaii's members from DDP_PEOPLE_DATA if set, else from the people fork's main on GitHub.
    Returns None (with a warning) when they cannot be read."""
    local = os.environ.get(PEOPLE_DIR_ENV)
    try:
        if local:
            files = []
            for folder in FOLDERS:
                files += sorted(glob.glob(os.path.join(local, "hi", folder, "*.yml")))
            if not files:
                raise OSError(f"no Hawaii people files under {local}")
            members = _load_yaml(open(f, encoding="utf-8").read() for f in files)
            source = local
        else:
            texts = []
            for folder in FOLDERS:
                listing = scraper.get(LIST_URL.format(folder=folder)).json()
                for entry in listing:
                    if entry["type"] == "file" and re.search(
                        r"\.ya?ml$", entry["name"]
                    ):
                        texts.append(scraper.get(entry["download_url"]).text)
            if not texts:
                raise ValueError("the people fork listed no Hawaii files")
            members = _load_yaml(texts)
            source = PEOPLE_REPO + " main"
    except Exception as e:  # any failure means no roster: the caller skips, never guesses
        logger.warning(
            "OPEN-709: Hawaii people data not read (%s); House floor tallies and Senate "
            "resolution adoptions are skipped this run, Senate floor tallies keep counts only "
            "(OPEN-825)",
            e,
        )
        return None
    logger.info(
        "OPEN-709: %d Hawaii legislator roles read from %s", len(members.roles), source
    )
    return members
