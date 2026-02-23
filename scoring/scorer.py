"""
Health score calculator.

Scoring model:
- Issues are grouped by (category, issue_type) — one deduction per unique issue TYPE,
  not per instance. This prevents a single issue firing on 2000 pages from tanking the score.
- Each issue type's deduction is scaled by the proportion of affected pages (0.0–1.0),
  so a problem hitting 5% of pages costs far less than one hitting 100%.
- Deductions are capped at the category weight, then summed for the final score.
"""
from __future__ import annotations

from models import Issue, Severity
from config import SCORING_WEIGHTS  # SEVERITY_DEDUCTIONS no longer used

# Deduction per unique issue TYPE when it affects 100% of pages.
# Scales linearly down to 0 as fewer pages are affected.
_TYPE_WEIGHT = {
    Severity.CRITICAL: 12.0,
    Severity.WARNING:   4.0,
    Severity.INFO:      0.8,
}


def compute_health_score(
    issues: list[Issue],
    total_pages: int = 1,
) -> tuple[float, dict[str, float]]:
    """
    Returns (overall_score 0–100, category_scores dict).

    total_pages — number of HTML pages crawled; used to normalise per-page issues.
    """
    if not issues:
        return 100.0, {cat: float(w) for cat, w in SCORING_WEIGHTS.items()}

    n_pages = max(total_pages, 1)

    # Group by category → issue_type → list of issues
    by_cat: dict[str, dict[str, list[Issue]]] = {}
    for issue in issues:
        by_cat.setdefault(issue.category, {}).setdefault(issue.issue_type, []).append(issue)

    total = 100.0
    category_scores: dict[str, float] = {}

    for category, weight in SCORING_WEIGHTS.items():
        type_map = by_cat.get(category, {})
        cat_deduction = 0.0

        for issue_type, type_issues in type_map.items():
            severity = type_issues[0].severity
            base = _TYPE_WEIGHT.get(severity, 0.0)

            # Unique pages affected by this specific issue type
            affected_pages = len({i.url for i in type_issues})
            ratio = min(1.0, affected_pages / n_pages)

            cat_deduction += base * ratio

        capped = min(cat_deduction, weight)
        category_scores[category] = round(weight - capped, 2)
        total -= capped

    overall = max(0.0, min(100.0, total))
    return round(overall, 1), category_scores


def score_label(score: float) -> str:
    if score >= 90:
        return "Excellent"
    elif score >= 75:
        return "Good"
    elif score >= 50:
        return "Needs Work"
    else:
        return "Poor"


def score_color(score: float) -> str:
    if score >= 90:
        return "#00C851"
    elif score >= 75:
        return "#FFD700"
    elif score >= 50:
        return "#FF8800"
    else:
        return "#FF4444"
