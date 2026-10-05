"""Shared HTTP session: browser User-Agent, certifi CA bundle, retries with backoff."""
import logging
import time

import certifi
import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    s.verify = certifi.where()
    return s


def get_with_retry(session, url, *, timeout, retries, stream=False):
    """GET a URL, retrying on network errors and 5xx with exponential backoff."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, stream=stream)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500:
                raise  # client errors won't fix themselves
            wait = 2 ** attempt
            log.warning("GET %s failed (%s), attempt %d/%d, retrying in %ds",
                        url, e, attempt, retries, wait)
            time.sleep(wait)
    raise last_err
