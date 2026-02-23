"""
HTTP issues analyzer: status codes, redirect types, fetch errors.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer


class HTTPIssuesAnalyzer(BaseAnalyzer):
    category = "HTTP Issues"

    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        issues: list[Issue] = []
        url = page.url

        # ── Fetch errors ──────────────────────────────────────────────────────
        if page.crawl_error and page.status_code == 0:
            if "Redirect loop" in page.crawl_error:
                issues.append(self.critical(
                    url, "redirect_loop",
                    "Page is caught in a redirect loop.",
                    "Fix the server-side redirect configuration to eliminate circular redirects.",
                    detail=page.crawl_error,
                ))
            elif "SSL" in page.crawl_error:
                pass  # handled by SecurityAnalyzer
            elif "timed out" in page.crawl_error.lower():
                issues.append(self.critical(
                    url, "page_timeout",
                    "Page request timed out — server did not respond in time.",
                    "Investigate server performance, slow queries, or network issues.",
                    detail=page.crawl_error,
                ))
            elif "robots" in page.crawl_error.lower():
                issues.append(self.info(
                    url, "blocked_by_robots",
                    "Page is blocked by robots.txt and was not crawled.",
                    "Review your robots.txt rules. If this page should be indexed, allow it.",
                    detail=page.crawl_error,
                ))
            else:
                issues.append(self.critical(
                    url, "page_fetch_error",
                    f"Page could not be fetched: {page.crawl_error}",
                    "Check that the URL is accessible and the server is responding correctly.",
                    detail=page.crawl_error,
                ))
            return issues

        code = page.status_code

        # ── 4xx errors ────────────────────────────────────────────────────────
        if code == 404:
            issues.append(self.critical(
                url, "page_404",
                "Page returns HTTP 404 Not Found.",
                "Fix the broken page with proper content, redirect it to a relevant live page, or remove inbound links.",
            ))
        elif code == 403:
            issues.append(self.critical(
                url, "page_403",
                "Page returns HTTP 403 Forbidden.",
                "Check server access permissions. If this page should be public, fix the access control.",
            ))
        elif code == 410:
            issues.append(self.warning(
                url, "page_410",
                "Page returns HTTP 410 Gone — server explicitly says the resource no longer exists.",
                "If gone permanently, keep the 410. Update or remove any internal links to this URL.",
            ))
        elif code in range(400, 500) and code not in (301, 302, 303, 307, 308):
            issues.append(self.critical(
                url, f"page_{code}",
                f"Page returns HTTP {code} client error.",
                f"Investigate and resolve the HTTP {code} error. Remove or redirect any links to this page.",
                detail=f"HTTP {code}",
            ))

        # ── 5xx errors ────────────────────────────────────────────────────────
        elif code == 500:
            issues.append(self.critical(
                url, "page_500",
                "Page returns HTTP 500 Internal Server Error.",
                "Fix the server-side error. Check application logs for the root cause.",
            ))
        elif code == 503:
            issues.append(self.critical(
                url, "page_503",
                "Page returns HTTP 503 Service Unavailable.",
                "Investigate server availability. If maintenance, use Retry-After header.",
            ))
        elif code in range(500, 600):
            issues.append(self.critical(
                url, f"page_{code}",
                f"Page returns HTTP {code} server error.",
                "Fix the server-side error. Check application and server logs.",
                detail=f"HTTP {code}",
            ))

        # ── Redirect type analysis ────────────────────────────────────────────
        elif code in (301, 302, 303, 307, 308):
            if page.redirect_chain:
                chain_len = len(page.redirect_chain)
                if chain_len > 1:
                    issues.append(self.warning(
                        url, "redirect_chain",
                        f"URL goes through a redirect chain of {chain_len} hops.",
                        "Shorten redirect chains to a single 301 redirect to the final destination.",
                        detail=f"Chain: {' → '.join(page.redirect_chain[:4])} → {page.final_url}",
                    ))
            # 302 used where 301 should be (for permanent moves)
            if code == 302 and page.final_url:
                issues.append(self.info(
                    url, "temporary_redirect",
                    "Page uses a 302 temporary redirect. If this move is permanent, use a 301.",
                    "Use 301 for permanent redirects to pass full link equity to the destination.",
                    detail=f"302 → {page.final_url}",
                ))

        return issues
