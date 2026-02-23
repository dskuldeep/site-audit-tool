"""
Sitemap analyzer: validates sitemap content against actual crawl results.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData, SitemapData
from analyzers.base import BaseAnalyzer
from config import SITEMAP_MAX_URLS


class SitemapAnalyzer(BaseAnalyzer):
    category = "Sitemap"

    def analyze(self, page, all_pages, config):
        return []

    @staticmethod
    def run_sitemap_checks(
        sitemap_data: SitemapData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        analyzer = SitemapAnalyzer()
        issues: list[Issue] = []

        # ── Sitemap existence ─────────────────────────────────────────────────
        if not sitemap_data or not sitemap_data.exists:
            issues.append(analyzer.warning(
                config.start_url, "no_sitemap",
                "No sitemap.xml was found for this domain.",
                "Create an XML sitemap and submit it to Google Search Console and Bing Webmaster Tools.",
            ))
            return issues

        # ── XML parse errors ──────────────────────────────────────────────────
        for error in sitemap_data.parse_errors:
            issues.append(analyzer.critical(
                sitemap_data.url, "sitemap_xml_error",
                f"Sitemap has an XML error: {error}",
                "Fix the XML syntax error. Use an XML validator to check the sitemap.",
                detail=error,
            ))

        # ── Sitemap too large ─────────────────────────────────────────────────
        if sitemap_data.url_count > SITEMAP_MAX_URLS:
            issues.append(analyzer.warning(
                sitemap_data.url, "sitemap_too_large",
                f"Sitemap contains {sitemap_data.url_count:,} URLs — over Google's limit of {SITEMAP_MAX_URLS:,}.",
                "Split the sitemap into multiple sitemaps and create a sitemap index file.",
                detail=f"{sitemap_data.url_count:,} URLs",
            ))

        # ── Per-URL checks ────────────────────────────────────────────────────
        sitemap_url_set = {u.rstrip("/") for u in sitemap_data.urls}

        for sitemap_url in sitemap_data.urls:
            norm = sitemap_url.rstrip("/")
            page = all_pages.get(sitemap_url) or all_pages.get(norm) or all_pages.get(norm + "/")

            if page is None:
                # URL in sitemap but not crawled (might be within limit)
                continue

            if page.status_code == 0:
                error_msg = page.crawl_error or "Unknown fetch error"
                issues.append(analyzer.critical(
                    sitemap_url, "sitemap_url_fetch_error",
                    f"Sitemap URL could not be fetched: {error_msg}",
                    "Check that the URL is accessible and the server is responding. Fix or remove it from the sitemap.",
                    detail=error_msg,
                ))
            elif page.status_code in range(400, 600):
                issues.append(analyzer.critical(
                    sitemap_url, "sitemap_url_error",
                    f"Sitemap URL returns HTTP {page.status_code}.",
                    "Fix or remove the broken URL from the sitemap. Update to the correct location.",
                    detail=f"HTTP {page.status_code}",
                ))
            elif page.redirect_chain:
                issues.append(analyzer.warning(
                    sitemap_url, "sitemap_url_redirect",
                    "Sitemap URL redirects to another location.",
                    "Update the sitemap to use the final destination URL, not the redirect source.",
                    detail=f"→ {page.final_url}",
                ))
            elif not page.is_indexable:
                issues.append(analyzer.warning(
                    sitemap_url, "sitemap_url_noindex",
                    "Sitemap includes a URL with noindex directive.",
                    "Remove noindex pages from the sitemap, or remove the noindex directive if the page should be indexed.",
                ))

        # ── Pages in sitemap not accessible ──────────────────────────────────

        # ── Crawled pages not in sitemap ──────────────────────────────────────
        crawled_not_in_sitemap = 0
        for url, page in all_pages.items():
            if not page.is_html or not page.is_indexable:
                continue
            if page.status_code not in range(200, 300):
                continue
            norm_url = url.rstrip("/")
            if norm_url not in sitemap_url_set and (norm_url + "/") not in sitemap_url_set:
                crawled_not_in_sitemap += 1

        if crawled_not_in_sitemap > 0 and sitemap_data.url_count > 0:
            issues.append(analyzer.info(
                sitemap_data.url, "pages_missing_from_sitemap",
                f"{crawled_not_in_sitemap} crawled pages are not listed in the sitemap.",
                "Add all important indexable pages to the sitemap to ensure complete crawl coverage.",
                detail=f"{crawled_not_in_sitemap} pages",
            ))

        return issues
