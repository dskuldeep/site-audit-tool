"""
Global configuration constants for the Site Audit Tool.
All tunable thresholds live here.
"""

# ── Meta thresholds ───────────────────────────────────────────────────────────
TITLE_MIN_CHARS = 30
TITLE_MAX_CHARS = 60
DESCRIPTION_MIN_CHARS = 70
DESCRIPTION_MAX_CHARS = 160

# ── Content thresholds ────────────────────────────────────────────────────────
THIN_CONTENT_WORD_COUNT = 300
H1_MAX_LENGTH = 70
DUPLICATE_CONTENT_SIMILARITY_THRESHOLD = 0.85  # difflib SequenceMatcher ratio

# ── Performance thresholds ────────────────────────────────────────────────────
SLOW_RESPONSE_TIME_MS = 2000
VERY_SLOW_RESPONSE_TIME_MS = 4000
LARGE_PAGE_SIZE_BYTES = 2_097_152        # 2 MB
LARGE_INLINE_SCRIPT_BYTES = 10_240       # 10 KB
LARGE_IMAGE_SIZE_BYTES = 102_400         # 100 KB

# ── Link thresholds ───────────────────────────────────────────────────────────
MAX_REDIRECT_CHAIN_LENGTH = 3

# ── Sitemap thresholds ────────────────────────────────────────────────────────
SITEMAP_MAX_URLS = 50_000

# ── Crawler defaults ──────────────────────────────────────────────────────────
DEFAULT_MAX_PAGES = 10000
DEFAULT_MAX_WORKERS = 10
DEFAULT_REQUEST_TIMEOUT = 15            # seconds
DEFAULT_USER_AGENT = (
    "SiteAuditBot/1.0 (+https://github.com/site-audit-tool)"
)

# Official bot user-agent strings for the sidebar dropdown
USER_AGENT_PRESETS = {
    "Site Audit Bot (default)": "SiteAuditBot/1.0 (+https://github.com/site-audit-tool)",
    "Googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "GPTBot (OpenAI)": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.0; +https://openai.com/gptbot",
}

# ── Scoring weights (must conceptually sum to 100) ────────────────────────────
SCORING_WEIGHTS: dict[str, float] = {
    "HTTP Issues":    18,
    "Links":          15,
    "Meta":           15,
    "Technical SEO":  14,
    "Content":        12,
    "Performance":    10,
    "Security":        8,
    "Images":          5,
    "Sitemap":         2,
    "Robots":          1,
}

# Deduction per individual issue instance
SEVERITY_DEDUCTIONS: dict[str, float] = {
    "critical": 5.0,
    "warning":  2.0,
    "info":     0.3,
}

# ── Security headers expected ─────────────────────────────────────────────────
EXPECTED_SECURITY_HEADERS = [
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "content-security-policy",
    "referrer-policy",
    "permissions-policy",
]
