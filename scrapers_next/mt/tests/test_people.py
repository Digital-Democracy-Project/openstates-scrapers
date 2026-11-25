import re
import unittest
from pathlib import Path
from urllib.parse import urljoin

from lxml import html

from ..people import Legislators

FIXTURE = Path(__file__).parent / "fixtures" / "roster_rows.html"
ROSTER_URL = "https://leg.mt.gov/legislator-information/"
NOTE = re.compile(r"\b(resigned|replaced)\b", re.I)


class TestRosterNames(unittest.TestCase):
    """Rows copied from the live roster page. A member who left or was replaced has a
    note after the name link in the same cell, and every cell ends in a script."""

    def setUp(self):
        tree = html.fromstring(FIXTURE.read_text())
        tree.make_links_absolute(ROSTER_URL)
        self.rows = tree.xpath("//tr")

    def person(self, row):
        return Legislators.process_item(Legislators.__new__(Legislators), row)

    def test_fixture_still_has_the_notes(self):
        # without them the other tests would prove nothing
        noted = [r for r in self.rows if NOTE.search(r.getchildren()[1].text_content())]
        self.assertEqual(len(noted), 4)

    def test_name_is_the_link_text_only(self):
        for row in self.rows:
            link = row.getchildren()[1].xpath("a")[0]
            expected = " ".join(link.text_content().split()).title()
            self.assertEqual(self.person(row).name, expected)

    def test_no_note_or_script_text_in_a_name(self):
        for row in self.rows:
            name = self.person(row).name
            self.assertIsNone(re.search(r"[\d;=]", name), name)
            self.assertIsNone(NOTE.search(name), name)

    def test_link_and_source_url_kept(self):
        for row in self.rows:
            href = urljoin(ROSTER_URL, row.getchildren()[1].xpath("a/@href")[0])
            person = self.person(row)
            self.assertEqual(str(person.links[0].url), href)
            self.assertEqual(str(person.sources[0].url), href)
