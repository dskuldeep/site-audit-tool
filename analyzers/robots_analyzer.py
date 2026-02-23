"""
Robots.txt analyzer: validates robots.txt rules, detects blocking of important resources.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData, RobotsData
from analyzers.base import BaseAnalyzer


class RobotsAnalyzer(BaseAnalyzer):
    category = "Robots"

    def analyze(self, page, all_pages, config):
        return []

    @staticmethod
    def run_robots_checks(
        robots_data: RobotsData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        analyzer = RobotsAnalyzer()
        issues: list[Issue] = []

        if robots_data is None:
            return issues

        # ── Missing robots.txt ────────────────────────────────────────────────
        if not robots_data.exists:
            if robots_data.status_code == 404:
                issues.append(analyzer.warning(
                    robots_data.url, "robots_txt_not_found",
                    "robots.txt was not found (404). While not required, it is best practice to have one.",
                    "Create a /robots.txt file to control crawler access and declare your sitemap.",
                ))
            elif robots_data.status_code != 0:
                issues.append(analyzer.warning(
                    robots_data.url, "robots_txt_error",
                    f"robots.txt returned HTTP {robots_data.status_code}.",
                    "Ensure robots.txt is accessible at /robots.txt on the root domain.",
                    detail=f"HTTP {robots_data.status_code}",
                ))
            return issues

        # ── Parse errors ───────────────────────────────────────────────────────
        for error in robots_data.parse_errors:
            issues.append(analyzer.warning(
                robots_data.url, "robots_syntax_error",
                f"robots.txt has a syntax issue: {error}",
                "Fix the robots.txt syntax. Each directive must be on its own line as 'Field: value'.",
                detail=error,
            ))

        # ── Blocking everything ────────────────────────────────────────────────
        for rule in robots_data.disallow_rules:
            if rule["agent"] in ("*", config.user_agent.lower()):
                if rule["path"] == "/":
                    issues.append(analyzer.critical(
                        robots_data.url, "robots_blocks_all",
                        f"robots.txt has 'Disallow: /' for user-agent '{rule['agent']}' — the entire site is blocked from crawling.",
                        "Remove or correct the Disallow: / rule. This prevents all search engines from crawling the site.",
                        detail=f"User-agent: {rule['agent']}\nDisallow: /",
                    ))

        # ── Blocking CSS/JS/images ─────────────────────────────────────────────
        blocked_resource_patterns = [".css", ".js", "/css", "/js", "/assets", "/static", "/images", "/img"]
        for rule in robots_data.disallow_rules:
            path = rule["path"].lower()
            for pattern in blocked_resource_patterns:
                if pattern in path:
                    issues.append(analyzer.warning(
                        robots_data.url, "robots_blocks_resources",
                        f"robots.txt blocks access to '{rule['path']}' which may include CSS/JS/image resources needed for rendering.",
                        "Allow search engines to access CSS, JavaScript, and image files for proper page rendering.",
                        detail=f"User-agent: {rule['agent']}\nDisallow: {rule['path']}",
                    ))
                    break

        # ── Missing sitemap declaration ────────────────────────────────────────
        if not robots_data.sitemap_urls:
            issues.append(analyzer.info(
                robots_data.url, "robots_missing_sitemap",
                "robots.txt does not declare a Sitemap.",
                "Add 'Sitemap: https://yourdomain.com/sitemap.xml' to robots.txt to help search engines find your sitemap.",
            ))

        # ── Crawl delay ────────────────────────────────────────────────────────
        if robots_data.crawl_delay is not None and robots_data.crawl_delay > 10:
            issues.append(analyzer.warning(
                robots_data.url, "high_crawl_delay",
                f"robots.txt specifies a Crawl-delay of {robots_data.crawl_delay} seconds — this is very high.",
                "Reduce the crawl-delay to allow search engines to crawl your site more efficiently. Google ignores Crawl-delay.",
                detail=f"Crawl-delay: {robots_data.crawl_delay}",
            ))

        # ── Pages blocked that should be crawlable ────────────────────────────
        blocked_but_indexed = []
        for url, page in all_pages.items():
            if page.crawl_error and "robots" in (page.crawl_error or "").lower():
                if page.is_indexable:  # Would be indexable if not blocked
                    blocked_but_indexed.append(url)

        if blocked_but_indexed:
            issues.append(analyzer.warning(
                robots_data.url, "pages_blocked_by_robots",
                f"{len(blocked_but_indexed)} page(s) are blocked by robots.txt.",
                "Review robots.txt rules. If these pages should be indexed, update the rules to allow access.",
                detail=f"Example: {blocked_but_indexed[0]}",
            ))

        return issues
