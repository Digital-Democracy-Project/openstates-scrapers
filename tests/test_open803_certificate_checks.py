"""OPEN-803: every request the scrapers make outside core checks certificates by core's rule.

OPEN-800 (openstates-core `openstates/utils/tls.py`) made core check certificates on every
request through `self.get()`; the only way to skip a check is a named host in
`TLS_VERIFY_EXCEPTIONS`. These tests hold the scrapers fork to the same rule:

* no `verify=False` (as a keyword, an attribute or a requests kwarg) and no `VERIFY_CERTS`
  read anywhere in `scrapers/` (tests and fixtures excepted);
* `utils.checked_requests`, `url_xpath` and `lxmlize` send `verify=True` to the wire even
  when a caller asks for `verify=False`, and `False` only for a named exception host;
* spatula pages that used to run on their own unverified `scrapelib.Scraper()` get core's
  `VerifyingScraper`.

No network: the HTTP adapter is replaced, so nothing leaves the machine.
"""
import ast
import os
import sys
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scrapers"))

from openstates.utils import tls  # noqa: E402
from openstates.utils.tls import VerifyingScraper  # noqa: E402
from utils import checked_requests, url_xpath, LXMLMixin  # noqa: E402

SCRAPERS = Path(__file__).resolve().parent.parent / "scrapers"


# -- the code scan ------------------------------------------------------------------------


def _is_false(node):
    return isinstance(node, ast.Constant) and node.value is False


def _target_is_verify(target):
    if isinstance(target, ast.Name):
        return target.id == "verify"
    if isinstance(target, ast.Attribute):
        return target.attr == "verify"
    if isinstance(target, ast.Subscript):
        key = target.slice
        return isinstance(key, ast.Constant) and key.value == "verify"
    return False


def certificate_bypasses(source, filename="<string>"):
    """(line, what) for every way `source` turns a certificate check off."""
    found = []
    for node in ast.walk(ast.parse(source, filename)):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "verify"
            and _is_false(node.value)
        ):
            found.append((node.value.lineno, "verify=False"))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_false(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_target_is_verify(t) for t in targets):
                found.append((node.lineno, "verify = False"))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "verify"
                    and _is_false(value)
                ):
                    found.append((node.lineno, '{"verify": False}'))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "VERIFY_CERTS" in node.value:
                found.append((node.lineno, "VERIFY_CERTS"))
        elif isinstance(node, ast.Name) and node.id == "VERIFY_CERTS":
            found.append((node.lineno, "VERIFY_CERTS"))
    return found


def scraper_sources():
    for path in sorted(SCRAPERS.rglob("*.py")):
        parts = path.relative_to(SCRAPERS).parts
        if "tests" in parts or "fixtures" in parts:
            continue
        yield path


def test_no_certificate_bypass_left_in_scrapers():
    offenders = []
    for path in scraper_sources():
        for line, what in certificate_bypasses(path.read_text(), str(path)):
            offenders.append(f"{path.relative_to(SCRAPERS)}:{line}: {what}")
    assert offenders == []


@pytest.mark.parametrize(
    "snippet",
    [
        "self.get(url, verify=False)",
        "requests.get(url, headers=h, verify=False)",
        "URL(url, verify=False)",
        "class S:\n    verify = False",
        "self.verify = False",
        "s = requests.Session()\ns.verify = False",
        'kwargs["verify"] = False',
        'requests.get(url, **{"verify": False})',
        'os.getenv("VERIFY_CERTS", "True")',
        'os.environ["VERIFY_CERTS"]',
    ],
)
def test_the_scan_catches_each_form_of_bypass(snippet):
    assert certificate_bypasses(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "self.get(url)",
        "self.get(url, verify=True)",
        "# verify=False was here once",
        "requests_kwargs.update(verify=True)",
        "self.verify = self.cert_path",
    ],
)
def test_the_scan_leaves_checked_calls_alone(snippet):
    assert certificate_bypasses(snippet) == []


# -- the request paths that used to skip the check now go through core ----------------------

# (file, function, how many checked_requests calls it must make). These are the raw `requests`
# calls that passed verify=False before OPEN-803. Swapping one back to plain `requests` would
# still pass the scan above (requests verifies by default) but would skip core's per-host
# exception list, so each one is pinned here.
CONVERTED = [
    ("ca/download.py", "get_contents", 1),
    ("dc/__init__.py", "get_session_list", 1),
    ("de/__init__.py", "get_session_list", 1),
    ("hi/__init__.py", "get_session_list", 1),
    ("il/__init__.py", "get_session_list", 1),
    ("in/__init__.py", "get_session_list", 1),
    ("in/apiclient.py", "get_session_no", 1),
    ("in/apiclient.py", "get_document_url", 1),
    ("in/apiclient.py", "identify_redirect_url", 1),
    ("ma/__init__.py", "get_session_list", 1),
    ("ma/bills.py", "get_as_ajax", 1),
    ("mi/__init__.py", "get_session_list", 1),
    ("nj/__init__.py", "get_session_list", 1),
    ("ok/bills.py", "scrape_chamber", 1),
    ("pr/__init__.py", "get_session_list", 1),
    ("usa/bills.py", "scrape_votes", 1),
    ("va/__init__.py", "get_session_list", 1),
    ("vi/__init__.py", "get_session_list", 1),
    ("utils/lxmlize.py", "url_xpath", 1),
]


@pytest.mark.parametrize("relpath,function,expected", CONVERTED)
def test_formerly_unchecked_requests_go_through_core(relpath, function, expected):
    tree = ast.parse((SCRAPERS / relpath).read_text())
    bodies = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
    ]
    assert len(bodies) == 1, (relpath, function)
    checked = [
        node
        for node in ast.walk(bodies[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "checked_requests"
    ]
    assert len(checked) == expected, (relpath, function)


# -- what actually reaches the wire --------------------------------------------------------


class _Wire:
    """Stands in for the network: records the `verify` each request was sent with."""

    def __init__(self, body=b"<html><body><a>2026</a></body></html>"):
        self.sent = []
        self.body = body

    def send(self, adapter, request, **kwargs):
        self.sent.append((request.url, kwargs.get("verify")))
        response = requests.Response()
        response.status_code = 200
        response._content = self.body
        response.url = request.url
        response.request = request
        response.encoding = "utf-8"
        return response


@pytest.fixture
def wire(monkeypatch):
    w = _Wire()
    monkeypatch.setattr(
        HTTPAdapter,
        "send",
        lambda adapter, request, **kw: w.send(adapter, request, **kw),
    )
    return w


@pytest.fixture
def exception_for(monkeypatch):
    def add(host):
        monkeypatch.setitem(
            tls.TLS_VERIFY_EXCEPTIONS,
            host,
            tls.TlsException("test", "2026-11-23", "OPEN-803"),
        )

    return add


def test_checked_requests_get_verifies_even_when_asked_not_to(wire):
    checked_requests.get("https://example.gov/a")
    checked_requests.get("https://example.gov/b", verify=False)
    checked_requests.post("https://example.gov/c", data={"x": 1}, verify=False)
    assert [v for _, v in wire.sent] == [True, True, True]


def test_checked_requests_session_verifies_even_with_session_verify_off(wire):
    session = checked_requests.Session()
    session.verify = False
    session.get("https://example.gov/a")
    assert wire.sent == [("https://example.gov/a", True)]


def test_checked_requests_skips_only_a_named_exception_host(wire, exception_for):
    exception_for("excepted.example.gov")
    checked_requests.get("https://excepted.example.gov/a")
    checked_requests.get("https://other.example.gov/a")
    assert [v for _, v in wire.sent] == [False, True]


def test_checked_requests_acts_like_plain_requests(wire):
    session = checked_requests.Session()
    # no throttle, no retries, no raise on an error status, requests' own User-Agent
    assert session.requests_per_minute == 0
    assert session.retry_attempts == 0
    assert session.raise_errors is False
    assert session.timeout is None  # no default timeout, like requests
    assert session.headers["User-Agent"] == requests.utils.default_user_agent()
    assert isinstance(session, VerifyingScraper)


def test_url_xpath_verifies(wire):
    assert url_xpath("https://example.gov/sessions", "//a/text()") == ["2026"]
    assert wire.sent == [("https://example.gov/sessions", True)]


def test_url_xpath_no_longer_takes_verify():
    with pytest.raises(TypeError):
        url_xpath("https://example.gov/sessions", "//a/text()", verify=False)


class _LxmlScraper(LXMLMixin):
    def __init__(self, fail_with=None):
        self.calls = []
        self.fail_with = fail_with

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        if self.fail_with:
            raise self.fail_with
        response = requests.Response()
        response._content = b"<html><body><a href='/x'>x</a></body></html>"
        response.encoding = "utf-8"
        return response

    def warning(self, *args):
        pass


def test_lxmlize_never_retries_unverified_after_an_ssl_error():
    scraper = _LxmlScraper(fail_with=requests.exceptions.SSLError("bad certificate"))
    with pytest.raises(requests.exceptions.SSLError):
        scraper.lxmlize("https://example.gov/page")
    assert len(scraper.calls) == 1
    assert "verify" not in scraper.calls[0]


def test_lxmlize_does_not_read_verify_certs(monkeypatch):
    monkeypatch.setenv("VERIFY_CERTS", "False")
    scraper = _LxmlScraper()
    page = scraper.lxmlize("https://example.gov/page")
    assert page.xpath("//a/@href") == ["https://example.gov/x"]
    assert "verify" not in scraper.calls[0]


# -- spatula pages run on core's VerifyingScraper ----------------------------------------


SPATULA_FILES = [
    "fl/bills.py",
    "ma/votes.py",
    "ok/events.py",
    "ms/events.py",
    "vt/events.py",
]


@pytest.mark.parametrize("relpath", SPATULA_FILES)
def test_spatula_pages_that_skipped_checks_now_run_on_core_scraper(relpath):
    tree = ast.parse((SCRAPERS / relpath).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "do_scrape"
    ]
    assert calls, relpath
    for call in calls:
        scraper = [k.value for k in call.keywords if k.arg == "scraper"]
        assert scraper and isinstance(scraper[0], ast.Call), (relpath, call.lineno)
        assert getattr(scraper[0].func, "id", None) == "VerifyingScraper", (
            relpath,
            call.lineno,
        )


def test_a_spatula_url_on_core_scraper_is_checked(wire):
    from spatula import URL

    URL("https://example.gov/journal", verify=False).get_response(
        VerifyingScraper(requests_per_minute=0)
    )
    assert wire.sent == [("https://example.gov/journal", True)]
