"""S1 Discover + S2 Filter: crawl the MoD OMs & Orders listing pages and keep debarment notices."""
import logging
import time
from urllib.parse import urljoin, urlparse
import os

from bs4 import BeautifulSoup

from .http import get_with_retry

log = logging.getLogger(__name__)


class LayoutChanged(RuntimeError):
    """The listing page no longer has the table we expect."""


def is_match(title: str, keyword: str) -> bool:
    """Plain substring match on normalized title — no regex.

    'debar' is a substring of 'debarment', 'debarred', 'debarring', so one check covers all.
    """
    normalized = " ".join(title.split()).casefold()
    return keyword.casefold() in normalized


def make_notice_id(listed_date: str, pdf_url: str) -> str:
    stem = os.path.splitext(os.path.basename(urlparse(pdf_url).path))[0]
    return f"{listed_date or 'nodate'}_{stem}"


def parse_listing(html: str, page_url: str) -> list[dict]:
    """Return every row of the listing table as a Notice dict."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    notices = []
    for tr in table.select("tbody tr"):
        title_td = tr.select_one("td.views-field-title")
        link = tr.select_one("td.views-field-nothing a[href]")
        if title_td is None:
            continue
        time_tag = tr.select_one("time")
        listed_date = time_tag.get_text(strip=True) if time_tag else ""
        pdf_url = urljoin(page_url, link["href"]) if link else None
        notices.append({
            "title": " ".join(title_td.get_text(" ", strip=True).split()),
            "listed_date": listed_date,
            "pdf_url": pdf_url,
            "source_page": page_url,
        })
    return notices


def discover(session, cfg) -> tuple[list[dict], int]:
    """Crawl all configured sources. Returns (matching notices, total rows seen)."""
    site = cfg["site"]
    keyword = site["keyword"]
    matches, total_rows, seen_urls = [], 0, set()

    for source in site["sources"]:
        base = urljoin(site["base_url"], source)
        for page in range(site["max_pages"]):
            url = f"{base}?page={page}"
            resp = get_with_retry(session, url, timeout=site["timeout"], retries=site["retries"])
            rows = parse_listing(resp.text, url)
            if page == 0 and not rows:
                raise LayoutChanged(f"No listing table rows found on {url}; site layout may have changed")
            if not rows:
                break
            total_rows += len(rows)
            for n in rows:
                if not is_match(n["title"], keyword):
                    continue
                if not n["pdf_url"]:
                    log.warning("Matching notice has no PDF link: %s", n["title"])
                    continue
                if n["pdf_url"] in seen_urls:
                    continue
                seen_urls.add(n["pdf_url"])
                n["notice_id"] = make_notice_id(n["listed_date"], n["pdf_url"])
                matches.append(n)
            log.info("%s: %d rows", url, len(rows))
            time.sleep(site["delay_seconds"])

    matches.sort(key=lambda n: n["listed_date"])
    return matches, total_rows
