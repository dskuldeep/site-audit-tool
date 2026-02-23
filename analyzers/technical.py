"""
Technical SEO analyzer: canonical tags, hreflang, structured data (JSON-LD), Open Graph.
"""
from __future__ import annotations

import re

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer

# Basic BCP47 language tag regex
_BCP47_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")


class TechnicalSEOAnalyzer(BaseAnalyzer):
    category = "Technical SEO"

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

        issues.extend(self._check_canonical(page, all_pages))
        issues.extend(self._check_hreflang(page, all_pages))
        issues.extend(self._check_schema(page))
        issues.extend(self._check_og(page))

        return issues

    # ── Canonical ──────────────────────────────────────────────────────────────

    def _check_canonical(self, page: PageData, all_pages: dict) -> list[Issue]:
        issues: list[Issue] = []
        url = page.url

        if not page.canonical_url:
            if page.is_indexable:
                issues.append(self.warning(
                    url, "missing_canonical",
                    "Indexable page has no canonical URL specified.",
                    "Add <link rel='canonical' href='…'> to prevent duplicate content issues.",
                    element="<link rel='canonical'>",
                ))
            return issues

        canonical = page.canonical_url.rstrip("/")
        page_url = url.rstrip("/")

        # Self-referencing canonical (good practice, just informational)
        if canonical == page_url or canonical == (page.final_url or url).rstrip("/"):
            issues.append(self.info(
                url, "self_referencing_canonical",
                "Page has a self-referencing canonical tag (correct practice).",
                "No action needed — self-referencing canonicals confirm this is the preferred URL.",
                detail=page.canonical_url,
            ))
        else:
            # Check where the canonical points
            canonical_page = all_pages.get(page.canonical_url) or all_pages.get(canonical + "/") or all_pages.get(canonical)

            if canonical_page is not None:
                if canonical_page.status_code in range(400, 600) or canonical_page.status_code == 0:
                    issues.append(self.critical(
                        url, "canonical_points_to_error",
                        f"Canonical URL returns HTTP {canonical_page.status_code}.",
                        "Fix the canonical URL to point to a valid, accessible page.",
                        detail=page.canonical_url,
                    ))
                elif not canonical_page.is_indexable:
                    issues.append(self.critical(
                        url, "canonical_points_to_noindex",
                        "Canonical URL points to a page with a noindex directive.",
                        "The canonical page must be indexable. Fix the noindex on the target or correct the canonical.",
                        detail=page.canonical_url,
                    ))
                elif canonical_page.redirect_chain:
                    issues.append(self.warning(
                        url, "canonical_points_to_redirect",
                        "Canonical URL redirects to another page.",
                        "Update the canonical to point directly to the final destination URL.",
                        detail=f"{page.canonical_url} → {canonical_page.final_url}",
                    ))
            else:
                # Canonical points to an uncrawled / external URL
                issues.append(self.info(
                    url, "canonical_cross_domain",
                    "Canonical URL points to an external or uncrawled page.",
                    "Verify the cross-domain canonical is intentional.",
                    detail=page.canonical_url,
                ))

        return issues

    # ── Hreflang ───────────────────────────────────────────────────────────────

    def _check_hreflang(self, page: PageData, all_pages: dict) -> list[Issue]:
        issues: list[Issue] = []
        url = page.url

        if not page.hreflang_tags:
            return issues

        seen_langs: dict[str, str] = {}

        for tag in page.hreflang_tags:
            lang = tag.hreflang.lower()
            href = tag.href

            # Validate BCP47 format
            if lang != "x-default" and not _BCP47_RE.match(lang):
                issues.append(self.warning(
                    url, "invalid_hreflang_value",
                    f"Hreflang value '{tag.hreflang}' is not a valid BCP47 language tag.",
                    "Use valid language codes such as 'en', 'en-US', 'fr', 'de-AT'.",
                    detail=f"hreflang='{tag.hreflang}' href='{href}'",
                    element="<link rel='alternate' hreflang='…'>",
                ))

            # Duplicate language
            if lang in seen_langs:
                issues.append(self.warning(
                    url, "duplicate_hreflang",
                    f"Duplicate hreflang tag for language '{lang}'.",
                    "Each language/region should appear only once in hreflang annotations.",
                    detail=f"Duplicate: {href}",
                ))
            else:
                seen_langs[lang] = href

            # Check reciprocal tag (the linked page should link back)
            target = all_pages.get(href) or all_pages.get(href.rstrip("/"))
            if target is not None:
                target_langs = {t.hreflang.lower(): t.href for t in target.hreflang_tags}
                current_lang_in_target = any(
                    t.href.rstrip("/") in (url.rstrip("/"), (page.final_url or url).rstrip("/"))
                    for t in target.hreflang_tags
                )
                if not current_lang_in_target:
                    issues.append(self.warning(
                        url, "missing_hreflang_return_link",
                        f"Hreflang target '{href}' does not link back to this page.",
                        "Hreflang must be reciprocal — both pages must reference each other.",
                        detail=f"Missing return tag on: {href}",
                    ))

        # Missing x-default
        if len(seen_langs) > 1 and "x-default" not in seen_langs:
            issues.append(self.info(
                url, "missing_hreflang_x_default",
                "Page has hreflang tags but is missing an x-default fallback.",
                "Add hreflang='x-default' pointing to the page shown when no language matches.",
            ))

        return issues

    # ── Structured data ────────────────────────────────────────────────────────

    def _check_schema(self, page: PageData) -> list[Issue]:
        issues: list[Issue] = []
        url = page.url

        if page.schema_errors:
            for error in page.schema_errors:
                issues.append(self.warning(
                    url, "invalid_json_ld",
                    f"JSON-LD structured data could not be parsed: {error}",
                    "Fix the JSON-LD syntax to ensure search engines can read your structured data.",
                    detail=error,
                    element="<script type='application/ld+json'>",
                ))

        if not page.schema_markup and not page.schema_errors:
            if page.is_indexable:
                issues.append(self.info(
                    url, "missing_schema_markup",
                    "Page has no JSON-LD structured data.",
                    "Add relevant schema markup (Article, Product, BreadcrumbList, etc.) to enable rich results.",
                ))

        return issues

    # ── Open Graph ────────────────────────────────────────────────────────────

    def _check_og(self, page: PageData) -> list[Issue]:
        issues: list[Issue] = []
        url = page.url

        if not page.is_indexable:
            return issues

        required_og = {
            "og:title": "og_missing_title",
            "og:description": "og_missing_description",
            "og:image": "og_missing_image",
            "og:url": "og_missing_url",
        }

        for prop, issue_type in required_og.items():
            if prop not in page.og_tags:
                issues.append(self.info(
                    url, issue_type,
                    f"Missing Open Graph tag: <meta property='{prop}'>.",
                    f"Add <meta property='{prop}' content='…'> for better social sharing previews.",
                    element=f"<meta property='{prop}'>",
                ))

        return issues
