"""
Security analyzer: HTTPS, mixed content, security response headers.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer
from config import EXPECTED_SECURITY_HEADERS

import re


class SecurityAnalyzer(BaseAnalyzer):
    category = "Security"

    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        if page.status_code == 0:
            return []

        issues: list[Issue] = []
        url = page.url

        # ── SSL / HTTPS ────────────────────────────────────────────────────────
        if page.crawl_error and "SSL" in page.crawl_error:
            issues.append(self.critical(
                url, "ssl_error",
                "SSL certificate error detected when accessing this page.",
                "Renew or fix the SSL certificate. All pages must be served over valid HTTPS.",
                detail=page.crawl_error,
            ))

        final = page.final_url or url
        if final.startswith("http://"):
            issues.append(self.critical(
                url, "not_https",
                "Page is served over HTTP, not HTTPS.",
                "Configure your server to serve all pages over HTTPS and redirect HTTP → HTTPS.",
            ))

        # ── Mixed content ──────────────────────────────────────────────────────
        if final.startswith("https://") and page.is_html:
            mixed = _find_mixed_content(page)
            if mixed:
                issues.append(self.critical(
                    url, "mixed_content",
                    f"Page loads {len(mixed)} resource(s) over HTTP on an HTTPS page.",
                    "Update all resource URLs to use HTTPS to prevent mixed content warnings.",
                    detail="; ".join(mixed[:5]),
                ))

        # ── Security headers ───────────────────────────────────────────────────
        lower_headers = {k.lower(): v for k, v in page.response_headers.items()}

        if "strict-transport-security" not in lower_headers and final.startswith("https://"):
            issues.append(self.warning(
                url, "missing_hsts",
                "Missing Strict-Transport-Security (HSTS) header.",
                "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' to prevent protocol downgrade attacks.",
            ))

        if "x-frame-options" not in lower_headers and "content-security-policy" not in lower_headers:
            issues.append(self.warning(
                url, "missing_x_frame_options",
                "Missing X-Frame-Options header (clickjacking protection).",
                "Add 'X-Frame-Options: SAMEORIGIN' or use Content-Security-Policy frame-ancestors directive.",
            ))

        if "x-content-type-options" not in lower_headers:
            issues.append(self.info(
                url, "missing_x_content_type_options",
                "Missing X-Content-Type-Options header.",
                "Add 'X-Content-Type-Options: nosniff' to prevent MIME-type sniffing attacks.",
            ))

        if "content-security-policy" not in lower_headers:
            issues.append(self.info(
                url, "missing_csp",
                "Missing Content-Security-Policy (CSP) header.",
                "Implement a CSP to reduce XSS risk by restricting which resources can be loaded.",
            ))

        if "referrer-policy" not in lower_headers:
            issues.append(self.info(
                url, "missing_referrer_policy",
                "Missing Referrer-Policy header.",
                "Add 'Referrer-Policy: strict-origin-when-cross-origin' to control referrer information.",
            ))

        return issues


def _find_mixed_content(page: PageData) -> list[str]:
    """Return HTTP resource URLs found on an HTTPS page."""
    mixed: list[str] = []

    for img in page.images:
        if img.src.startswith("http://"):
            mixed.append(img.src)

    for script in page.scripts:
        if script.src and script.src.startswith("http://"):
            mixed.append(script.src)

    for css in page.stylesheets:
        if css.startswith("http://"):
            mixed.append(css)

    return mixed
