"""
Advanced mode analyzers.
These run only when AuditConfig.advanced_mode is True.

Checks are organised into 8 analyzer classes + 2 batch cross-page checkers:
  1.  URLStructureAnalyzer       — URL quality, depth, params, session IDs
  2.  ContentQualityAnalyzer     — Reading level, keyword density, soft-404, Lorem ipsum
  3.  LinkQualityAnalyzer        — Generic anchors, unsafe new-tab, image-links, duplicates
  4.  TechnicalEnhancedAnalyzer  — lang attr, multiple titles, meta refresh, favicon, pagination
  5.  ServerHeaderAnalyzer       — Cache-Control, compression, server/X-Powered-By disclosure
  6.  ImageEnhancedAnalyzer      — Missing dimensions (CLS), srcset, old formats
  7.  SocialRichResultsAnalyzer  — Twitter Cards, OG type/locale, schema @context/@type
  8.  ResourceHintsAnalyzer      — Preconnect, render-blocking CSS count
  Batch:
  9.  run_trailing_slash_checks  — Trailing-slash duplicate URLs
  10. run_noindex_link_checks    — Non-indexable pages receiving many internal links
  11. run_www_consistency_checks — Mixed www / non-www internal links
"""
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse, parse_qs, unquote

from bs4 import BeautifulSoup

from models import AuditConfig, Issue, PageData, Severity
from analyzers.base import BaseAnalyzer


# ── Thresholds ─────────────────────────────────────────────────────────────────
_URL_MAX_LENGTH     = 115
_URL_MAX_DEPTH      = 5
_LINKS_MAX          = 150
_CONTENT_RATIO_MIN  = 0.10   # text chars / html chars
_KEYWORD_DENSITY    = 0.05   # 5 %
_FK_GRADE_MAX       = 14     # Flesch-Kincaid grade level
_MIN_WORD_LEN       = 4      # ignore short words for density
_NOINDEX_LINK_MIN   = 3      # min inlinks before flagging a noindex page

_SESSION_PARAMS = {
    "sessid", "sessionid", "phpsessid", "jsessionid",
    "aspsessionid", "sid", "session",
}

_GENERIC_ANCHORS = {
    "click here", "here", "read more", "more", "link", "this",
    "click", "go", "visit", "website", "page", "learn more",
    "more info", "more information", "details", "info",
    "check it out", "download", "buy now", "see more",
    "view more", "find out more", "this page", "this site",
    "this link", "continue", "get started", "start here",
}

_OLD_IMG_EXTS = {".bmp", ".tiff", ".tif"}

_SOFT_404_SIGNALS = [
    "page not found", "404", "not found", "does not exist",
    "no longer available", "page cannot be found",
    "couldn't find", "can't find", "error 404",
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. URL Structure
# ─────────────────────────────────────────────────────────────────────────────

class URLStructureAnalyzer(BaseAnalyzer):
    category = "URL Structure"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        issues: list[Issue] = []
        url = page.url

        try:
            parsed = urlparse(url)
        except Exception:
            return issues

        path  = parsed.path or "/"
        query = parsed.query
        params = parse_qs(query)

        # ── Length ────────────────────────────────────────────────────────────
        if len(url) > _URL_MAX_LENGTH:
            issues.append(self.warning(
                url, "url_too_long",
                f"URL is {len(url)} characters (recommended max {_URL_MAX_LENGTH}).",
                "Shorten URL slugs — long URLs are truncated in SERPs and harder to share.",
                detail=f"{len(url)} chars",
            ))

        # ── Uppercase in path ─────────────────────────────────────────────────
        if path != path.lower():
            issues.append(self.warning(
                url, "url_uppercase",
                "URL path contains uppercase letters, risking duplicate content via case variations.",
                "Use all-lowercase URLs and 301-redirect any uppercase variants to the canonical form.",
                detail=path,
            ))

        # ── Underscores (Google prefers hyphens) ──────────────────────────────
        if "_" in path:
            issues.append(self.info(
                url, "url_underscores",
                "URL slug uses underscores (_). Google treats hyphens (-) as word separators, not underscores.",
                "Replace underscores with hyphens in URL slugs.",
                detail=path,
            ))

        # ── Too deep ──────────────────────────────────────────────────────────
        segments = [s for s in path.split("/") if s]
        if len(segments) > _URL_MAX_DEPTH:
            issues.append(self.warning(
                url, "url_too_deep",
                f"URL is {len(segments)} directory levels deep (recommended max {_URL_MAX_DEPTH}).",
                "Flatten the URL structure — deeply nested paths are harder to crawl and dilute authority.",
                detail=f"{len(segments)} segments",
            ))

        # ── Session ID parameters ─────────────────────────────────────────────
        lower_params = {k.lower() for k in params}
        matched_sid = lower_params & _SESSION_PARAMS
        if matched_sid:
            issues.append(self.critical(
                url, "url_session_id",
                f"URL contains a session ID parameter ({', '.join(matched_sid)}), creating near-infinite URL variants.",
                "Use cookies for session management. Strip session IDs from URLs.",
                detail=f"param(s): {', '.join(matched_sid)}",
            ))

        # ── Too many query parameters ─────────────────────────────────────────
        if len(params) > 3:
            issues.append(self.info(
                url, "url_too_many_params",
                f"URL has {len(params)} query parameters. Complex URLs may not be fully indexed.",
                "Reduce query parameters. Use URL parameter handling in Google Search Console for faceted navigation.",
                detail=f"{len(params)} params",
            ))

        # ── Spaces in path ────────────────────────────────────────────────────
        if "%20" in path or "+" in path:
            issues.append(self.warning(
                url, "url_spaces",
                "URL path contains encoded spaces (%20 or +).",
                "Replace spaces with hyphens in URL slugs.",
                detail=unquote(path),
            ))

        # ── URL contains repeated slashes ─────────────────────────────────────
        if "//" in path:
            issues.append(self.warning(
                url, "url_double_slash",
                "URL path contains consecutive slashes (//), which may cause duplicate content.",
                "Fix the URL to remove double slashes.",
                detail=path,
            ))

        # ── Non-ASCII characters ──────────────────────────────────────────────
        try:
            path.encode("ascii")
        except UnicodeEncodeError:
            issues.append(self.info(
                url, "url_non_ascii",
                "URL contains non-ASCII characters. Some crawlers or tools may not handle these correctly.",
                "Use ASCII-only URL slugs. Transliterate non-ASCII characters to their closest ASCII equivalents.",
                detail=path,
            ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 2. Content Quality
# ─────────────────────────────────────────────────────────────────────────────

class ContentQualityAnalyzer(BaseAnalyzer):
    category = "Content Quality"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300):
            return []

        issues: list[Issue] = []
        url  = page.url
        text = page.text_content

        # ── Lorem ipsum / placeholder text ────────────────────────────────────
        if "lorem ipsum" in text.lower():
            issues.append(self.critical(
                url, "lorem_ipsum",
                "Page contains Lorem Ipsum placeholder text.",
                "Replace all placeholder text with real, relevant content before publishing.",
            ))

        # ── Content-to-HTML ratio ─────────────────────────────────────────────
        if page.html and page.word_count > 20:
            ratio = len(text) / max(len(page.html), 1)
            if ratio < _CONTENT_RATIO_MIN:
                issues.append(self.warning(
                    url, "low_content_html_ratio",
                    f"Only {ratio * 100:.1f}% of page HTML is visible text — page is bloated with markup.",
                    "Reduce unnecessary HTML wrappers, inline scripts, and tracking code.",
                    detail=f"{ratio * 100:.1f}% text-to-HTML ratio",
                ))

        # ── Keyword stuffing ──────────────────────────────────────────────────
        if page.word_count > 100 and text:
            words = [re.sub(r"[^a-z]", "", w) for w in text.lower().split()]
            words = [w for w in words if len(w) >= _MIN_WORD_LEN]
            if words:
                freq = Counter(words)
                top_word, top_count = freq.most_common(1)[0]
                density = top_count / len(words)
                if density > _KEYWORD_DENSITY:
                    issues.append(self.warning(
                        url, "keyword_stuffing",
                        f'Word "{top_word}" appears {top_count}× ({density * 100:.1f}% density) — possible keyword stuffing.',
                        "Aim for natural keyword usage (1–3%). Over-optimisation can trigger spam filters.",
                        detail=f'"{top_word}" × {top_count} ({density * 100:.1f}%)',
                    ))

        # ── Reading level (Flesch-Kincaid Grade) ──────────────────────────────
        if page.word_count > 100:
            grade = _fk_grade(text)
            if grade > _FK_GRADE_MAX:
                issues.append(self.info(
                    url, "complex_reading_level",
                    f"Content has a Flesch-Kincaid grade level of {grade:.1f} — difficult for general audiences.",
                    "Simplify sentences and vocabulary. Grade 8–10 is optimal for broad web audiences.",
                    detail=f"Grade {grade:.1f}",
                ))

        # ── Soft 404 detection ────────────────────────────────────────────────
        if page.status_code == 200 and page.is_indexable and page.word_count < 200:
            snippet = text.lower()[:600]
            for signal in _SOFT_404_SIGNALS:
                if signal in snippet:
                    issues.append(self.warning(
                        url, "soft_404",
                        f'Page returns 200 but content suggests it may be a soft 404 ("{signal}" detected).',
                        "Return a proper 404 or 410 for missing content. Add real content if the page should exist.",
                        detail=f'Signal: "{signal}"',
                    ))
                    break

        # ── Very long sentences / wall of text ───────────────────────────────
        if text and page.word_count > 300:
            sentences = re.split(r"[.!?]+", text)
            long_sentences = [s for s in sentences if len(s.split()) > 50]
            if len(long_sentences) > 3:
                issues.append(self.info(
                    url, "long_sentences",
                    f"Page has {len(long_sentences)} sentences longer than 50 words — hard to read.",
                    "Break long sentences into shorter ones. Aim for an average of 15–20 words per sentence.",
                    detail=f"{len(long_sentences)} long sentences",
                ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 3. Link Quality
# ─────────────────────────────────────────────────────────────────────────────

class LinkQualityAnalyzer(BaseAnalyzer):
    category = "Link Quality"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300):
            return []

        issues: list[Issue] = []
        url  = page.url
        soup = _parse(page.html) if page.html else None

        # ── Too many internal links ───────────────────────────────────────────
        n_int = len(page.internal_links)
        if n_int > _LINKS_MAX:
            issues.append(self.warning(
                url, "too_many_links",
                f"Page has {n_int} internal links — exceeds the recommended {_LINKS_MAX}.",
                "Reduce navigation links. Excessive links dilute PageRank and overwhelm crawlers.",
                detail=f"{n_int} internal links",
            ))

        # ── Generic anchor text ───────────────────────────────────────────────
        generic = [
            lnk.anchor_text.lower().strip()
            for lnk in page.internal_links
            if lnk.anchor_text.lower().strip() in _GENERIC_ANCHORS
        ]
        if generic:
            top = Counter(generic).most_common(3)
            issues.append(self.warning(
                url, "generic_anchor_text",
                f"{len(generic)} internal link(s) use generic anchor text.",
                "Use descriptive anchor text that indicates the destination page topic.",
                detail=", ".join(f'"{a}" ×{c}' for a, c in top),
                element="<a>",
            ))

        # ── Duplicate internal links (same URL > 2 times) ─────────────────────
        url_counts = Counter(lnk.url for lnk in page.internal_links)
        dupes = {u: c for u, c in url_counts.items() if c > 2}
        if dupes:
            issues.append(self.info(
                url, "duplicate_links",
                f"{len(dupes)} destination URL(s) are linked more than twice on this page.",
                "Consolidate duplicate links — each destination should be linked once with the best anchor text.",
                detail="; ".join(
                    f"{u.rstrip('/').split('/')[-1] or u} ×{c}"
                    for u, c in list(dupes.items())[:4]
                ),
            ))

        if soup:
            # ── target="_blank" without rel="noopener noreferrer" ────────────
            unsafe = []
            for a in soup.find_all("a", target="_blank"):
                rel = " ".join(a.get("rel", [])) if isinstance(a.get("rel"), list) else str(a.get("rel", ""))
                if "noopener" not in rel.lower():
                    href = (a.get("href") or "")[:80]
                    unsafe.append(href)
            if unsafe:
                issues.append(self.warning(
                    url, "unsafe_new_tab_links",
                    f"{len(unsafe)} link(s) open in a new tab without rel=\"noopener noreferrer\".",
                    'Add rel="noopener noreferrer" to all target="_blank" links to prevent tabnapping.',
                    detail=f"{len(unsafe)} links",
                    element='<a target="_blank">',
                ))

            # ── Image links without alt text ──────────────────────────────────
            bad_img_links = 0
            for a in soup.find_all("a", href=True):
                if a.find_all("img") and not a.get_text(strip=True):
                    for img in a.find_all("img"):
                        if not img.get("alt", "").strip():
                            bad_img_links += 1
                            break
            if bad_img_links:
                issues.append(self.warning(
                    url, "image_link_no_alt",
                    f"{bad_img_links} image link(s) have no alt text — link purpose is not communicated to screen readers or search engines.",
                    "Add descriptive alt text to images used as links.",
                    element="<a><img alt=''>",
                ))

            # ── Empty links (<a href='...'></a> with no text or image) ────────
            empty_links = [
                a.get("href", "")[:60]
                for a in soup.find_all("a", href=True)
                if not a.get_text(strip=True) and not a.find("img")
            ]
            if empty_links:
                issues.append(self.info(
                    url, "empty_links",
                    f"{len(empty_links)} link(s) have no visible text or image content.",
                    "Add descriptive anchor text or remove empty links.",
                    detail=f"{len(empty_links)} empty links",
                    element="<a></a>",
                ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 4. Technical Enhanced
# ─────────────────────────────────────────────────────────────────────────────

class TechnicalEnhancedAnalyzer(BaseAnalyzer):
    category = "Technical SEO"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if not page.is_html:
            return []

        issues: list[Issue] = []
        url  = page.url
        soup = _parse(page.html) if page.html else None

        if not soup:
            return issues

        # ── Missing lang attribute on <html> ──────────────────────────────────
        html_tag = soup.find("html")
        if html_tag is not None:
            lang = html_tag.get("lang", "").strip()
            if not lang:
                issues.append(self.warning(
                    url, "missing_html_lang",
                    "<html> element is missing the lang attribute.",
                    'Add lang attribute to <html> (e.g. lang="en") for accessibility and SEO.',
                    element="<html>",
                ))
            elif lang and page.hreflang_tags:
                # lang vs hreflang mismatch
                html_lang_base = lang.split("-")[0].lower()
                hreflang_bases = {
                    t.hreflang.split("-")[0].lower()
                    for t in page.hreflang_tags
                    if t.hreflang.lower() != "x-default"
                }
                if hreflang_bases and html_lang_base not in hreflang_bases:
                    issues.append(self.warning(
                        url, "html_lang_hreflang_mismatch",
                        f'<html lang="{lang}"> does not match any declared hreflang language.',
                        "Ensure html lang attribute matches one of the hreflang values for this page.",
                        detail=f'html lang="{lang}", hreflang langs: {", ".join(sorted(hreflang_bases))}',
                    ))

        # ── Multiple <title> tags ─────────────────────────────────────────────
        titles = soup.find_all("title")
        if len(titles) > 1:
            issues.append(self.critical(
                url, "multiple_title_tags",
                f"Page has {len(titles)} <title> tags — only the first is used by browsers and search engines.",
                "Remove duplicate <title> tags. Keep exactly one in <head>.",
                element="<title>",
            ))

        # ── <title> outside <head> ────────────────────────────────────────────
        head = soup.find("head")
        if head and titles:
            for t in titles:
                if t not in head.find_all("title"):
                    issues.append(self.warning(
                        url, "title_not_in_head",
                        "<title> tag found outside of <head>.",
                        "Move the <title> tag into the <head> section.",
                        element="<title>",
                    ))
                    break

        # ── Meta refresh ──────────────────────────────────────────────────────
        for meta in soup.find_all("meta", {"http-equiv": re.compile(r"^refresh$", re.I)}):
            content = meta.get("content", "")
            issues.append(self.warning(
                url, "meta_refresh",
                f'Page uses <meta http-equiv="refresh"> redirect.',
                "Replace meta-refresh redirects with proper 301 server-side redirects.",
                detail=f'content="{content}"',
                element='<meta http-equiv="refresh">',
            ))

        # ── Missing favicon ───────────────────────────────────────────────────
        if page.depth == 0:
            has_favicon = bool(soup.find(
                "link",
                rel=lambda r: r and any(
                    "icon" in x.lower()
                    for x in (r if isinstance(r, list) else [r])
                ),
            ))
            if not has_favicon:
                issues.append(self.info(
                    url, "missing_favicon",
                    "No favicon <link> tag declared in <head>.",
                    'Add <link rel="icon" href="/favicon.ico"> or a PNG favicon to your HTML.',
                    element='<link rel="icon">',
                ))

        # ── Pagination rel=prev/next ───────────────────────────────────────────
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        looks_paginated = (
            any(p in {k.lower() for k in params} for p in ("page", "p", "pg", "paged"))
            or bool(re.search(r"/page/\d+", parsed.path, re.I))
            or bool(re.search(r"-\d+/?$", parsed.path))
        )
        if looks_paginated:
            has_prev = bool(soup.find("link", rel=lambda r: r and "prev" in (r if isinstance(r, list) else [r])))
            has_next = bool(soup.find("link", rel=lambda r: r and "next" in (r if isinstance(r, list) else [r])))
            if not has_prev and not has_next:
                issues.append(self.info(
                    url, "pagination_no_rel_links",
                    "Paginated page has no rel=\"prev\"/\"next\" link elements.",
                    "Add rel=\"prev\"/\"next\" links on paginated series to aid navigation.",
                    element='<link rel="prev/next">',
                ))

        # ── Frames / iframes (SEO concern) ────────────────────────────────────
        iframes = soup.find_all("iframe")
        if iframes:
            issues.append(self.info(
                url, "iframes_present",
                f"Page contains {len(iframes)} <iframe> element(s). Content inside iframes is not easily indexed.",
                "Avoid using iframes for important content. Embed content directly in the HTML.",
                detail=f"{len(iframes)} iframe(s)",
                element="<iframe>",
            ))

        # ── Canonical in <body> instead of <head> ─────────────────────────────
        body = soup.find("body")
        if body and page.canonical_url:
            body_canonical = body.find("link", rel=lambda r: r and "canonical" in (r if isinstance(r, list) else [r]))
            if body_canonical:
                issues.append(self.critical(
                    url, "canonical_in_body",
                    "<link rel=\"canonical\"> is placed in <body> instead of <head> — it may be ignored.",
                    "Move the canonical link tag into the <head> section.",
                    element='<link rel="canonical">',
                ))

        # ── Inline styles (excessive) ─────────────────────────────────────────
        inline_style_tags = soup.find_all("style")
        inline_style_bytes = sum(len((t.string or "").encode()) for t in inline_style_tags)
        if inline_style_bytes > 20_000:
            issues.append(self.info(
                url, "excessive_inline_styles",
                f"Page has {inline_style_bytes // 1024} KB of inline CSS in <style> blocks.",
                "Move inline styles to external CSS files for better caching and maintainability.",
                detail=f"{inline_style_bytes // 1024} KB inline CSS",
            ))

        # ── Missing meta charset ──────────────────────────────────────────────
        has_charset = bool(
            soup.find("meta", charset=True)
            or soup.find("meta", {"http-equiv": re.compile(r"content-type", re.I)})
        )
        if not has_charset:
            issues.append(self.warning(
                url, "missing_charset",
                "Page does not declare a character encoding.",
                'Add <meta charset="UTF-8"> as the first element in <head>.',
                element='<meta charset="UTF-8">',
            ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 5. Server Headers
# ─────────────────────────────────────────────────────────────────────────────

class ServerHeaderAnalyzer(BaseAnalyzer):
    category = "Security"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if page.status_code == 0:
            return []

        issues: list[Issue] = []
        url = page.url
        hdrs = {k.lower(): v for k, v in page.response_headers.items()}

        # ── Server version disclosure ─────────────────────────────────────────
        server = hdrs.get("server", "")
        if server and re.search(r"\d", server):
            issues.append(self.info(
                url, "server_version_disclosure",
                f'Server header discloses software version: "{server}".',
                "Configure your server to omit version numbers from the Server header.",
                detail=f"Server: {server}",
            ))

        # ── X-Powered-By disclosure ───────────────────────────────────────────
        xpb = hdrs.get("x-powered-by", "")
        if xpb:
            issues.append(self.info(
                url, "x_powered_by_disclosure",
                f'X-Powered-By header exposes technology stack: "{xpb}".',
                "Remove the X-Powered-By header to reduce fingerprinting surface.",
                detail=f"X-Powered-By: {xpb}",
            ))

        # ── Missing Cache-Control ─────────────────────────────────────────────
        if "cache-control" not in hdrs and page.is_html:
            issues.append(self.warning(
                url, "missing_cache_control",
                "Page is missing a Cache-Control header.",
                "Add Cache-Control to enable browser caching and reduce repeat load times.",
            ))

        # ── Missing compression ───────────────────────────────────────────────
        content_encoding = hdrs.get("content-encoding", "")
        transfer_encoding = hdrs.get("transfer-encoding", "")
        is_compressed = any(enc in (content_encoding + transfer_encoding).lower() for enc in ("gzip", "br", "deflate", "zstd"))
        if not is_compressed and page.page_size_bytes > 10_000 and page.is_html:
            issues.append(self.warning(
                url, "missing_compression",
                "Page response is not compressed (no gzip/Brotli Content-Encoding header).",
                "Enable gzip or Brotli compression on your server to reduce transfer size by 60–80%.",
            ))

        # ── Missing Vary header for content negotiation ───────────────────────
        if "accept-encoding" in hdrs.get("vary", "").lower() is False and is_compressed:
            pass  # Vary: Accept-Encoding is best practice but low priority

        # ── ETag / Last-Modified for caching ─────────────────────────────────
        if "etag" not in hdrs and "last-modified" not in hdrs and page.is_html:
            issues.append(self.info(
                url, "missing_etag_lastmodified",
                "Page has neither an ETag nor a Last-Modified header.",
                "Add ETag or Last-Modified headers to enable conditional requests and reduce bandwidth.",
            ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 6. Image Enhanced
# ─────────────────────────────────────────────────────────────────────────────

class ImageEnhancedAnalyzer(BaseAnalyzer):
    category = "Images"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300):
            return []

        issues: list[Issue] = []
        url  = page.url
        soup = _parse(page.html) if page.html else None

        if not soup:
            return issues

        imgs = [i for i in soup.find_all("img", src=True) if not i.get("src", "").startswith("data:")]
        if not imgs:
            return issues

        missing_dims = 0
        no_srcset    = 0
        old_fmts: list[str] = []

        for img in imgs:
            src = img.get("src", "")

            # Missing width / height → causes Cumulative Layout Shift
            if not img.get("width") or not img.get("height"):
                missing_dims += 1

            # Missing srcset for responsive images
            if not img.get("srcset"):
                no_srcset += 1

            # Old / suboptimal format
            ext = ""
            clean_src = src.split("?")[0].lower()
            if "." in clean_src:
                ext = "." + clean_src.rsplit(".", 1)[-1]
            if ext in _OLD_IMG_EXTS:
                old_fmts.append(src)

        if missing_dims:
            issues.append(self.warning(
                url, "images_missing_dimensions",
                f"{missing_dims} image(s) are missing explicit width/height attributes, causing layout shift (CLS).",
                "Add width and height attributes to all <img> tags matching the image's intrinsic size.",
                detail=f"{missing_dims} of {len(imgs)} images",
                element="<img>",
            ))

        if no_srcset > 3:
            issues.append(self.info(
                url, "images_missing_srcset",
                f"{no_srcset} image(s) have no srcset attribute for responsive delivery.",
                "Add srcset and sizes attributes so browsers can select the right image size per device.",
                detail=f"{no_srcset} of {len(imgs)} images",
                element="<img srcset>",
            ))

        for src in old_fmts:
            fname = src.rstrip("/").split("/")[-1].split("?")[0]
            issues.append(self.info(
                url, "image_old_format",
                f'Image "{fname}" uses an outdated format. Consider WebP or AVIF for better compression.',
                "Convert images to WebP or AVIF to reduce file sizes by 25–50% with no visible quality loss.",
                detail=src[:120],
                element="<img>",
            ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 7. Social & Rich Results
# ─────────────────────────────────────────────────────────────────────────────

class SocialRichResultsAnalyzer(BaseAnalyzer):
    category = "Technical SEO"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300) or not page.is_indexable:
            return []

        issues: list[Issue] = []
        url = page.url

        # ── Twitter Card ──────────────────────────────────────────────────────
        tw = page.twitter_tags
        if not tw:
            issues.append(self.info(
                url, "missing_twitter_card",
                "Page has no Twitter Card meta tags.",
                "Add twitter:card, twitter:title, twitter:description, and twitter:image tags for richer social previews.",
            ))
        else:
            for tag in ("twitter:card", "twitter:title", "twitter:description", "twitter:image"):
                if tag not in tw:
                    slug = tag.replace(":", "_")
                    issues.append(self.info(
                        url, f"missing_{slug}",
                        f"Missing Twitter Card tag: <meta name=\"{tag}\">.",
                        f'Add <meta name="{tag}" content="…"> for complete Twitter Card support.',
                        element=f'<meta name="{tag}">',
                    ))

        # ── Open Graph enhancements ───────────────────────────────────────────
        og = page.og_tags
        if og:
            if "og:type" not in og:
                issues.append(self.info(
                    url, "missing_og_type",
                    "Missing og:type Open Graph tag.",
                    "Add <meta property='og:type' content='website'> (or 'article', 'product', etc.).",
                ))
            if "og:locale" not in og:
                issues.append(self.info(
                    url, "missing_og_locale",
                    "Missing og:locale Open Graph tag.",
                    "Add <meta property='og:locale' content='en_US'> for locale targeting.",
                ))
            if "og:site_name" not in og:
                issues.append(self.info(
                    url, "missing_og_site_name",
                    "Missing og:site_name Open Graph tag.",
                    "Add <meta property='og:site_name' content='Your Brand'> for consistent social previews.",
                ))

        # ── Structured data quality ───────────────────────────────────────────
        for schema in page.schema_markup:
            if not isinstance(schema, dict):
                continue
            if "@context" not in schema:
                issues.append(self.warning(
                    url, "schema_missing_context",
                    'JSON-LD structured data block is missing "@context".',
                    'Add "@context": "https://schema.org" to all JSON-LD blocks.',
                    element='<script type="application/ld+json">',
                ))
            if "@type" not in schema:
                issues.append(self.warning(
                    url, "schema_missing_type",
                    'JSON-LD structured data block is missing "@type".',
                    'Specify the schema type, e.g. "@type": "Article".',
                    element='<script type="application/ld+json">',
                ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 8. Resource Hints & Performance
# ─────────────────────────────────────────────────────────────────────────────

class ResourceHintsAnalyzer(BaseAnalyzer):
    category = "Performance"

    def analyze(self, page: PageData, all_pages: dict, config: AuditConfig) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300):
            return []

        issues: list[Issue] = []
        url  = page.url
        soup = _parse(page.html) if page.html else None

        if not soup:
            return issues

        page_origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # ── External origins without preconnect ───────────────────────────────
        external_origins: set[str] = set()
        for script in page.scripts:
            if script.src:
                o = _origin(script.src, page_origin)
                if o:
                    external_origins.add(o)
        for css_url in page.stylesheets:
            o = _origin(css_url, page_origin)
            if o:
                external_origins.add(o)

        declared_preconnect: set[str] = set()
        for link in soup.find_all(
            "link",
            rel=lambda r: r and "preconnect" in (r if isinstance(r, list) else [r]),
        ):
            href = link.get("href", "").rstrip("/")
            if href:
                declared_preconnect.add(href)

        missing_pc = external_origins - declared_preconnect
        if missing_pc and len(external_origins) > 1:
            issues.append(self.info(
                url, "missing_preconnect",
                f"{len(missing_pc)} external origin(s) load resources without a preconnect hint.",
                "Add <link rel='preconnect' href='origin'> for key third-party domains to reduce connection overhead.",
                detail=", ".join(sorted(missing_pc)[:4]),
            ))

        # ── Render-blocking stylesheets count ─────────────────────────────────
        head = soup.find("head")
        if head:
            blocking_css = [
                lnk.get("href", "")
                for lnk in head.find_all(
                    "link",
                    rel=lambda r: r and "stylesheet" in (r if isinstance(r, list) else [r]),
                )
                if lnk.get("media", "all").lower() in ("all", "", "screen")
            ]
            if len(blocking_css) > 4:
                issues.append(self.info(
                    url, "many_render_blocking_stylesheets",
                    f"{len(blocking_css)} render-blocking stylesheets are loaded in <head>.",
                    "Inline critical CSS and defer non-critical stylesheets with media='print' + onload swap.",
                    detail=f"{len(blocking_css)} CSS files",
                ))

        # ── Missing preload for LCP candidate ─────────────────────────────────
        # Heuristic: first above-fold <img> without loading="lazy" + no <link rel="preload">
        preloads = {
            lnk.get("href", "")
            for lnk in soup.find_all("link", rel=lambda r: r and "preload" in (r if isinstance(r, list) else [r]))
        }
        if not preloads and page.images:
            first_img = page.images[0]
            if first_img.loading != "lazy" and not first_img.is_broken:
                issues.append(self.info(
                    url, "missing_lcp_preload",
                    "No <link rel='preload'> found. The LCP image candidate may load late.",
                    "Add <link rel='preload' as='image' href='…'> for the above-fold hero image.",
                    detail=first_img.src[:100],
                ))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# Batch cross-page checks
# ─────────────────────────────────────────────────────────────────────────────

def run_trailing_slash_checks(
    all_pages: dict[str, PageData],
    config: AuditConfig,
) -> list[Issue]:
    """Flag URLs that exist both with and without a trailing slash."""
    issues: list[Issue] = []
    analyzer = _make_batch("Technical SEO")

    seen: dict[str, list[str]] = {}
    for url in all_pages:
        norm = url.rstrip("/")
        seen.setdefault(norm, []).append(url)

    for norm_url, variants in seen.items():
        if len(variants) > 1:
            issues.append(analyzer.warning(
                variants[0], "trailing_slash_inconsistency",
                "URL exists both with and without a trailing slash, creating duplicate content.",
                "Pick one canonical form and 301-redirect the other. Update internal links accordingly.",
                detail=" vs ".join(variants),
            ))

    return issues


def run_noindex_link_checks(
    all_pages: dict[str, PageData],
    config: AuditConfig,
) -> list[Issue]:
    """Flag non-indexable pages that receive many internal links (crawl budget waste)."""
    issues: list[Issue] = []
    analyzer = _make_batch("Technical SEO")

    noindex_urls = {url for url, p in all_pages.items() if not p.is_indexable and p.is_html}
    if not noindex_urls:
        return issues

    inlink_counts: dict[str, int] = {}
    for page in all_pages.values():
        for lnk in page.internal_links:
            if lnk.url in noindex_urls:
                inlink_counts[lnk.url] = inlink_counts.get(lnk.url, 0) + 1

    for url, count in inlink_counts.items():
        if count >= _NOINDEX_LINK_MIN:
            issues.append(analyzer.info(
                url, "noindex_receives_links",
                f"Non-indexable page receives {count} internal link(s), wasting crawl budget.",
                "Remove internal links to noindex pages, or reconsider whether the page should be indexed.",
                detail=f"{count} internal links",
            ))

    return issues


def run_www_consistency_checks(
    all_pages: dict[str, PageData],
    config: AuditConfig,
) -> list[Issue]:
    """Flag pages that mix www and non-www internal links."""
    issues: list[Issue] = []
    analyzer = _make_batch("Technical SEO")

    www_set: set[str]     = set()
    non_www_set: set[str] = set()

    for page in all_pages.values():
        host = urlparse(page.url).netloc.lower()
        if host.startswith("www."):
            www_set.add(page.url)
        else:
            non_www_set.add(page.url)

    if www_set and non_www_set:
        issues.append(analyzer.warning(
            config.start_url, "www_nonwww_mixed",
            f"Site mixes www ({len(www_set)}) and non-www ({len(non_www_set)}) URLs — potential duplicate content.",
            "Canonicalise to one form (www or non-www) and 301-redirect the other across the entire site.",
            detail=f"{len(www_set)} www pages, {len(non_www_set)} non-www pages",
        ))

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _origin(resource_url: str, page_origin: str) -> str | None:
    try:
        p = urlparse(resource_url)
        o = f"{p.scheme}://{p.netloc}"
        return o if o != page_origin and p.netloc else None
    except Exception:
        return None


def _fk_grade(text: str) -> float:
    """Flesch-Kincaid Grade Level (simplified)."""
    sentences = max(1, len(re.split(r"[.!?]+", text)))
    words     = text.split()
    n_words   = max(1, len(words))
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * (n_words / sentences) + 11.8 * (syllables / n_words) - 15.59


def _syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 1
    count = len(re.findall(r"[aeiou]+", word))
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


class _BatchAnalyzerBase(BaseAnalyzer):
    def analyze(self, page, all_pages, config):
        return []


def _make_batch(category: str) -> _BatchAnalyzerBase:
    obj = _BatchAnalyzerBase.__new__(_BatchAnalyzerBase)
    obj.__class__ = type("_B", (_BatchAnalyzerBase,), {"category": category})
    return obj
