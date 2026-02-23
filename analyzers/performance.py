"""
Performance analyzer: response time, page size, render-blocking scripts, lazy loading.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer
from config import (
    LARGE_INLINE_SCRIPT_BYTES,
    LARGE_PAGE_SIZE_BYTES,
    SLOW_RESPONSE_TIME_MS,
    VERY_SLOW_RESPONSE_TIME_MS,
)


class PerformanceAnalyzer(BaseAnalyzer):
    category = "Performance"

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

        # ── Response time ─────────────────────────────────────────────────────
        rt = page.response_time_ms
        if rt >= VERY_SLOW_RESPONSE_TIME_MS:
            issues.append(self.critical(
                url, "very_slow_response",
                f"Page TTFB is {rt:.0f} ms — critically slow (>{VERY_SLOW_RESPONSE_TIME_MS} ms).",
                "Investigate server performance: caching, database queries, CDN, server location.",
                detail=f"{rt:.0f} ms",
            ))
        elif rt >= SLOW_RESPONSE_TIME_MS:
            issues.append(self.warning(
                url, "slow_response",
                f"Page TTFB is {rt:.0f} ms — above the {SLOW_RESPONSE_TIME_MS} ms threshold.",
                "Optimize server response time with caching, CDN, and efficient backend queries.",
                detail=f"{rt:.0f} ms",
            ))

        # ── Page size ─────────────────────────────────────────────────────────
        if page.page_size_bytes > LARGE_PAGE_SIZE_BYTES:
            size_kb = page.page_size_bytes // 1024
            issues.append(self.warning(
                url, "large_page_size",
                f"HTML page size is {size_kb} KB — above the recommended {LARGE_PAGE_SIZE_BYTES // 1024} KB limit.",
                "Minify HTML, remove unnecessary inline scripts/styles, and lazy-load non-critical content.",
                detail=f"{size_kb} KB",
            ))

        if not page.is_html:
            return issues

        # ── Render-blocking scripts ────────────────────────────────────────────
        blocking_scripts = [
            s for s in page.scripts
            if not s.is_inline and not s.has_async and not s.has_defer and s.in_head and s.src
        ]
        if blocking_scripts:
            issues.append(self.warning(
                url, "render_blocking_scripts",
                f"{len(blocking_scripts)} render-blocking <script> tag(s) in <head> are blocking page render.",
                "Add async or defer attribute to non-critical scripts, or move them to end of <body>.",
                detail="; ".join(s.src.split("/")[-1] for s in blocking_scripts[:5]),
                element="<script> in <head>",
            ))

        # ── Scripts without async/defer in body ───────────────────────────────
        body_scripts_no_attr = [
            s for s in page.scripts
            if not s.is_inline and not s.has_async and not s.has_defer and not s.in_head and s.src
        ]
        if body_scripts_no_attr:
            issues.append(self.info(
                url, "scripts_without_async_defer",
                f"{len(body_scripts_no_attr)} <script> tag(s) in <body> lack async or defer.",
                "Add async or defer to <script> tags to improve page load performance.",
                detail="; ".join(s.src.split("/")[-1] for s in body_scripts_no_attr[:5]),
                element="<script>",
            ))

        # ── Large inline scripts ───────────────────────────────────────────────
        large_inline = [s for s in page.scripts if s.is_inline and s.inline_size_bytes > LARGE_INLINE_SCRIPT_BYTES]
        if large_inline:
            total_inline_kb = sum(s.inline_size_bytes for s in large_inline) // 1024
            issues.append(self.info(
                url, "large_inline_scripts",
                f"Page contains {len(large_inline)} large inline script block(s) totalling ~{total_inline_kb} KB.",
                "Move large inline scripts to external files for better caching and parsing performance.",
                detail=f"~{total_inline_kb} KB inline JavaScript",
            ))

        # ── No lazy loading on image-heavy page ───────────────────────────────
        # (Covered in ImageAnalyzer — referenced here for performance context)

        # ── Many external script resources ────────────────────────────────────
        external_scripts = [s for s in page.scripts if not s.is_inline and s.src and not _is_same_domain(s.src, url)]
        if len(external_scripts) > 15:
            issues.append(self.warning(
                url, "too_many_external_scripts",
                f"Page loads {len(external_scripts)} external scripts, increasing HTTP request overhead.",
                "Bundle scripts where possible, remove unused third-party scripts, and defer non-critical ones.",
                detail=f"{len(external_scripts)} external scripts",
            ))

        return issues


def _is_same_domain(script_url: str, page_url: str) -> bool:
    from urllib.parse import urlparse
    try:
        return urlparse(script_url).netloc == urlparse(page_url).netloc
    except Exception:
        return False
