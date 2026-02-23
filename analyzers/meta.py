"""
Meta tag analyzer: title, description, meta robots, viewport, keywords.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer
from config import (
    DESCRIPTION_MAX_CHARS,
    DESCRIPTION_MIN_CHARS,
    TITLE_MAX_CHARS,
    TITLE_MIN_CHARS,
)


class MetaAnalyzer(BaseAnalyzer):
    category = "Meta"

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

        # ── Title ─────────────────────────────────────────────────────────────
        if page.title is None or page.title.strip() == "":
            issues.append(self.critical(
                url, "missing_title",
                "Page is missing a <title> tag.",
                "Add a descriptive <title> tag between 30–60 characters.",
            ))
        else:
            title = page.title.strip()
            length = len(title)

            if length < TITLE_MIN_CHARS:
                issues.append(self.warning(
                    url, "title_too_short",
                    f"Title is too short ({length} chars). Minimum recommended is {TITLE_MIN_CHARS}.",
                    "Expand the title to be more descriptive (30–60 characters).",
                    detail=title,
                ))
            elif length > TITLE_MAX_CHARS:
                issues.append(self.warning(
                    url, "title_too_long",
                    f"Title is too long ({length} chars). Google truncates titles above ~{TITLE_MAX_CHARS} chars.",
                    "Shorten the title to under 60 characters to prevent truncation in SERPs.",
                    detail=title,
                ))

        # ── Description ───────────────────────────────────────────────────────
        if page.meta_description is None or page.meta_description.strip() == "":
            issues.append(self.warning(
                url, "missing_description",
                "Page is missing a meta description.",
                "Add a unique meta description between 70–160 characters to improve click-through rates.",
            ))
        else:
            desc = page.meta_description.strip()
            length = len(desc)

            if length < DESCRIPTION_MIN_CHARS:
                issues.append(self.warning(
                    url, "description_too_short",
                    f"Meta description is too short ({length} chars). Recommended minimum is {DESCRIPTION_MIN_CHARS}.",
                    "Expand the meta description to 70–160 characters.",
                    detail=desc,
                ))
            elif length > DESCRIPTION_MAX_CHARS:
                issues.append(self.warning(
                    url, "description_too_long",
                    f"Meta description is too long ({length} chars). Google may truncate after ~{DESCRIPTION_MAX_CHARS} chars.",
                    "Shorten the meta description to under 160 characters.",
                    detail=desc,
                ))

        # ── Viewport ──────────────────────────────────────────────────────────
        if not page.meta_viewport:
            issues.append(self.warning(
                url, "missing_viewport",
                "Page is missing a viewport meta tag. This may cause poor mobile rendering.",
                'Add <meta name="viewport" content="width=device-width, initial-scale=1">.',
                element="<meta name='viewport'>",
            ))

        # ── Meta robots ───────────────────────────────────────────────────────
        if page.meta_robots:
            robots_lower = page.meta_robots.lower()
            if "noindex" in robots_lower:
                issues.append(self.info(
                    url, "noindex_set",
                    "Page has noindex directive — it will not appear in search results.",
                    "If this page should be indexed, remove the noindex directive.",
                    detail=page.meta_robots,
                    element="<meta name='robots'>",
                ))
            if "nofollow" in robots_lower:
                issues.append(self.info(
                    url, "nofollow_set",
                    "Page has nofollow directive — search engines will not follow links on this page.",
                    "Use nofollow only when intentional. Remove if links should be followed.",
                    detail=page.meta_robots,
                ))

        # ── X-Robots-Tag ──────────────────────────────────────────────────────
        if page.x_robots_tag and "noindex" in page.x_robots_tag.lower():
            issues.append(self.info(
                url, "x_robots_noindex",
                "X-Robots-Tag response header contains noindex.",
                "If this page should be indexed, remove the X-Robots-Tag: noindex header.",
                detail=page.x_robots_tag,
            ))

        return issues


class DuplicateMetaAnalyzer(BaseAnalyzer):
    """
    Cross-page duplicate detection for titles and descriptions.
    Must be run after all pages have been crawled.
    """
    category = "Meta"

    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        # This analyzer defers to run_duplicate_checks()
        return []

    @staticmethod
    def run_duplicate_checks(
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        issues: list[Issue] = []
        analyzer = DuplicateMetaAnalyzer()

        # Build lookup dicts
        title_map: dict[str, list[str]] = {}
        desc_map: dict[str, list[str]] = {}

        for url, page in all_pages.items():
            if not page.is_html or page.status_code not in range(200, 300):
                continue

            if page.title:
                t = page.title.strip().lower()
                title_map.setdefault(t, []).append(url)

            if page.meta_description:
                d = page.meta_description.strip().lower()
                desc_map.setdefault(d, []).append(url)

        # Emit one issue per URL (not per pair)
        for title_key, urls in title_map.items():
            if len(urls) > 1:
                for url in urls:
                    issues.append(analyzer.warning(
                        url, "duplicate_title",
                        f"Duplicate title found on {len(urls)} pages.",
                        "Each page should have a unique, descriptive title.",
                        detail=f"Shared with: {', '.join(u for u in urls if u != url)[:200]}",
                    ))

        for desc_key, urls in desc_map.items():
            if len(urls) > 1:
                for url in urls:
                    issues.append(analyzer.warning(
                        url, "duplicate_description",
                        f"Duplicate meta description found on {len(urls)} pages.",
                        "Each page should have a unique meta description.",
                        detail=f"Shared with: {', '.join(u for u in urls if u != url)[:200]}",
                    ))

        return issues
