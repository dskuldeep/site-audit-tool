"""
Fetches and parses XML sitemaps (including sitemap index files and gzip-compressed sitemaps).
"""
from __future__ import annotations

import gzip
import io
import time
from urllib.parse import urlparse

import requests
from lxml import etree

from models import SitemapData

# XML namespaces used in sitemaps
_NS = {
    "sm":  "http://www.sitemaps.org/schemas/sitemap/0.9",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
    "video": "http://www.google.com/schemas/sitemap-video/1.1",
    "news":  "http://www.google.com/schemas/sitemap-news/0.9",
}

_MAX_RECURSION = 5   # max sitemap-index nesting depth
_MAX_URLS      = 10_000


def fetch_sitemap(url: str, session: requests.Session, timeout: int = 15) -> SitemapData:
    """Fetch and parse a sitemap from the given URL."""
    data = SitemapData(url=url, exists=False)
    _fetch_recursive(url, session, timeout, data, depth=0, seen_sitemaps=set())
    data.url_count = len(data.urls)
    return data


def _fetch_recursive(
    url: str,
    session: requests.Session,
    timeout: int,
    data: SitemapData,
    depth: int,
    seen_sitemaps: set[str],
) -> None:
    if depth > _MAX_RECURSION or url in seen_sitemaps:
        return
    seen_sitemaps.add(url)

    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        data.status_code = resp.status_code

        if resp.status_code != 200:
            data.parse_errors.append(
                f"Sitemap {url!r} returned HTTP {resp.status_code}"
            )
            return

        data.exists = True
        raw = _decompress_if_gzip(resp)
        data.raw_xml += raw[:4096]  # store a snippet for display

        root = _parse_xml(raw, data)
        if root is None:
            return

        tag = _local_tag(root.tag)

        if tag == "sitemapindex":
            data.is_index = True
            # Recurse into child sitemaps
            for sm_elem in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"):
                loc_elem = sm_elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                if loc_elem is not None and loc_elem.text:
                    child_url = loc_elem.text.strip()
                    data.child_sitemaps.append(child_url)
                    _fetch_recursive(child_url, session, timeout, data, depth + 1, seen_sitemaps)

        elif tag == "urlset":
            # Standard URL sitemap
            for url_elem in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
                loc_elem = url_elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                if loc_elem is not None and loc_elem.text:
                    page_url = loc_elem.text.strip()
                    if len(data.urls) < _MAX_URLS:
                        data.urls.append(page_url)

        else:
            data.parse_errors.append(f"Unexpected root element <{tag}> in sitemap {url!r}")

    except requests.RequestException as exc:
        data.parse_errors.append(f"Could not fetch sitemap {url!r}: {exc}")
    except Exception as exc:
        data.parse_errors.append(f"Error processing sitemap {url!r}: {exc}")


def _decompress_if_gzip(resp: requests.Response) -> str:
    """Return the response body as a string, decompressing gzip if needed."""
    content_type = resp.headers.get("content-type", "")
    content_encoding = resp.headers.get("content-encoding", "")

    if (
        resp.url.endswith(".gz")
        or "gzip" in content_type
        or "gzip" in content_encoding
    ):
        try:
            raw_bytes = gzip.decompress(resp.content)
            return raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass  # fall through to plain text

    return resp.text


def _parse_xml(raw: str, data: SitemapData):
    """Parse XML string, recording any parse errors."""
    try:
        root = etree.fromstring(raw.encode("utf-8"))
        return root
    except etree.XMLSyntaxError as exc:
        data.parse_errors.append(f"XML parse error: {exc}")
        return None


def _local_tag(tag: str) -> str:
    """Strip namespace from tag name."""
    if "}" in tag:
        return tag.split("}")[1]
    return tag


def guess_sitemap_url(domain_url: str) -> list[str]:
    """Return candidate sitemap URLs to try if none is provided."""
    parsed = urlparse(domain_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return [
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
        f"{base}/sitemap-index.xml",
        f"{base}/sitemaps/sitemap.xml",
    ]
