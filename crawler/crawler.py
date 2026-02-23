"""
Main crawl orchestrator.
Uses ThreadPoolExecutor to concurrently fetch internal pages, then checks
external links with HEAD requests.
Yields ProgressUpdate dicts so the Streamlit UI can display live progress.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Generator, Optional
from urllib.parse import urlparse, urljoin, urlunparse

import requests
import tldextract

from config import DEFAULT_MAX_PAGES, DEFAULT_MAX_WORKERS, DEFAULT_REQUEST_TIMEOUT
from crawler.fetcher import check_url_status, fetch_page
from crawler.parser import parse_page
from crawler.robots import fetch_and_parse_robots, is_url_allowed
from crawler.sitemap import fetch_sitemap, guess_sitemap_url
from models import AuditConfig, AuditResult, PageData, RobotsData, SitemapData


def crawl(
    config: AuditConfig,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> AuditResult:
    """
    Crawl the site described by `config`.
    Call `progress_callback` with status dicts as crawling progresses.
    Returns a fully-populated AuditResult (issues are filled later by analyzers).
    """
    result = AuditResult(config=config, started_at=datetime.now())

    session = _make_session(config.user_agent)

    _emit(progress_callback, "Fetching robots.txt…", 0)
    result.robots_data = fetch_and_parse_robots(config.start_url, session, config.request_timeout)

    _emit(progress_callback, "Fetching sitemap…", 1)
    result.sitemap_data = _get_sitemap(config, session)

    # Seed URLs: sitemap URLs + start URL
    seed_urls: list[str] = [_normalize_url(config.start_url)]
    if result.sitemap_data and result.sitemap_data.urls:
        for u in result.sitemap_data.urls[:10000]:
            n = _normalize_url(u)
            if n and n not in seed_urls:
                seed_urls.append(n)

    _emit(progress_callback, f"Starting crawl — {len(seed_urls)} seed URLs…", 2)

    pages, external_links_to_check = _crawl_internal(
        seed_urls=seed_urls,
        config=config,
        session=session,
        robots_data=result.robots_data,
        progress_callback=progress_callback,
    )
    result.pages = pages

    # Check external links
    if config.check_external_links and external_links_to_check:
        _emit(progress_callback, f"Checking {len(external_links_to_check)} external links…", 95)
        _check_external_links(external_links_to_check, pages, session, config)

    result.finished_at = datetime.now()
    result.crawl_stats = _build_stats(result)

    _emit(progress_callback, "Crawl complete.", 100)
    return result


# ── Internal crawl ─────────────────────────────────────────────────────────────

def _crawl_internal(
    seed_urls: list[str],
    config: AuditConfig,
    session: requests.Session,
    robots_data: RobotsData,
    progress_callback: Optional[Callable],
) -> tuple[dict[str, PageData], set[str]]:
    """
    BFS crawl of internal pages.
    Returns (pages_dict, set_of_external_urls_to_check).
    """
    visited: set[str] = set()
    todo: deque[tuple[str, int]] = deque()  # (url, depth)
    pages: dict[str, PageData] = {}
    external_urls: set[str] = set()
    lock = threading.Lock()
    done_count = 0

    # Seed
    for url in seed_urls:
        norm = _normalize_url(url)
        if norm:
            todo.append((norm, 0))
            visited.add(norm)

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        pending_futures: dict = {}

        while True:
            # Submit new work up to max_workers slots
            while todo and len(pending_futures) < config.max_workers * 2:
                if len(pages) + len(pending_futures) >= config.max_pages:
                    break
                url, depth = todo.popleft()
                future = executor.submit(
                    _fetch_and_parse,
                    url, depth, config, session, robots_data,
                )
                pending_futures[future] = url

            if not pending_futures:
                break

            # Collect completed
            completed = [f for f in list(pending_futures) if f.done()]
            for future in completed:
                url = pending_futures.pop(future)
                try:
                    page = future.result()
                except Exception as exc:
                    page = PageData(url=url, crawl_error=str(exc))

                with lock:
                    pages[page.url] = page
                    done_count += 1

                # Harvest new internal links
                for link in page.internal_links:
                    norm = _normalize_url(link.url)
                    if not norm:
                        continue
                    with lock:
                        if norm not in visited and len(pages) + len(pending_futures) < config.max_pages:
                            visited.add(norm)
                            todo.append((norm, page.depth + 1))

                # Collect external links for later checking
                for link in page.external_links:
                    external_urls.add(link.url)

                pct = min(90, int(done_count / max(config.max_pages, 1) * 90) + 5)
                _emit(
                    progress_callback,
                    f"Crawled {done_count} pages — {page.url}",
                    pct,
                )

            if not todo and not pending_futures:
                break

            time.sleep(0.01)  # avoid busy-spin

    return pages, external_urls


def _fetch_and_parse(
    url: str,
    depth: int,
    config: AuditConfig,
    session: requests.Session,
    robots_data: RobotsData,
) -> PageData:
    """Fetch + parse a single page."""
    # Check robots.txt
    if config.respect_robots and not is_url_allowed(url, robots_data, config.user_agent):
        page = PageData(url=url, depth=depth)
        page.crawl_error = "Blocked by robots.txt"
        page.is_indexable = False
        return page

    page = fetch_page(url, session, config.request_timeout, config.user_agent, depth)
    if page.is_html and page.html:
        parse_page(page, config.domain)

    return page


# ── External link checking ────────────────────────────────────────────────────

def _check_external_links(
    external_urls: set[str],
    pages: dict[str, PageData],
    session: requests.Session,
    config: AuditConfig,
) -> None:
    """
    HEAD-check all external URLs and update LinkData objects in pages.
    """
    # Build a map from URL -> status_code for fast lookup
    url_status: dict[str, tuple[int, list[str]]] = {}

    sampled = list(external_urls)[:500]  # cap at 500 external checks

    with ThreadPoolExecutor(max_workers=min(20, config.max_workers * 2)) as executor:
        futures = {
            executor.submit(check_url_status, url, session, 10, config.user_agent): url
            for url in sampled
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                status, chain = future.result()
            except Exception:
                status, chain = 0, []
            url_status[url] = (status, chain)

    # Update LinkData in all pages
    for page in pages.values():
        for link in page.external_links:
            if link.url in url_status:
                status, chain = url_status[link.url]
                link.status_code = status
                link.is_broken = status in range(400, 600) or status == 0
                link.redirect_chain = chain


# ── Sitemap helper ────────────────────────────────────────────────────────────

def _get_sitemap(config: AuditConfig, session: requests.Session) -> Optional[SitemapData]:
    sitemap_url = config.sitemap_url

    if sitemap_url:
        return fetch_sitemap(sitemap_url, session, config.request_timeout)

    # Auto-discover
    for candidate in guess_sitemap_url(config.start_url):
        data = fetch_sitemap(candidate, session, config.request_timeout)
        if data.exists:
            return data

    return SitemapData(url="", exists=False, parse_errors=["No sitemap found"])


# ── URL normalization ─────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """
    Normalize a URL for deduplication:
    - Lowercase scheme and host
    - Remove fragment
    - Remove trailing slash from path (except root)
    - Remove default ports (80 for http, 443 for https)
    """
    try:
        p = urlparse(url.strip())
        if p.scheme not in ("http", "https"):
            return ""
        if not p.netloc:
            return ""

        host = p.netloc.lower()
        # Remove default ports
        if host.endswith(":80") and p.scheme == "http":
            host = host[:-3]
        if host.endswith(":443") and p.scheme == "https":
            host = host[:-4]

        path = p.path
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        query = p.query
        return urlunparse((p.scheme, host, path, "", query, ""))
    except Exception:
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        max_retries=requests.adapters.Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    return session


def _emit(callback: Optional[Callable], message: str, pct: int) -> None:
    if callback:
        try:
            callback({"message": message, "pct": pct})
        except Exception:
            pass


def _build_stats(result: AuditResult) -> dict:
    pages = result.pages
    total = len(pages)
    status_counts: dict[str, int] = {}
    for page in pages.values():
        family = f"{page.status_code // 100}xx" if page.status_code else "Error"
        status_counts[family] = status_counts.get(family, 0) + 1

    response_times = [p.response_time_ms for p in pages.values() if p.response_time_ms > 0]
    avg_rt = sum(response_times) / len(response_times) if response_times else 0
    page_sizes = [p.page_size_bytes for p in pages.values() if p.page_size_bytes > 0]
    avg_size = sum(page_sizes) / len(page_sizes) if page_sizes else 0

    return {
        "total_pages": total,
        "status_counts": status_counts,
        "avg_response_time_ms": round(avg_rt, 1),
        "avg_page_size_bytes": int(avg_size),
        "crawl_duration_s": round(result.duration_seconds, 1),
        "indexable_pages": sum(1 for p in pages.values() if p.is_indexable),
        "broken_pages": sum(1 for p in pages.values() if p.status_code in range(400, 600)),
        "redirect_pages": sum(1 for p in pages.values() if p.redirect_chain),
    }
