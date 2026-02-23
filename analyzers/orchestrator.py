"""
Runs all analyzers over the crawl result and populates AuditResult.issues.
"""
from __future__ import annotations

from typing import Callable, Optional

from models import AuditConfig, AuditResult, Issue, PageData
from scoring.scorer import compute_health_score

from analyzers.meta import MetaAnalyzer, DuplicateMetaAnalyzer
from analyzers.content import ContentAnalyzer, DuplicateContentAnalyzer
from analyzers.links import LinkAnalyzer, OrphanPageAnalyzer
from analyzers.images import ImageAnalyzer
from analyzers.technical import TechnicalSEOAnalyzer
from analyzers.performance import PerformanceAnalyzer
from analyzers.security import SecurityAnalyzer
from analyzers.http_issues import HTTPIssuesAnalyzer
from analyzers.sitemap_analyzer import SitemapAnalyzer
from analyzers.robots_analyzer import RobotsAnalyzer


# Per-page analyzers (run for each crawled page)
_PER_PAGE_ANALYZERS = [
    MetaAnalyzer(),
    ContentAnalyzer(),
    LinkAnalyzer(),
    ImageAnalyzer(),
    TechnicalSEOAnalyzer(),
    PerformanceAnalyzer(),
    SecurityAnalyzer(),
    HTTPIssuesAnalyzer(),
]


def run_all_analyzers(
    result: AuditResult,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> AuditResult:
    """
    Run all analyzers over result.pages and populate result.issues.
    Returns the same AuditResult with issues filled in.
    """
    all_pages = result.pages
    config = result.config
    issues: list[Issue] = []

    total = len(all_pages)
    _emit(progress_callback, f"Analysing {total} pages…", 0)

    # ── Per-page analysis ──────────────────────────────────────────────────────
    for idx, (url, page) in enumerate(all_pages.items()):
        for analyzer in _PER_PAGE_ANALYZERS:
            try:
                found = analyzer.analyze(page, all_pages, config)
                issues.extend(found)
            except Exception as exc:
                # Never let one analyzer crash the whole audit
                pass

        if idx % 20 == 0:
            pct = int(idx / max(total, 1) * 70)
            _emit(progress_callback, f"Analysing pages… {idx}/{total}", pct)

    _emit(progress_callback, "Running cross-page checks…", 72)

    # ── Cross-page batch checks ────────────────────────────────────────────────
    try:
        dup_meta = DuplicateMetaAnalyzer.run_duplicate_checks(all_pages, config)
        issues.extend(dup_meta)
    except Exception:
        pass

    try:
        dup_content = DuplicateContentAnalyzer.run_duplicate_checks(all_pages, config)
        issues.extend(dup_content)
    except Exception:
        pass

    sitemap_urls: set[str] = set()
    if result.sitemap_data:
        sitemap_urls = set(result.sitemap_data.urls)

    try:
        orphan_issues = OrphanPageAnalyzer.run_orphan_checks(all_pages, sitemap_urls, config)
        issues.extend(orphan_issues)
    except Exception:
        pass

    _emit(progress_callback, "Analysing sitemap…", 85)

    try:
        if result.sitemap_data:
            sitemap_issues = SitemapAnalyzer.run_sitemap_checks(result.sitemap_data, all_pages, config)
            issues.extend(sitemap_issues)
    except Exception:
        pass

    _emit(progress_callback, "Analysing robots.txt…", 90)

    try:
        if result.robots_data:
            robots_issues = RobotsAnalyzer.run_robots_checks(result.robots_data, all_pages, config)
            issues.extend(robots_issues)
    except Exception:
        pass

    _emit(progress_callback, "Scoring…", 95)

    result.issues = issues
    total_pages = sum(1 for p in all_pages.values() if p.is_html and p.status_code in range(200, 300))
    result.health_score, result.category_scores = compute_health_score(issues, total_pages=max(total_pages, 1))

    _emit(progress_callback, "Analysis complete.", 100)
    return result


def _emit(callback, message: str, pct: int) -> None:
    if callback:
        try:
            callback({"message": message, "pct": pct})
        except Exception:
            pass
