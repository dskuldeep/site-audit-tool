"""
Low-level HTTP fetcher. Handles single-URL retrieval with redirect chain tracking.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlparse

import requests

from models import PageData


_MAX_REDIRECTS = 10


def fetch_page(
    url: str,
    session: requests.Session,
    timeout: int = 15,
    user_agent: str = "SiteAuditBot/1.0",
    depth: int = 0,
    head_only: bool = False,
) -> PageData:
    """
    Fetch a URL and return a PageData with HTTP metadata populated.
    HTML content is stored but NOT parsed here (parser.py does that).
    """
    page = PageData(url=url, final_url=url, depth=depth)
    method = "HEAD" if head_only else "GET"

    try:
        t0 = time.perf_counter()
        resp = _follow_redirects(url, session, timeout, user_agent, page)
        page.response_time_ms = (time.perf_counter() - t0) * 1000

        if resp is None:
            return page  # error already stored in page.crawl_error

        page.status_code = resp.status_code
        page.final_url = resp.url
        page.response_headers = dict(resp.headers)

        content_type = resp.headers.get("content-type", "").lower()
        page.content_type = content_type

        # X-Robots-Tag header
        x_robots = resp.headers.get("x-robots-tag", "")
        if x_robots:
            page.x_robots_tag = x_robots
            if "noindex" in x_robots.lower():
                page.is_indexable = False

        # Only download body for HTML responses
        if "text/html" in content_type:
            page.is_html = True
            page.html = resp.text
            page.page_size_bytes = len(resp.content)
        elif not head_only:
            page.is_html = False
            page.page_size_bytes = int(resp.headers.get("content-length", 0) or 0)

    except requests.exceptions.SSLError as exc:
        page.crawl_error = f"SSL Error: {exc}"
        page.status_code = 0
    except requests.exceptions.ConnectionError as exc:
        page.crawl_error = f"Connection Error: {exc}"
        page.status_code = 0
    except requests.exceptions.Timeout:
        page.crawl_error = "Request timed out"
        page.status_code = 0
    except requests.exceptions.TooManyRedirects:
        page.crawl_error = "Too many redirects"
        page.status_code = 0
    except Exception as exc:
        page.crawl_error = f"Unexpected error: {exc}"
        page.status_code = 0

    return page


def _follow_redirects(
    url: str,
    session: requests.Session,
    timeout: int,
    user_agent: str,
    page: PageData,
) -> Optional[requests.Response]:
    """
    Follow redirects manually to capture the full redirect chain.
    Returns the final response, or None on hard error.
    """
    headers = {"User-Agent": user_agent}
    current_url = url
    seen_urls: set[str] = set()

    for _ in range(_MAX_REDIRECTS):
        try:
            resp = session.get(
                current_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=False,
            )
        except Exception as exc:
            page.crawl_error = str(exc)
            page.status_code = 0
            return None

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if not location:
                break

            # Resolve relative redirect URLs
            from urllib.parse import urljoin
            next_url = urljoin(current_url, location)

            # Store in redirect chain
            page.redirect_chain.append(current_url)

            # Detect redirect loop
            if next_url in seen_urls or next_url == current_url:
                page.crawl_error = "Redirect loop detected"
                page.status_code = resp.status_code
                return resp

            seen_urls.add(current_url)
            current_url = next_url
        else:
            return resp

    return None


def check_url_status(
    url: str,
    session: requests.Session,
    timeout: int = 10,
    user_agent: str = "SiteAuditBot/1.0",
) -> tuple[int, list[str]]:
    """
    Lightweight HEAD check for external links.
    Returns (status_code, redirect_chain).
    Falls back to GET if HEAD is disallowed.
    """
    headers = {"User-Agent": user_agent}
    redirect_chain: list[str] = []
    current_url = url

    for _ in range(_MAX_REDIRECTS):
        try:
            resp = session.head(
                current_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
            )

            if resp.status_code == 405:
                # HEAD not allowed — retry with GET
                resp = session.get(
                    current_url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=False,
                    stream=True,
                )
                resp.close()

            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    return resp.status_code, redirect_chain
                from urllib.parse import urljoin
                next_url = urljoin(current_url, location)
                redirect_chain.append(current_url)
                current_url = next_url
            else:
                return resp.status_code, redirect_chain

        except requests.exceptions.SSLError:
            return 0, redirect_chain
        except requests.exceptions.ConnectionError:
            return 0, redirect_chain
        except requests.exceptions.Timeout:
            return 0, redirect_chain
        except Exception:
            return 0, redirect_chain

    return 0, redirect_chain  # too many redirects
