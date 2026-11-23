"""OPEN-798: legislature.idaho.gov/sessioninfo/ was redesigned on 2026-11-23. The old
<select id="ddlsessions"> is gone and each session is now a "session-card", so
Idaho.get_session_list() returned nothing and every Idaho run stopped at openstates-core's
session check ("no sessions from Idaho.get_session_list()").

The fixtures are the page as served on 2026-11-23 (the new cards) and the Internet Archive's
copy of 2026-11-03 (the old menu). The names read from the new cards must be exactly the names
the old menu printed, so the scraper's _scraped_name and ignored_scraped_sessions still match.
"""
import os
import sys

import lxml.html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

import id as idaho  # noqa: E402
from openstates.cli.update import check_session_list  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "id_open798")
CARDS = '//article[contains(@class, "session-card")]'


def _page(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return lxml.html.fromstring(f.read())


def _new_names():
    return idaho.session_names(_page("sessioninfo_20261123.html").xpath(CARDS))


def _old_menu_names():
    return _page("sessioninfo_wayback_20261103.html").xpath(
        '//select[@id="ddlsessions"]/option/text()'
    )


def test_new_page_gives_the_names_the_old_menu_printed():
    old = _old_menu_names()
    assert len(old) == 34
    # same 34 names; the old menu listed each extraordinary session above its year's regular
    # session and the new page lists it below, which the session check does not look at
    assert sorted(_new_names()) == sorted(old)


def test_names_as_printed():
    names = _new_names()
    assert names[:2] == ["2026 Session", "2025 Session"]
    assert "2022  First Extraordinary Session" in names
    assert "2015  First Extraordinary Session" in names
    assert "1998 Session" in names


def test_session_check_passes_with_no_unknown_sessions(monkeypatch):
    def fake_url_xpath(url, path):
        assert url == "https://legislature.idaho.gov/sessioninfo/"
        return _page("sessioninfo_20261123.html").xpath(path)

    monkeypatch.setattr(idaho, "url_xpath", fake_url_xpath)
    jurisdiction = idaho.Idaho()
    # openstates-core's own check, the one that raised the CommandError; it raises on an empty
    # list or on any name not in legislative_sessions / ignored_scraped_sessions
    assert check_session_list(jurisdiction) == {"2026"}


def test_a_session_kind_the_old_menu_never_had_is_left_as_printed():
    card = lxml.html.fromstring(
        '<article class="session-card"><div class="session-header"><h2>2027</h2></div>'
        '<div class="session-details"><p>Sixty-Ninth Idaho Legislature</p>'
        "<p>Organizational Session</p></div></article>"
    )
    assert idaho.session_names([card]) == ["2027 Organizational Session"]
