"""
Content analyzer: headings, word count, thin content, duplicate content.
"""
from __future__ import annotations

import difflib
from itertools import combinations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer
from config import (
    DUPLICATE_CONTENT_SIMILARITY_THRESHOLD,
    H1_MAX_LENGTH,
    THIN_CONTENT_WORD_COUNT,
)


class ContentAnalyzer(BaseAnalyzer):
    category = "Content"

    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300):
            return []

        issues: list[Issue] = []
        url = page.url

        # ── H1 ────────────────────────────────────────────────────────────────
        if not page.h1_tags:
            if page.is_indexable:
                issues.append(self.warning(
                    url, "missing_h1",
                    "Page has no H1 heading.",
                    "Add a single, descriptive H1 that includes the primary keyword.",
                    element="<h1>",
                ))
        else:
            if len(page.h1_tags) > 1:
                issues.append(self.warning(
                    url, "multiple_h1",
                    f"Page has {len(page.h1_tags)} H1 headings. Only one is recommended.",
                    "Consolidate to a single H1 that best describes the page's main topic.",
                    detail=" | ".join(page.h1_tags[:3]),
                    element="<h1>",
                ))
            for h1 in page.h1_tags:
                if len(h1) > H1_MAX_LENGTH:
                    issues.append(self.info(
                        url, "h1_too_long",
                        f"H1 is too long ({len(h1)} chars). Recommended max is {H1_MAX_LENGTH}.",
                        "Shorten the H1 to be concise and keyword-focused.",
                        detail=h1[:100],
                        element="<h1>",
                    ))

        # ── Heading hierarchy ─────────────────────────────────────────────────
        issues.extend(self._check_heading_hierarchy(page))

        # ── Word count / thin content ─────────────────────────────────────────
        if page.is_indexable and page.word_count < THIN_CONTENT_WORD_COUNT:
            if page.word_count == 0:
                issues.append(self.warning(
                    url, "no_content",
                    "Page appears to have no visible text content.",
                    "Add meaningful content that serves user intent. Blank pages harm SEO.",
                ))
            else:
                issues.append(self.warning(
                    url, "thin_content",
                    f"Page has only {page.word_count} words — below the {THIN_CONTENT_WORD_COUNT}-word threshold for thin content.",
                    "Expand the page with useful, relevant content or consider consolidating with a similar page.",
                    detail=f"{page.word_count} words",
                ))

        # ── H2 missing on long pages ──────────────────────────────────────────
        if page.word_count > 500 and not page.h2_tags:
            issues.append(self.info(
                url, "missing_h2",
                "Long page has no H2 subheadings. Subheadings improve readability and SEO.",
                "Break content into sections with descriptive H2 subheadings.",
                element="<h2>",
            ))

        return issues

    def _check_heading_hierarchy(self, page: PageData) -> list[Issue]:
        """Detect skipped heading levels (e.g. H1 → H3 with no H2)."""
        issues: list[Issue] = []

        # Build ordered list of (level, text)
        headings: list[tuple[int, str]] = []
        for h1 in page.h1_tags:
            headings.append((1, h1))
        for h2 in page.h2_tags:
            headings.append((2, h2))
        for h in page.h3_h6_tags:
            headings.append((h["level"], h["text"]))

        # Sort by first occurrence is complex without position tracking.
        # Do a simpler structural check: if we have h3 but no h2, that's a skip.
        levels_present = {h[0] for h in headings}

        if 3 in levels_present and 2 not in levels_present:
            issues.append(self.info(
                page.url, "skipped_heading_level",
                "Page uses H3 headings but has no H2 — heading hierarchy is skipped.",
                "Ensure heading levels are sequential (H1 → H2 → H3) for proper document structure.",
                element="<h3>",
            ))

        if 4 in levels_present and 3 not in levels_present:
            issues.append(self.info(
                page.url, "skipped_heading_level",
                "Page uses H4 headings but has no H3 — heading hierarchy is skipped.",
                "Ensure heading levels are sequential for proper document structure.",
                element="<h4>",
            ))

        return issues


class DuplicateContentAnalyzer(BaseAnalyzer):
    """
    Cross-page duplicate content detection.
    Uses MD5 hash for exact matches, then difflib for near-duplicates.
    Run as a post-crawl batch check.
    """
    category = "Content"

    def analyze(self, page, all_pages, config):
        return []

    @staticmethod
    def run_duplicate_checks(
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        issues: list[Issue] = []
        analyzer = DuplicateContentAnalyzer()

        # Collect indexable HTML pages with content
        candidates = {
            url: page for url, page in all_pages.items()
            if page.is_html
            and page.status_code in range(200, 300)
            and page.is_indexable
            and page.word_count > 50
        }

        # ── Exact duplicate detection via content hash ─────────────────────
        hash_map: dict[str, list[str]] = {}
        for url, page in candidates.items():
            if page.content_hash:
                hash_map.setdefault(page.content_hash, []).append(url)

        already_flagged: set[str] = set()
        for h, urls in hash_map.items():
            if len(urls) > 1:
                for url in urls:
                    already_flagged.add(url)
                    issues.append(analyzer.warning(
                        url, "duplicate_content_exact",
                        f"Page content is identical to {len(urls) - 1} other page(s).",
                        "Consolidate duplicate pages with a canonical tag or 301 redirect to the preferred version.",
                        detail=f"Duplicates: {', '.join(u for u in urls if u != url)[:200]}",
                    ))

        # ── Near-duplicate detection via difflib ──────────────────────────
        # Only on pages not already flagged as exact duplicates, and only up to 200 pages (performance)
        remaining = [
            (url, page) for url, page in candidates.items()
            if url not in already_flagged
        ][:200]

        # Pre-filter using word-set Jaccard similarity to avoid O(n^2) difflib calls
        checked_pairs: set[frozenset] = set()
        for i, (url_a, page_a) in enumerate(remaining):
            words_a = set(page_a.text_content.lower().split()[:500])
            if not words_a:
                continue
            for url_b, page_b in remaining[i + 1:]:
                pair = frozenset([url_a, url_b])
                if pair in checked_pairs:
                    continue
                checked_pairs.add(pair)

                words_b = set(page_b.text_content.lower().split()[:500])
                if not words_b:
                    continue

                # Jaccard pre-filter
                jaccard = len(words_a & words_b) / len(words_a | words_b)
                if jaccard < 0.7:
                    continue

                # Full difflib comparison
                ratio = difflib.SequenceMatcher(
                    None,
                    page_a.text_content[:3000],
                    page_b.text_content[:3000],
                ).ratio()

                if ratio >= DUPLICATE_CONTENT_SIMILARITY_THRESHOLD:
                    for url in [url_a, url_b]:
                        issues.append(analyzer.warning(
                            url, "duplicate_content_near",
                            f"Page content is {int(ratio * 100)}% similar to another page.",
                            "Differentiate this page's content or use a canonical to indicate the preferred version.",
                            detail=f"Similar to: {url_b if url == url_a else url_a}",
                        ))

        return issues
