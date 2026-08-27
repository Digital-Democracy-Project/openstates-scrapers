"""Tests for OPEN-176 and OPEN-177: Massachusetts roll calls that imported wrong.

Both tickets are the same defect seen from two sides, and the shared cause is that
an unreadable roll call was indistinguishable from a read one.

OPEN-176 -- 152 MA 194th vote events imported with a real tally and zero voters
(118 Senate, 34 House). The Senate half was not, as first filed, a malformed-PDF
problem: 115 of the 118 had been pointed at `/Bills/GetAmendmentContent/.../Preview`,
an 818-byte HTML modal that was never a PDF. The scraper took the first link in the
action cell, and that cell carries several kinds of link.

OPEN-177 -- 6 MA bills cite a Senate roll call and hold no Senate vote at all. Four
are the tally gate rejecting "Yeas 39 to Nay 0" for want of a literal "nays"; two
(H 4530 / roll call #70, S 2903 / roll call #128) had their PDF fetch fail during the
2026-08-12 run, and the old code dropped the entire vote when that happened.

These tests pin the parsing rules and the return-value contract, not a scraped
snapshot -- a snapshot would not have caught any of it, because every one of these
failures produced well-formed output.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from ma.bills import (  # noqa: E402
    MABillScraper,
    _QUORUM_RE,
    parse_senate_tally,
    senate_rollcall_url,
)

SESSION = "194th"


class TestSenateTallyParsing:
    """OPEN-177: every nay-count spelling Massachusetts actually uses."""

    def test_plural_nays_still_parses(self):
        """The 230 of 236 that always worked must keep working."""
        assert parse_senate_tally(
            "Passed to be engrossed -see   Roll Call #70 (Yeas 39 to Nays 0)"
        ) == (39, 0, True)

    def test_singular_nay_parses(self):
        """The bug. S 18, S 19 and S 2917 all read "Nay", and all three created
        no vote event at all."""
        assert parse_senate_tally(
            "Report accepted, as amended -- see   Roll Call #24 (Yeas 39 to Nay 0)"
        ) == (39, 0, True)

    def test_singular_nay_with_nonzero_count(self):
        assert parse_senate_tally(
            "Passed to be engrossed -see   Roll Call #118 (Yeas 37 to Nay 1)"
        ) == (37, 1, True)

    def test_source_typo_writing_nays_as_yeas(self):
        """S 2565. The legislature wrote "Yeas" twice; the second number is still
        the nay count, and the roll-call PDF behind it is readable."""
        assert parse_senate_tally(
            "Passed to be engrossed -- see   Roll Call #65 (Yeas 39 to Yeas 0)"
        ) == (
            39,
            0,
            False,
        )  # False = the nay count was labelled "Yeas"

    def test_older_number_first_form(self):
        """2019 H86's shape, which the original regex was written for."""
        assert parse_senate_tally(
            "Ordered to a third reading -- 30 yeas to 8 nays"
        ) == (30, 8, True)

    def test_action_with_no_tally_returns_none(self):
        assert parse_senate_tally("Referred to the committee on Ways and Means") is None

    def test_empty_and_none_are_safe(self):
        assert parse_senate_tally("") is None
        assert parse_senate_tally(None) is None


class TestSenateRollCallUrl:
    """OPEN-176: the URL comes from the number the action cites."""

    def test_builds_url_from_cited_number(self):
        """All 110 Senate votes that DID import voters follow exactly this rule,
        which is why it is safe to rely on for the 115 that did not."""
        assert (
            senate_rollcall_url("Passed to be engrossed -- see Roll Call #128", SESSION)
            == "http://malegislature.gov/RollCall/194/SenateRollCall128.pdf"
        )

    def test_strips_the_session_ordinal(self):
        """OPEN-169 fixed this same trap on the House side: the site wants 194,
        not 194th, and the ordinal form returns a 404 HTML page that converts to
        junk text rather than raising."""
        assert "/194/" in senate_rollcall_url("Roll Call #1", "194th")
        assert "194th" not in senate_rollcall_url("Roll Call #1", "194th")

    def test_tolerates_spacing_variants(self):
        assert (
            senate_rollcall_url("see   Roll  Call # 65 (Yeas 39 to Yeas 0)", SESSION)
            == "http://malegislature.gov/RollCall/194/SenateRollCall65.pdf"
        )

    def test_reproduces_urls_that_already_work(self):
        """The regression guard. Reconstruction replaces the link for *every*
        Senate roll call, including the 110 that already import voters, so it
        has to reproduce those URLs exactly rather than merely fix the broken
        ones. These pairs are real: the action text on the left, and the URL the
        successful import actually used on the right."""
        cases = [
            (
                "Passed to be engrossed -see   Roll Call #70 (Yeas 39 to Nays 0)",
                "http://malegislature.gov/RollCall/194/SenateRollCall70.pdf",
            ),
            (
                "Passed to be engrossed -- see   Roll Call #128 (Yeas 38 to Nays 0)",
                "http://malegislature.gov/RollCall/194/SenateRollCall128.pdf",
            ),
            # S 2710 -- a space after the "#". This is the one that made a
            # stricter check look like a 109/110 mismatch; the real figure is
            # 110/110 and this is why.
            (
                "Passed to be engrossed -see   Roll Call # 97 (Yeas 37 to Nays 0)",
                "http://malegislature.gov/RollCall/194/SenateRollCall97.pdf",
            ),
        ]
        for action_name, expected in cases:
            assert senate_rollcall_url(action_name, SESSION) == expected

    def test_no_number_yields_no_url(self):
        """Better to record the vote with an explicit gap than to invent a URL.

        No Massachusetts action currently reaches this: all 234 vote-producing
        roll-call actions in the 194th carry a number. It is a degradation path,
        not a live one."""
        assert senate_rollcall_url("Passed to be engrossed", SESSION) is None

    def test_prefers_the_number_the_action_gives_the_senate(self):
        """The latent bug this guards, raised at review of OPEN-176.

        An action can name a roll call in each chamber. The 2019 H86 shape,
        cited in this module's own comments, is the example. Taking the first
        number would build a Senate URL out of the HOUSE roll-call number --
        and that URL resolves, returns a real PDF, and attaches the wrong
        chamber's voters. A wrong source that works is worse than no source.
        """
        url = senate_rollcall_url(
            "Ordered to a third reading -- see Senate   Roll Call #25 "
            "and House Roll Call 56",
            SESSION,
        )
        assert url == "http://malegislature.gov/RollCall/194/SenateRollCall25.pdf"

    def test_house_number_first_does_not_win(self):
        """The case that actually distinguishes the guard from what it replaced.

        In H86's own wording the Senate number happens to come first, so taking
        the first match gets the right answer by luck. Reverse the order and the
        old behaviour builds SenateRollCall56.pdf -- the House's roll call,
        served as the Senate's, with the wrong chamber's voters attached and
        nothing to indicate it. Ordering must not decide this.
        """
        url = senate_rollcall_url(
            "see House Roll Call #56 and Senate Roll Call #25", SESSION
        )
        assert url == "http://malegislature.gov/RollCall/194/SenateRollCall25.pdf"

    def test_house_only_citation_yields_no_senate_url(self):
        """No Senate number named, so there is no Senate URL to build. The
        caller records the vote with voters_unavailable instead of fetching the
        House roll call and calling its voters the Senate's."""
        assert (
            senate_rollcall_url(
                "Passed to be engrossed -- see House Roll Call #56", SESSION
            )
            is None
        )

    def test_two_unqualified_numbers_are_ambiguous(self):
        """Neither number is attributed to a chamber, so neither can be trusted.
        Ambiguity resolves to None rather than to a coin flip."""
        assert (
            senate_rollcall_url("see Roll Call #25 and Roll Call #56", SESSION) is None
        )

    def test_one_number_repeated_is_not_ambiguous(self):
        """The same roll call cited twice is still one roll call."""
        assert (
            senate_rollcall_url(
                "see Roll Call #25 -- corrected, see Roll Call #25", SESSION
            )
            == "http://malegislature.gov/RollCall/194/SenateRollCall25.pdf"
        )

    def test_never_returns_an_amendment_content_link(self):
        """The actual regression. This is the shape 115 of the 118 broken Senate
        events carried, and it can no longer be produced at all: the URL is now
        built, not picked."""
        url = senate_rollcall_url(
            "Amendment #1 rejected -- see Roll Call #14 (Yeas 6 to Nays 30)", SESSION
        )
        assert "GetAmendmentContent" not in url
        assert url.endswith("SenateRollCall14.pdf")


class TestQuorumRollCallsAreNotBillVotes:
    """OPEN-176: the 2 Senate events whose source was a *House* roll-call PDF."""

    def test_quorum_roll_call_is_recognised(self):
        assert _QUORUM_RE.search(
            "Quorum Roll Call - 149 YEAS to 0 NAYS (See YEA and NAY No. 249 )"
        )

    def test_ordinary_roll_call_is_not_treated_as_quorum(self):
        assert not _QUORUM_RE.search(
            "Passed to be engrossed -see   Roll Call #70 (Yeas 39 to Nays 0)"
        )


class _FakeVote:
    """Minimal stand-in for VoteEvent -- records what got attached."""

    def __init__(self):
        self.voters = []

    def yes(self, name):
        self.voters.append(("yes", name))

    def no(self, name):
        self.voters.append(("no", name))

    def vote(self, how, name):
        self.voters.append((how, name))


def _scraper_with_pdf(text):
    """A MABillScraper whose House PDF fetch returns `text`.

    Built with __new__ so the test needs no jurisdiction, datadir or network --
    only the one method under test is exercised.
    """
    scraper = MABillScraper.__new__(MABillScraper)
    scraper.get_house_pdf = lambda vurl: text
    scraper.info = lambda *a, **kw: None
    scraper.warning = lambda *a, **kw: None
    return scraper


class TestUnreadableRollCallReportsFailure:
    """OPEN-176's central criterion: an unreadable roll call must not look like a
    successful one. Every one of these used to return None, which the caller's
    `is False` test read as success."""

    def test_missing_supplement_returns_false(self):
        """The OPEN-169 mechanism: the PDF was fetched but the supplement is not
        in it. This is also the shape of the 34 House events -- supplements #237
        to #270 were not yet in the 2026 year-aggregate journal."""
        scraper = _scraper_with_pdf("No. 12\nSmith   Y\nMASSACHUSETTS")
        vote = _FakeVote()
        assert scraper.scrape_house_vote(vote, "http://example/rc", 999) is False
        assert vote.voters == []

    def test_unfetchable_pdf_returns_false(self):
        scraper = _scraper_with_pdf(None)
        assert scraper.scrape_house_vote(_FakeVote(), "http://example/rc", 1) is False

    def test_supplement_present_but_naming_nobody_returns_false(self):
        """A PDF that read cleanly and named no one is a failure, not a unanimous
        silence."""
        scraper = _scraper_with_pdf("No. 5\n   \nMASSACHUSETTS")
        vote = _FakeVote()
        assert scraper.scrape_house_vote(vote, "http://example/rc", 5) is False
        assert vote.voters == []

    def test_readable_roll_call_returns_true_and_attaches_voters(self):
        scraper = _scraper_with_pdf(
            "No. 7\nSmith   Y   Jones   N   Brown   X\nMASSACHUSETTS"
        )
        vote = _FakeVote()
        assert scraper.scrape_house_vote(vote, "http://example/rc", 7) is True
        assert ("yes", "Smith") in vote.voters
        assert ("no", "Jones") in vote.voters
        assert len(vote.voters) == 3


class TestSenateVoteReturnContract:
    """`scrape_senate_vote()` must return a strict boolean on every path.

    The caller now tests `not read_voters` rather than `is False`, which is only
    safe if there is no third answer. That is the whole point of the change --
    the old code's third answer (a bare `return`) is what let 152 empty votes
    through -- so it is worth a test rather than an assumption. The reviewer of
    this change asked exactly that question.
    """

    def _scraper(self, monkeypatch, pdf_text):
        import ma.bills as ma_bills

        scraper = MABillScraper.__new__(MABillScraper)
        scraper.warning = lambda *a, **kw: None
        scraper.info = lambda *a, **kw: None
        scraper.urlretrieve = lambda url: ("/dev/null", None)
        monkeypatch.setattr(ma_bills, "convert_pdf", lambda path, fmt: pdf_text)
        monkeypatch.setattr(ma_bills.os, "remove", lambda path: None)
        return scraper

    def test_readable_roll_call_returns_true(self, monkeypatch):
        pdf = b"YEAS\nSmith   Jones\nNAYS\nBrown\n"
        scraper = self._scraper(monkeypatch, pdf)
        vote = _FakeVote()
        assert scraper.scrape_senate_vote(vote, "http://example/rc.pdf") is True
        assert ("yes", "Smith") in vote.voters
        assert ("no", "Brown") in vote.voters

    def test_html_error_page_returns_false(self, monkeypatch):
        """The actual 115-event failure: an HTML modal converts to text without
        raising, matches no YEAS/NAYS header, and must not read as success."""
        pdf = b'<div class="modal-header"><button>close</button></div>'
        scraper = self._scraper(monkeypatch, pdf)
        vote = _FakeVote()
        assert scraper.scrape_senate_vote(vote, "http://example/rc.pdf") is False
        assert vote.voters == []

    def test_empty_document_returns_false(self, monkeypatch):
        scraper = self._scraper(monkeypatch, b"")
        assert scraper.scrape_senate_vote(_FakeVote(), "http://example/rc.pdf") is False

    def test_fetch_error_returns_false(self, monkeypatch):
        import ma.bills as ma_bills

        scraper = MABillScraper.__new__(MABillScraper)
        scraper.warning = lambda *a, **kw: None

        def _raise(url):
            raise ma_bills.requests.exceptions.RequestException("boom")

        scraper.urlretrieve = _raise
        assert scraper.scrape_senate_vote(_FakeVote(), "http://example/rc.pdf") is False
