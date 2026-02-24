"""
Core data models for the Site Audit Tool.
All modules import from here; nothing else is cross-imported at this level.

NOTE: `from __future__ import annotations` is intentionally omitted here.
Python 3.13.0 has a regression (bpo-121814) where that import causes a crash
in the dataclasses decorator when the module is not yet fully registered in
sys.modules. Python 3.9+ supports generic aliases (list[str], dict[str, Any])
natively, so the future import is unnecessary.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ── Severity ──────────────────────────────────────────────────────────────────
class Severity:
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"

    ALL = [CRITICAL, WARNING, INFO]

    COLORS = {
        CRITICAL: "#FF4B4B",
        WARNING:  "#FFA500",
        INFO:     "#4B9EFF",
    }

    ICONS = {
        CRITICAL: "🔴",
        WARNING:  "🟡",
        INFO:     "🔵",
    }


# ── Sub-structures ─────────────────────────────────────────────────────────────
@dataclass
class LinkData:
    url: str
    anchor_text: str = ""
    rel: str = ""
    nofollow: bool = False
    status_code: int = 0
    is_broken: bool = False
    redirect_chain: list[str] = field(default_factory=list)


@dataclass
class ImageData:
    src: str
    alt: str = ""
    title: str = ""
    width: Optional[str] = None
    height: Optional[str] = None
    loading: str = ""
    is_broken: bool = False
    status_code: int = 0
    size_bytes: int = 0


@dataclass
class ScriptData:
    src: str = ""
    is_inline: bool = False
    has_async: bool = False
    has_defer: bool = False
    in_head: bool = False
    inline_size_bytes: int = 0


@dataclass
class HreflangData:
    hreflang: str
    href: str


# ── Core page model ────────────────────────────────────────────────────────────
@dataclass
class PageData:
    url: str

    # HTTP response
    status_code: int = 0
    response_time_ms: float = 0.0
    content_type: str = ""
    page_size_bytes: int = 0
    redirect_chain: list[str] = field(default_factory=list)
    final_url: str = ""
    response_headers: dict[str, str] = field(default_factory=dict)
    crawl_error: Optional[str] = None
    is_html: bool = True

    # Raw HTML
    html: str = ""

    # Meta tags
    title: Optional[str] = None
    meta_description: Optional[str] = None
    meta_keywords: Optional[str] = None
    meta_robots: Optional[str] = None
    meta_viewport: Optional[str] = None

    # SEO
    canonical_url: Optional[str] = None
    hreflang_tags: list[HreflangData] = field(default_factory=list)
    schema_markup: list[dict] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    og_tags: dict[str, str] = field(default_factory=dict)
    twitter_tags: dict[str, str] = field(default_factory=dict)

    # Content
    h1_tags: list[str] = field(default_factory=list)
    h2_tags: list[str] = field(default_factory=list)
    h3_h6_tags: list[dict] = field(default_factory=list)  # [{level, text}]
    word_count: int = 0
    text_content: str = ""
    content_hash: str = ""

    # Links
    internal_links: list[LinkData] = field(default_factory=list)
    external_links: list[LinkData] = field(default_factory=list)

    # Resources
    images: list[ImageData] = field(default_factory=list)
    scripts: list[ScriptData] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)

    # Indexability
    is_indexable: bool = True
    x_robots_tag: Optional[str] = None

    # Crawl depth (hops from root)
    depth: int = 0


# ── Issue model ────────────────────────────────────────────────────────────────
@dataclass
class Issue:
    url: str
    category: str
    issue_type: str
    severity: str          # Severity.CRITICAL / WARNING / INFO
    description: str
    recommendation: str
    detail: str = ""       # specific value / context that triggered the issue
    affected_element: str = ""   # tag name or attribute


# ── Auxiliary data models ──────────────────────────────────────────────────────
@dataclass
class RobotsData:
    url: str
    exists: bool
    status_code: int = 0
    raw_text: str = ""
    sitemap_urls: list[str] = field(default_factory=list)
    disallow_rules: list[dict] = field(default_factory=list)  # [{agent, path}]
    allow_rules: list[dict] = field(default_factory=list)
    crawl_delay: Optional[float] = None
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class SitemapData:
    url: str
    exists: bool
    status_code: int = 0
    is_index: bool = False
    child_sitemaps: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    url_count: int = 0
    parse_errors: list[str] = field(default_factory=list)
    raw_xml: str = ""


# ── Audit configuration ────────────────────────────────────────────────────────
@dataclass
class AuditConfig:
    domain: str
    start_url: str
    sitemap_url: str = ""
    max_pages: int = 10000
    max_workers: int = 10
    request_timeout: int = 15
    user_agent: str = "SiteAuditBot/1.0"
    respect_robots: bool = True
    check_external_links: bool = True
    follow_subdomains: bool = False
    advanced_mode: bool = False


# ── Top-level audit result ─────────────────────────────────────────────────────
@dataclass
class AuditResult:
    config: AuditConfig
    pages: dict[str, PageData] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    health_score: float = 100.0
    category_scores: dict[str, float] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    sitemap_data: Optional[SitemapData] = None
    robots_data: Optional[RobotsData] = None
    crawl_stats: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    @property
    def issues_by_severity(self) -> dict[str, list[Issue]]:
        out: dict[str, list[Issue]] = {s: [] for s in Severity.ALL}
        for issue in self.issues:
            out.setdefault(issue.severity, []).append(issue)
        return out

    @property
    def issues_by_category(self) -> dict[str, list[Issue]]:
        out: dict[str, list[Issue]] = {}
        for issue in self.issues:
            out.setdefault(issue.category, []).append(issue)
        return out
