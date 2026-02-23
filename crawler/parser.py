"""
HTML parser that transforms raw HTML + PageData (HTTP metadata) into
a fully-populated PageData object.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import tldextract
from bs4 import BeautifulSoup, Tag

from models import (
    HreflangData,
    ImageData,
    LinkData,
    PageData,
    ScriptData,
)


def parse_page(page: PageData, audit_domain: str) -> PageData:
    """
    Populate page fields by parsing page.html.
    Mutates and returns the same PageData object.
    """
    if not page.html or not page.is_html:
        return page

    try:
        soup = BeautifulSoup(page.html, "lxml")
    except Exception:
        soup = BeautifulSoup(page.html, "html.parser")

    base_url = _resolve_base_url(soup, page.final_url or page.url)

    _parse_meta(soup, page, base_url)
    _parse_headings(soup, page)
    _parse_content(soup, page)
    _parse_links(soup, page, base_url, audit_domain)
    _parse_images(soup, page, base_url)
    _parse_scripts(soup, page, base_url)
    _parse_schema(soup, page)
    _parse_og_tags(soup, page)
    _parse_indexability(page)

    return page


# ── Meta ──────────────────────────────────────────────────────────────────────

def _parse_meta(soup: BeautifulSoup, page: PageData, base_url: str) -> None:
    # Title
    title_tag = soup.find("title")
    if title_tag:
        page.title = title_tag.get_text(strip=True)

    # Meta tags
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower().strip()
        prop = (meta.get("property") or "").lower().strip()
        http_equiv = (meta.get("http-equiv") or "").lower().strip()
        content = meta.get("content", "")

        if name == "description":
            page.meta_description = content
        elif name == "keywords":
            page.meta_keywords = content
        elif name == "robots":
            page.meta_robots = content
        elif name == "viewport":
            page.meta_viewport = content

    # Canonical
    canonical_tag = soup.find("link", rel=lambda r: r and "canonical" in (r if isinstance(r, list) else [r]))
    if canonical_tag:
        href = canonical_tag.get("href", "")
        if href:
            page.canonical_url = urljoin(base_url, href.strip())

    # Hreflang
    for link in soup.find_all("link", rel=lambda r: r and "alternate" in (r if isinstance(r, list) else [r])):
        hreflang = link.get("hreflang", "").strip()
        href = link.get("href", "").strip()
        if hreflang and href:
            page.hreflang_tags.append(HreflangData(
                hreflang=hreflang,
                href=urljoin(base_url, href),
            ))


def _resolve_base_url(soup: BeautifulSoup, fallback: str) -> str:
    base_tag = soup.find("base", href=True)
    if base_tag:
        return urljoin(fallback, base_tag["href"])
    return fallback


# ── Headings ──────────────────────────────────────────────────────────────────

def _parse_headings(soup: BeautifulSoup, page: PageData) -> None:
    for h1 in soup.find_all("h1"):
        text = h1.get_text(strip=True)
        if text:
            page.h1_tags.append(text)

    for h2 in soup.find_all("h2"):
        text = h2.get_text(strip=True)
        if text:
            page.h2_tags.append(text)

    for level in range(3, 7):
        for tag in soup.find_all(f"h{level}"):
            text = tag.get_text(strip=True)
            if text:
                page.h3_h6_tags.append({"level": level, "text": text})


# ── Content ───────────────────────────────────────────────────────────────────

def _parse_content(soup: BeautifulSoup, page: PageData) -> None:
    # Remove script/style content for text extraction
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    body = soup.find("body")
    if body:
        text = body.get_text(separator=" ", strip=True)
    else:
        text = soup.get_text(separator=" ", strip=True)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    page.text_content = text
    page.word_count = len(text.split()) if text else 0

    # Content hash for duplicate detection
    normalized = text.lower()
    page.content_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()


# ── Links ─────────────────────────────────────────────────────────────────────

def _parse_links(
    soup: BeautifulSoup,
    page: PageData,
    base_url: str,
    audit_domain: str,
) -> None:
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue

        abs_url = urljoin(base_url, href)
        # Remove fragments
        abs_url = _strip_fragment(abs_url)

        if abs_url in seen:
            continue
        seen.add(abs_url)

        rel = " ".join(a_tag.get("rel", [])) if isinstance(a_tag.get("rel"), list) else str(a_tag.get("rel", ""))
        nofollow = "nofollow" in rel.lower()
        anchor_text = a_tag.get_text(strip=True)

        link = LinkData(
            url=abs_url,
            anchor_text=anchor_text[:200],
            rel=rel,
            nofollow=nofollow,
        )

        if _is_internal(abs_url, audit_domain):
            page.internal_links.append(link)
        else:
            parsed = urlparse(abs_url)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                page.external_links.append(link)


def _strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def _is_internal(url: str, audit_domain: str) -> bool:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    site_ext = tldextract.extract(audit_domain)
    return ext.registered_domain == site_ext.registered_domain


# ── Images ────────────────────────────────────────────────────────────────────

def _parse_images(soup: BeautifulSoup, page: PageData, base_url: str) -> None:
    for img in soup.find_all("img"):
        src = img.get("src", "").strip()
        if not src or src.startswith("data:"):
            continue

        abs_src = urljoin(base_url, src)
        page.images.append(ImageData(
            src=abs_src,
            alt=img.get("alt", ""),
            title=img.get("title", ""),
            width=img.get("width"),
            height=img.get("height"),
            loading=img.get("loading", ""),
        ))


# ── Scripts ───────────────────────────────────────────────────────────────────

def _parse_scripts(soup: BeautifulSoup, page: PageData, base_url: str) -> None:
    head = soup.find("head")
    head_scripts: set = set()

    if head:
        for script in head.find_all("script"):
            head_scripts.add(id(script))

    for script in soup.find_all("script"):
        src = script.get("src", "").strip()
        is_inline = not bool(src)
        in_head = id(script) in head_scripts
        has_async = script.has_attr("async")
        has_defer = script.has_attr("defer")

        inline_size = 0
        if is_inline:
            inline_content = script.string or ""
            inline_size = len(inline_content.encode("utf-8"))

        page.scripts.append(ScriptData(
            src=urljoin(base_url, src) if src else "",
            is_inline=is_inline,
            has_async=has_async,
            has_defer=has_defer,
            in_head=in_head,
            inline_size_bytes=inline_size,
        ))

    # Stylesheets
    for link in soup.find_all("link", rel=lambda r: r and "stylesheet" in (r if isinstance(r, list) else [r])):
        href = link.get("href", "").strip()
        if href:
            page.stylesheets.append(urljoin(base_url, href))


# ── Schema ────────────────────────────────────────────────────────────────────

def _parse_schema(soup: BeautifulSoup, page: PageData) -> None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            text = script.string or ""
            data = json.loads(text)
            if isinstance(data, list):
                page.schema_markup.extend(data)
            else:
                page.schema_markup.append(data)
        except json.JSONDecodeError as exc:
            page.schema_errors.append(f"Invalid JSON-LD: {exc}")


def _parse_og_tags(soup: BeautifulSoup, page: PageData) -> None:
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "").lower()
        name = meta.get("name", "").lower()
        content = meta.get("content", "")

        if prop.startswith("og:"):
            page.og_tags[prop] = content
        elif prop.startswith("twitter:") or name.startswith("twitter:"):
            key = prop or name
            page.twitter_tags[key] = content


# ── Indexability ──────────────────────────────────────────────────────────────

def _parse_indexability(page: PageData) -> None:
    if page.meta_robots:
        robots_lower = page.meta_robots.lower()
        if "noindex" in robots_lower:
            page.is_indexable = False

    if page.x_robots_tag and "noindex" in page.x_robots_tag.lower():
        page.is_indexable = False
