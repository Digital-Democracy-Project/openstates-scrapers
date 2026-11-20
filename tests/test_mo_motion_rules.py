"""OPEN-705: Missouri motion rules.

scrapers/mo/votes.py (OPEN-696) labelled every member-level roll call "passage". Now the
mo block of config/motion_classification.yaml decides passage, the scraper labels
amendment roll calls "amendment", and everything else stays unlabelled.

The fixtures (tests/fixtures/mo_open705/) are the legislature's own 2026 files:

* House roll-call PDFs: 014.003 (motion to recommit HB 1667), 014.004 (previous question),
  023.006 (perfection amendment *HA 1 to HB 2178), 033.002 and 033.003 (HB 2014 with
  Senate amendments: the Senate substitute adopted, then truly agreed to and finally
  passed, House journal day 33), 049.019 and 049.020 (HB 3080 passed, then its emergency
  clause defeated 2-131, House journal day 49), 060.002-060.004 (HBs 2637 & 3155: CCR
  adopted, CCS passed, emergency clause adopted), 064.003 (motion to refuse a CCR),
  071.029 (SB 1408, request messages: truly agreed to and finally passed, journal day 71),
  073.001 (HR 1, veto session).
* Senate journals for day 2 (HCR 21 and HCR 22 adopted) and day 22 (SA 2 adopted, SA 3
  failed); days 23, 55 and 68 are OPEN-696's fixtures (tests/fixtures/mo_open696/).
"""
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils import convert_pdf  # noqa: E402
from classify_motion import classify_motion  # noqa: E402
from mo import Missouri  # noqa: E402
from mo.votes import (  # noqa: E402
    EMERGENCY_CLAUSE,
    MOVoteScraper,
    mark_emergency_clauses,
    parse_house_rollcall,
    parse_senate_journal,
    vote_classification,
)

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures", "mo_open705")
OPEN696 = os.path.join(HERE, "fixtures", "mo_open696")


def fixture(name):
    for folder in (FIXTURES, OPEN696):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(name)


def text(name):
    return convert_pdf(fixture(name), type="text").decode("utf-8")


def house(number):
    return parse_house_rollcall(text(f"house_rollcall_{number}.pdf"))


def senate(name):
    return {
        (rc["page"], rc["bill"], rc["motion"][:60]): vote_classification(rc["motion"])
        for rc in parse_senate_journal(text(name))
    }


# ── real motion texts, as the scraper builds them ───────────────────────────


@pytest.mark.parametrize(
    "motion,expected",
    [
        # House third reading, every calendar heading seen
        (
            "HBs FOR THIRD READING - HB 2885 - HOVIS (146) - VESSEL REGISTRATION FEES - 6206H.02P",
            ["passage"],
        ),
        (
            "HBs 3rd READ - INFORMAL - HCS HB 1757 - SHIELDS (011) - TESTING OF GIFTED STUDENTS - 5274H.02P",
            ["passage"],
        ),
        (
            "HBs 3rd READING - CONSENT - HB 1628 - HALEY (058) - HIGHER EDUCATION - 5234H.02P",
            ["passage"],
        ),
        (
            "HABs FOR THIRD READING - HCS HB 2002 - DEATON (159) - APPROPRIATIONS BILL - 2002H.03P",
            ["passage"],
        ),
        (
            "HJRs FOR THIRD READING - HCS HJR 154 - CHAPPELL (137) - MO HEALTHNET - 6310H.02P",
            ["passage"],
        ),
        (
            "HCRs FOR THIRD READING - HCR 23 - PERKINS (040) - ELECTORAL PROCESSES - 5904H.02I",
            ["passage"],
        ),
        (
            "SBs FOR THIRD READING - SS#3 SB 888 - CHRIST (096) - CRIMINAL JUSTICE SYSTEM - 5440S.14P",
            ["passage"],
        ),
        (
            "SBs 3rd READ - INFORMAL - HCS SS#2 SB 1233, A.A. - MCGIRL (118) - ACTIVITIES REQUIRING LICENSURE - 5607H.07C",
            ["passage"],
        ),
        (
            "SJRs FOR THIRD READING - SS SCS SJR 95 - WELLENKAMP (105) - CREATION OF A SOVEREIGN WEALTH FUND FOR THE - STATE",
            ["passage"],
        ),
        (
            "SCRs FOR THIRD READING - SCS SCR 21 - VEIT (059) - SHOW-ME AMERICA 250 - 7532S.02P",
            ["passage"],
        ),
        # a title that says EMERGENCY is not the emergency clause vote
        (
            "HBs 3rd READ - INFORMAL - HB 1 - X (001) - EMERGENCY SUSPENSIONS OR RESTRICTIONS OF - CERTAIN LICENSES",
            ["passage"],
        ),
        # concurrence and conference
        (
            "HBs WITH SENATE AMENDMENTS - SS HCS HB 2641, A.A. - HINMAN (103) - CANNABIS - 6366S.11F",
            ["passage"],
        ),
        (
            "HBs w/SENATE AMENDMENTS - SS SCS HCS HBS 2273, 1946, 1814 & 2551, A.A. - LEWIS (006) - ANTI-TRAFFICKING EFFORTS - 5011S.09F",
            ["passage"],
        ),
        (
            "BILLS IN CONFERENCE - CCR SS SCS HCS HBS 2637 & 3155, A.A. - BLACK (129) - THE CRIMINAL JUSTICE SYSTEM - 6162H09.01F",
            ["passage"],
        ),
        (
            "BILLS IN CONFERENCE - CCS SS SCS HCS HBS 2637 & 3155, E.C. - BLACK (129) - THE CRIMINAL JUSTICE SYSTEM - 6162H.09S",
            ["passage"],
        ),
        # House: not passage
        (
            "BILLS IN CONFERENCE - CCS SS SCS HCS HBS 2637 & 3155, E.C. - BLACK (129) - THE CRIMINAL JUSTICE SYSTEM - 6162H.09S"
            + EMERGENCY_CLAUSE,
            [],
        ),
        (
            "HBs FOR THIRD READING - HB 1847 - HEWKIN (120) - DENTAL PROFESSIONS - 3984H.01P - PREVIOUS QUESTION",
            [],
        ),
        (
            "HBs FOR THIRD READING - HCS HB 2989, A.A. - HARDWICK (121) - GAMING - 6459H.03P - *THAT HCS HB 2989, A.A., BE REFERRED TO THE COMMITTEE ON FISCAL REVIEW",
            [],
        ),
        (
            "HBs FOR THIRD READING - HCS HB 3239 - X (001) - Y - 1H.01P - THAT THE VOTE BY WHICH HCS HB 3239 WAS THIRD READ AND DEFEATED BE RECONSIDERED",
            [],
        ),
        (
            "BILLS IN CONFERENCE - CCR SS SCS HCS HB 2002 - DEATON (159) - APPROPRIATIONS BILL - 2002H06.01F - *THAT THE HOUSE REFUSE TO ADOPT CCR SS SCS HCS HB 2002 AND REQUEST THE SENATE - GRANT FURTHER CONFERENCE",
            [],
        ),
        (
            "HBs FOR PERFECTION - *HCS HB 2989, A.A. - HARDWICK (121) - GAMING - 6459H.03C",
            [],
        ),
        (
            "HJRs FOR PERFECTION - HCS HJR 154 - CHAPPELL (137) - MO HEALTHNET - 6310H.02C - PREVIOUS QUESTION",
            [],
        ),
        (
            "SBs 3rd READ - INFORMAL - HCS SB 953 - HA 1 - DAVIDSON (130) - ENVIRONMENTAL PROGRAMS WITHIN DNR - 4505H04.17H - PREVIOUS QUESTION",
            [],
        ),
        # House amendments
        (
            "HBs PERFECTION - INFORMAL - HCS HB 2178 - *HA 1 - PERKINS (040) - TAXATION OF PROPERTY - 5348H02.08H",
            ["amendment"],
        ),
        (
            "SBs FOR THIRD READING - HCS SS SCS SBs 835 & 1111 - HA 3 - BOSLEY (079) - GARNISHMENTS - 5285H07.08H",
            ["amendment"],
        ),
        (
            "HBs FOR PERFECTION - HCS HB 1 - *HA 1 HA 2 - X (001) - Y - 1H01.01H",
            ["amendment"],
        ),
        # Senate third reading and final passage
        (
            "On motion of Senator Crawford, SB 1020 was read the 3rd time and passed by the following vote:",
            ["passage"],
        ),
        (
            "On motion of Senator Brown (16) SS No. 2 for SCS for SB 1023 was read the 3rd time and passed by the following vote:",
            ["passage"],
        ),
        ("Was read the 3rd time and passed by the following vote:", ["passage"]),
        # Senate concurrence and conference
        (
            "Senator Henderson moved that HCS for SB 1572, as amended, be adopted, which motion prevailed by the following vote:",
            ["passage"],
        ),
        (
            "Senator Coleman moved that HCS for SB 982, be adopted, which motion prevailed by the following vote:",
            ["passage"],
        ),
        (
            "Senator Gregory (15) moved that HA 1 to SS for SCS for SB 905 be adopted, which motion prevailed by the following vote:",
            ["passage"],
        ),
        (
            "Senator Crawford moved that the above conference committee report be adopted, which motion prevailed by the following vote:",
            ["passage"],
        ),
        (
            "Senator Black moved that the conference committee report on SS for SCS for HCS for HB 2003 be adopted, which motion prevailed by the following vote:",
            ["passage"],
        ),
        (
            "On motion of Senator Black, the above conference committee report was adopted by the following vote:",
            ["passage"],
        ),
        # Senate resolutions
        (
            "On motion of Senator Luetkemeyer, HCR 21 was adopted by the following vote:",
            ["passage"],
        ),
        (
            "On motion of Senator Bernskoetter, SCR 21, as amended by SCS, was adopted by the following vote:",
            ["passage"],
        ),
        (
            "On motion of Senator O'Laughlin, SR 640 was adopted by the following vote:",
            ["passage"],
        ),
        # Senate: not passage
        ("The emergency clause was adopted by the following vote:", []),
        (
            "Having voted on the prevailing side, Senator Trent moved that the vote by which SS for SB 1233, as amended, was declared perfected be reconsidered, which motion prevailed by the following vote:",
            [],
        ),
        (
            "SS for SCS for HCS for HJRs 173 and 174 was adopted by the following vote:",
            [],
        ),
        # reconsidering a passage vote names the passage vote (not seen in the Senate in 2026)
        (
            "Senator X moved that the vote by which SB 1 was read the 3rd time and passed"
            " be reconsidered, which motion prevailed by the following vote:",
            [],
        ),
        (
            "Senator X moved for reconsideration of the vote by which SB 1 was read the 3rd"
            " time and passed, which motion prevailed by the following vote:",
            [],
        ),
        # Senate amendments
        ("SA 2 was adopted by the following vote:", ["amendment"]),
        ("SA 2, as amended, was adopted by the following vote:", ["amendment"]),
        ("SA 3 failed of adoption by the following vote:", ["amendment"]),
        # unseen text stays unlabelled, never passage
        ("HBs FOR SOMETHING NEW - HB 1 - X (001) - Y - 1H.01P", []),
        (
            "Senator X moved that the bill be placed on the informal calendar, which motion prevailed by the following vote:",
            [],
        ),
    ],
)
def test_real_motions(motion, expected):
    assert vote_classification(motion) == expected


def test_passage_is_only_from_the_mo_block():
    # the yaml decides passage, never the scraper's own amendment rule
    assert classify_motion("mo", "SA 2 was adopted by the following vote:") == []
    assert classify_motion("mo", "HBs FOR PERFECTION - HCS HB 1 - *HA 1 - X") == []


# ── the real PDFs through the parser ────────────────────────────────────────


@pytest.mark.parametrize(
    "number,expected",
    [
        ("014.003", []),  # motion to recommit
        ("014.004", []),  # previous question
        ("023.006", ["amendment"]),
        # alone; with the final passage after it, the scraper relabels it (OPEN-714)
        ("033.002", ["passage"]),  # Senate substitute adopted (concurrence)
        ("033.003", ["passage"]),  # truly agreed to and finally passed
        ("060.002", ["passage"]),  # CCR adopted
        ("064.003", []),  # motion to refuse the CCR
        ("071.029", ["passage"]),
        ("073.001", ["passage"]),
        ("049.010", ["passage"]),  # OPEN-696's HB 2885 third reading
        ("065.004", ["amendment"]),  # OPEN-696's HA 3 to SB 835
        (
            "065.006",
            ["passage"],
        ),  # OPEN-696's SB 835 truly agreed to and finally passed
    ],
)
def test_house_pdfs(number, expected):
    assert vote_classification(house(number)["motion"]) == expected


def test_senate_journals():
    day2 = senate("RDay020108117-137.pdf")
    assert [label for key, label in day2.items() if key[1] in ("HCR 21", "HCR 22")] == [
        ["passage"],
        ["passage"],
    ]
    day22 = senate("RDay220218398-409.pdf")
    assert {k[0]: v for k, v in day22.items() if k[1] == "SB 1233"} == {
        402: ["amendment"],
        406: ["amendment"],
    }
    day55 = senate("RDay5504231120-1141.pdf")
    # page 1123: passed, then "The emergency clause was adopted"
    assert [v for k, v in day55.items() if k[1] == "HB 2637"] == [["passage"], []]
    day68 = senate("RDay6805151864-1889.pdf")
    by_page = {}
    for (page, bill, _), label in day68.items():
        by_page.setdefault((page, bill), []).append(label)
    assert by_page[(1868, "SB 835")] == [["passage"]]  # CCR adopted
    assert by_page[(1869, "SB 835")] == [["passage"]]  # then passed
    # concurrence in the HCS, then (OPEN-707, a wrapped lead-in) its final passage
    assert by_page[(1870, "SB 1572")] == [["passage"], ["passage"]]
    assert by_page[(1877, "HB 2474")] == [[]]  # reconsider
    assert by_page[(1878, "HB 2474")] == [["passage"]]
    assert by_page[(1879, "HB 2885")] == [["passage"]]


# ── the emergency clause vote, through the House walk ───────────────────────


def make_scraper(tmp_path, files):
    scraper = MOVoteScraper(Missouri(), str(tmp_path))

    def urlretrieve(url, *args, **kwargs):
        copy = str(tmp_path / f"dl{len(os.listdir(tmp_path))}")
        shutil.copy(fixture(files.get(url, "house_rollcall_missing.html")), copy)
        return copy, None

    scraper.urlretrieve = urlretrieve
    return scraper


def test_house_walk_labels_the_emergency_clause_vote(tmp_path):
    base = "https://documents.house.mo.gov/billtracking/bills261/rollcalls/"
    scraper = make_scraper(
        tmp_path,
        {
            # day 60: CCR adopted, CCS passed, emergency clause adopted
            base + "001.001.pdf": "house_rollcall_060.002.pdf",
            base + "001.002.pdf": "house_rollcall_060.003.pdf",
            base + "001.003.pdf": "house_rollcall_060.004.pdf",
            # day 49: HB 3080 passed 104-34, its emergency clause defeated 2-131
            base + "002.001.pdf": "house_rollcall_049.019.pdf",
            base + "002.002.pdf": "house_rollcall_049.020.pdf",
            # day 33: Senate substitute adopted, then passed; no emergency clause
            base + "003.001.pdf": "house_rollcall_033.002.pdf",
            base + "003.002.pdf": "house_rollcall_033.003.pdf",
        },
    )
    votes = list(scraper._scrape_lower_chamber("2026"))
    got = [
        (
            v.dedupe_key,
            v.motion_classification,
            v.motion_text.endswith(EMERGENCY_CLAUSE),
        )
        for v in votes
    ]
    assert got == [
        # OPEN-714: the CCR adoption is followed by the CCS's final passage
        ("mo-2026-H-001.001", [], False),
        ("mo-2026-H-001.002", ["passage"], False),
        ("mo-2026-H-001.003", [], True),
        ("mo-2026-H-002.001", ["passage"], False),
        ("mo-2026-H-002.002", [], True),
        # OPEN-714: the concurrence is followed by the final passage
        ("mo-2026-H-003.001", ["amendment"], False),
        ("mo-2026-H-003.002", ["passage"], False),
    ]
    for v in votes:
        v.validate()
    # the passage vote keeps its own counts; the emergency clause vote its own
    assert [(c["option"], c["value"]) for c in votes[3].counts][:2] == [
        ("yes", 104),
        ("no", 34),
    ]


def test_emergency_clause_is_the_last_of_a_run():
    def rc(motion):
        return {"motion": motion}

    ec = "HBs WITH SENATE AMENDMENTS - SS HB 1, E.C. - X"
    other = "HBs FOR THIRD READING - HB 2, E.C. - Y"
    plain = "HBs FOR THIRD READING - HB 3 - Z"
    marked = mark_emergency_clauses(
        [rc(ec), rc(ec), rc(ec), rc(other), rc(plain), rc(plain)]
    )
    assert [m["motion"].endswith(EMERGENCY_CLAUSE) for m in marked] == [
        False,
        False,
        True,
        False,  # a single roll call: the emergency clause was not roll-called
        False,
        False,  # no ", E.C." in the header
    ]


def test_source_no_longer_hard_codes_passage():
    with open(os.path.join(HERE, "..", "scrapers", "mo", "votes.py")) as f:
        assert 'classification="passage"' not in f.read()
