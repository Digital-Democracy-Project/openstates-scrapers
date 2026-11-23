"""Plain `requests` calls with certificates checked by core's rule (OPEN-803).

openstates-core checks every request a scraper makes through `self.get()` (OPEN-800,
`openstates/utils/tls.py`): the only way to skip the check is a named, per-host entry in
`TLS_VERIFY_EXCEPTIONS`. Code that calls `requests` directly (session lists, a few one-off
fetches) used to pass `verify=False` and skip the check entirely. Use these instead:

    from utils import checked_requests
    checked_requests.get(url, headers=...)   # like requests.get
    checked_requests.Session()               # like requests.Session()

They behave like plain `requests` (no throttle, no retries, no raise on 4xx/5xx, requests'
own User-Agent unless the caller sends one); the one difference is core's certificate check
on every request and redirect hop. Exceptions are still `requests.exceptions.*`.

spatula pages: pass `scraper=VerifyingScraper()` (core's) to `do_scrape()` instead of letting
spatula make its own unchecked-by-core `scrapelib.Scraper()`.
"""
import requests
from openstates.utils.tls import VerifyingScraper


class Session(VerifyingScraper):
    """core's VerifyingScraper set up to act like a bare `requests.Session()`."""

    def __init__(self) -> None:
        super().__init__(raise_errors=False, requests_per_minute=0, retry_attempts=0)
        self.user_agent = requests.utils.default_user_agent()


def get(url, **kwargs):
    with Session() as session:
        return session.get(url, **kwargs)


def post(url, **kwargs):
    with Session() as session:
        return session.post(url, **kwargs)
