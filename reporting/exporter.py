"""
Converts AuditResult data to Pandas DataFrames and CSV bytes for export.
"""
from __future__ import annotations

import io
from typing import Optional

import pandas as pd

from models import AuditResult, Issue, PageData, Severity


# ── Issues DataFrame ───────────────────────────────────────────────────────────

def issues_to_df(issues: list[Issue]) -> pd.DataFrame:
    if not issues:
        return pd.DataFrame(columns=["Severity", "Category", "Issue", "URL", "Detail", "Recommendation"])

    rows = []
    for issue in issues:
        rows.append({
            "Severity":       issue.severity.upper(),
            "Category":       issue.category,
            "Issue":          _humanize(issue.issue_type),
            "URL":            issue.url,
            "Detail":         issue.detail or "",
            "Description":    issue.description,
            "Recommendation": issue.recommendation,
        })

    df = pd.DataFrame(rows)

    # Severity sort order
    severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    df["_sev_order"] = df["Severity"].str.lower().map(severity_order)
    df = df.sort_values(["_sev_order", "Category", "URL"]).drop(columns=["_sev_order"])
    df = df.reset_index(drop=True)
    return df


def pages_to_df(all_pages: dict[str, PageData]) -> pd.DataFrame:
    if not all_pages:
        return pd.DataFrame()

    rows = []
    for url, page in all_pages.items():
        rows.append({
            "URL":             url,
            "Status":          page.status_code,
            "Final URL":       page.final_url or url,
            "Title":           page.title or "",
            "Word Count":      page.word_count,
            "Response (ms)":   round(page.response_time_ms, 0),
            "Size (KB)":       round(page.page_size_bytes / 1024, 1) if page.page_size_bytes else 0,
            "Indexable":       page.is_indexable,
            "H1 Count":        len(page.h1_tags),
            "Internal Links":  len(page.internal_links),
            "External Links":  len(page.external_links),
            "Images":          len(page.images),
            "Canonical":       page.canonical_url or "",
            "Depth":           page.depth,
            "Redirects":       len(page.redirect_chain),
            "Error":           page.crawl_error or "",
        })

    return pd.DataFrame(rows).sort_values("URL").reset_index(drop=True)


# ── Summary table ──────────────────────────────────────────────────────────────

def issues_summary_df(issues: list[Issue]) -> pd.DataFrame:
    """Grouped count of issues by category and severity."""
    if not issues:
        return pd.DataFrame()

    rows: dict[tuple, int] = {}
    for issue in issues:
        key = (issue.category, issue.severity.capitalize())
        rows[key] = rows.get(key, 0) + 1

    data = [{"Category": k[0], "Severity": k[1], "Count": v} for k, v in rows.items()]
    df = pd.DataFrame(data)
    severity_order = {"Critical": 0, "Warning": 1, "Info": 2}
    df["_order"] = df["Severity"].map(severity_order)
    df = df.sort_values(["_order", "Category"]).drop(columns=["_order"]).reset_index(drop=True)
    return df


# ── CSV export ─────────────────────────────────────────────────────────────────

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _humanize(snake: str) -> str:
    """Convert snake_case to Title Case for display."""
    return snake.replace("_", " ").title()
