"""
Link analyzer: broken internal/external links, redirect chains, orphan pages, nofollow issues.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer
from config import MAX_REDIRECT_CHAIN_LENGTH


class LinkAnalyzer(BaseAnalyzer):
    category = "Links"

    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        if not page.is_html:
            return []

        issues: list[Issue] = []
        url = page.url

        # ── Internal links ────────────────────────────────────────────────────
        for link in page.internal_links:
            target = all_pages.get(link.url)
            if target is None:
                continue  # not crawled — skip

            # Broken internal link
            if target.status_code in range(400, 600) or target.status_code == 0:
                severity = "critical" if target.status_code in range(400, 500) else "critical"
                issues.append(self._issue(
                    url, "broken_internal_link", "critical",
                    f"Internal link points to a page returning HTTP {target.status_code}.",
                    "Fix or remove the broken link. If the target page has moved, update the link or add a redirect.",
                    detail=f"→ {link.url} [{target.status_code}]",
                    affected_element=f'<a href="{link.url}">',
                ))

            # Redirect chain on internal link
            elif target.redirect_chain:
                chain_len = len(target.redirect_chain)
                if chain_len >= MAX_REDIRECT_CHAIN_LENGTH:
                    issues.append(self.warning(
                        url, "long_redirect_chain",
                        f"Internal link goes through a redirect chain of {chain_len} hops.",
                        "Update the link to point directly to the final destination URL.",
                        detail=f"Chain: {' → '.join(target.redirect_chain[:5])} → {target.final_url}",
                        element=f'<a href="{link.url}">',
                    ))
                elif chain_len == 1:
                    issues.append(self.info(
                        url, "redirect_on_internal_link",
                        "Internal link points to a URL that redirects.",
                        "Update the link to point directly to the final destination URL to save a redirect hop.",
                        detail=f"{link.url} → {target.final_url}",
                    ))

            # Redirect loop
            if target.crawl_error and "Redirect loop" in (target.crawl_error or ""):
                issues.append(self.critical(
                    url, "redirect_loop",
                    "Internal link leads to a redirect loop.",
                    "Fix the server-side redirect configuration to eliminate the loop.",
                    detail=link.url,
                ))

            # Nofollow on internal link
            if link.nofollow:
                issues.append(self.info(
                    url, "nofollow_internal_link",
                    "Internal link has rel='nofollow', which wastes internal link equity.",
                    "Remove nofollow from internal links unless intentional (e.g. login/register pages).",
                    detail=f"→ {link.url}",
                    element=f'<a rel="nofollow" href="{link.url}">',
                ))

            # HTTP link on HTTPS page
            if url.startswith("https://") and link.url.startswith("http://"):
                issues.append(self.warning(
                    url, "http_internal_link",
                    "Internal link uses HTTP on an HTTPS page.",
                    "Update the internal link to use HTTPS.",
                    detail=link.url,
                ))

        # ── External links ────────────────────────────────────────────────────
        for link in page.external_links:
            if link.is_broken:
                issues.append(self.warning(
                    url, "broken_external_link",
                    f"External link points to a page returning HTTP {link.status_code or 'Error'}.",
                    "Remove or update the broken external link.",
                    detail=f"→ {link.url} [{link.status_code}]",
                    element=f'<a href="{link.url}">',
                ))

            if link.redirect_chain and len(link.redirect_chain) >= MAX_REDIRECT_CHAIN_LENGTH:
                issues.append(self.info(
                    url, "external_redirect_chain",
                    f"External link goes through {len(link.redirect_chain)} redirect hops.",
                    "Consider updating the link to point to the final destination.",
                    detail=f"→ {link.url}",
                ))

        return issues


class OrphanPageAnalyzer(BaseAnalyzer):
    """
    Detect orphan pages: crawled pages that have no internal links pointing to them
    and are also not in the sitemap.
    Run as a post-crawl batch check.
    """
    category = "Links"

    def analyze(self, page, all_pages, config):
        return []

    @staticmethod
    def run_orphan_checks(
        all_pages: dict[str, PageData],
        sitemap_urls: set[str],
        config: AuditConfig,
    ) -> list[Issue]:
        analyzer = OrphanPageAnalyzer()
        issues: list[Issue] = []

        # Build reverse link index: url -> set of pages linking to it
        linked_to: set[str] = set()
        for page in all_pages.values():
            for link in page.internal_links:
                linked_to.add(link.url)

        start_url = config.start_url.rstrip("/")

        for url, page in all_pages.items():
            if not page.is_html or not page.is_indexable:
                continue
            if page.status_code not in range(200, 300):
                continue
            if url.rstrip("/") == start_url:
                continue  # homepage is never an orphan

            in_sitemap = url in sitemap_urls or url.rstrip("/") in {s.rstrip("/") for s in sitemap_urls}
            has_internal_links = url in linked_to or url.rstrip("/") in linked_to

            if not has_internal_links and not in_sitemap:
                issues.append(analyzer.warning(
                    url, "orphan_page",
                    "Page has no internal links pointing to it and is not in the sitemap.",
                    "Add internal links to this page from relevant content or include it in the sitemap.",
                ))
            elif not has_internal_links and in_sitemap:
                issues.append(analyzer.info(
                    url, "no_internal_links",
                    "Page is in the sitemap but no internal links point to it.",
                    "Add contextual internal links to this page to distribute link equity and improve crawlability.",
                ))

        return issues
