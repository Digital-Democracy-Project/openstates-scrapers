"""OPEN-863: a "motion to adopt" right after an amendment or substitute is offered is an amendment vote.

ALISON leaves amdSub empty on some of these adoptions. The billModal replies of HB 605, SB 146 and
HB 201 and HB 605's Senate roll calls are ALISON's own, saved 2026-11-24 (SB 146's on 2026-11-10).
No test makes a live call.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from test_al_votes import by_roll_call, load, make_bill, make_scraper  # noqa: E402


def rows_of(bill_id, roll_calls=None):
    # oldest first, as scrape_rest hands them to scrape_votes
    rows = json.loads(load(f"modal_{bill_id}.json"))["data"]["histories"]["data"][::-1]
    if roll_calls is not None:
        rows = [r for r in rows if r["rollCallNbr"] in roll_calls]
    return rows


def classified(bill_id, rows, roll_call):
    votes = by_roll_call(make_scraper().scrape_votes(make_bill(bill_id), rows))
    return votes[str(roll_call)].motion_classification


def test_hb605_senate_amendment_adoption_is_not_passage():
    # "Chesteen 1st Amendment Offered", "Carried Over to Call of Chair", then 1316 with amdSub empty
    rows = rows_of("HB605")
    adopt = [r for r in rows if r["rollCallNbr"] == 1316][0]
    assert adopt["amdSub"] is None
    senate = [r for r in rows if r["rollCallNbr"] in (1316, 1317)]
    # keep the Offered row before the vote rows; the other rolls of the bill are not saved
    kept = [
        r
        for r in rows
        if r in senate or (r["body"] == "Senate" and "Offered" in r["matter"])
    ]
    assert classified("HB605", kept, 1316) == ["amendment"]
    assert classified("HB605", kept, 1317) == ["passage"]


def test_sb146_senate_substitute_adoption_is_not_passage():
    # "1st Substitute Offered", then "Albritton motion to adopt- Adopted Roll Call 813", amdSub empty
    rows = rows_of("SB146")
    assert [r for r in rows if r["rollCallNbr"] == 813][0]["amdSub"] is None
    senate = [
        r for r in rows if r["body"] == "Senate" and r["calendarDate"] == "2026-03-11"
    ]
    kept = [
        r for r in senate if r["rollCallNbr"] in (813, 814) or "Offered" in r["matter"]
    ]
    assert classified("SB146", kept, 813) == ["amendment"]
    assert classified("SB146", kept, 814) == ["passage"]


def test_hb201_adoption_with_no_offer_stays_passage():
    # a local bill: the Senate's only vote, "Motion to Adopt - Adopted Roll Call 101", no paper offered
    rows = rows_of("HB201")
    assert not any("Offered" in r["matter"] for r in rows)
    kept = [r for r in rows if r["rollCallNbr"] == 101]
    assert classified("HB201", kept, 101) == ["passage"]


def test_an_offer_does_not_carry_to_another_day_or_chamber():
    rows = rows_of("HB605")
    adopt = dict([r for r in rows if r["rollCallNbr"] == 1316][0])
    offer = dict(
        [r for r in rows if "Chesteen 1st Amendment Offered" in r["matter"]][0]
    )
    for change in ({"calendarDate": "2026-04-10"}, {"body": "House"}):
        votes = list(
            make_scraper().scrape_votes(
                make_bill("HB605"), [dict(offer, **change), adopt]
            )
        )
        assert votes[0].motion_classification == ["passage"]


def test_one_offer_covers_one_roll_call():
    # after the adoption's roll call the offer is used up; a later "motion to adopt" is not an amendment
    rows = rows_of("HB605")
    offer = [r for r in rows if "Chesteen 1st Amendment Offered" in r["matter"]][0]
    adopt = [r for r in rows if r["rollCallNbr"] == 1316][0]
    again = dict(
        adopt, rollCallNbr=1317, matter="Motion to Adopt - Adopted Roll Call 1317"
    )
    votes = list(make_scraper().scrape_votes(make_bill("HB605"), [offer, adopt, again]))
    assert [v.motion_classification for v in votes] == [["amendment"], ["passage"]]


def test_an_offer_stays_pending_across_another_chambers_rows_and_roll_calls():
    rows = rows_of("HB605")
    offer = [r for r in rows if "Chesteen 1st Amendment Offered" in r["matter"]][0]
    adopt = [r for r in rows if r["rollCallNbr"] == 1316][0]
    # a House offer and a House roll call land between the Senate's offer and its adoption
    house_offer = dict(offer, body="House", matter="Kiel 1st Amendment Offered")
    house_roll = dict(
        adopt,
        body="House",
        rollCallNbr=535,
        matter="Motion to Adopt - Adopted Roll Call 535",
        amdSub="X",
    )
    votes = list(
        make_scraper().scrape_votes(
            make_bill("HB605"), [offer, house_offer, house_roll, adopt]
        )
    )
    assert [(v.dedupe_key.split("#")[2], v.motion_classification) for v in votes] == [
        ("535", ["amendment"]),
        ("1316", ["amendment"]),
    ]
