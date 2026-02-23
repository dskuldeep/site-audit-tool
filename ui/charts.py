"""
Plotly chart builders for the Site Audit dashboard.
All functions return plotly Figure objects.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from models import PageData, Issue, Severity
from scoring.scorer import score_color

# Consistent colour palette
_COLORS = {
    "critical": "#FF4B4B",
    "warning":  "#FFA500",
    "info":     "#4B9EFF",
}

_BG = "#1A1D27"
_PAPER = "#0E1117"
_GRID = "#2A2D3A"
_TEXT = "#FAFAFA"


def _base_layout(**kwargs) -> dict:
    return {
        "paper_bgcolor": _PAPER,
        "plot_bgcolor":  _BG,
        "font": {"color": _TEXT, "family": "sans-serif"},
        "margin": {"l": 20, "r": 20, "t": 40, "b": 20},
        **kwargs,
    }


# ── Health score gauge ─────────────────────────────────────────────────────────

def health_score_gauge(score: float) -> go.Figure:
    color = score_color(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        domain={"x": [0, 1], "y": [0, 1]},
        number={"font": {"size": 48, "color": color}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": _TEXT, "tickfont": {"color": _TEXT}},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": _BG,
            "borderwidth": 2,
            "bordercolor": _GRID,
            "steps": [
                {"range": [0, 50],  "color": "#3A1A1A"},
                {"range": [50, 75], "color": "#3A2E1A"},
                {"range": [75, 90], "color": "#2A3A1A"},
                {"range": [90, 100],"color": "#1A3A1A"},
            ],
            "threshold": {
                "line": {"color": color, "width": 4},
                "thickness": 0.8,
                "value": score,
            },
        },
    ))
    fig.update_layout(
        **_base_layout(height=260),
        title={"text": "Site Health Score", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
    )
    return fig


# ── Issues by category (horizontal bar, stacked by severity) ──────────────────

def issues_by_category_bar(issues: list[Issue]) -> go.Figure:
    # Build counts
    counts: dict[str, dict[str, int]] = {}
    for issue in issues:
        counts.setdefault(issue.category, {"critical": 0, "warning": 0, "info": 0})
        counts[issue.category][issue.severity] = counts[issue.category].get(issue.severity, 0) + 1

    if not counts:
        return _empty_chart("No issues found")

    cats = sorted(counts.keys(), key=lambda c: -(
        counts[c]["critical"] * 100 + counts[c]["warning"] * 10 + counts[c]["info"]
    ))

    fig = go.Figure()
    for sev in [Severity.CRITICAL, Severity.WARNING, Severity.INFO]:
        values = [counts[c].get(sev, 0) for c in cats]
        fig.add_trace(go.Bar(
            y=cats,
            x=values,
            name=sev.capitalize(),
            orientation="h",
            marker_color=_COLORS[sev],
            hovertemplate=f"<b>%{{y}}</b><br>{sev.capitalize()}: %{{x}}<extra></extra>",
        ))

    fig.update_layout(
        **_base_layout(height=max(300, len(cats) * 38 + 80)),
        title={"text": "Issues by Category", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
        barmode="stack",
        legend={"orientation": "h", "y": -0.15, "font": {"color": _TEXT}},
        xaxis={"title": "Issue Count", "gridcolor": _GRID, "color": _TEXT},
        yaxis={"gridcolor": _GRID, "color": _TEXT, "automargin": True},
    )
    return fig


# ── Issues by severity donut ───────────────────────────────────────────────────

def issues_by_severity_donut(issues: list[Issue]) -> go.Figure:
    counts = {s: 0 for s in Severity.ALL}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1

    labels = [s.capitalize() for s in Severity.ALL]
    values = [counts[s] for s in Severity.ALL]
    colors = [_COLORS[s] for s in Severity.ALL]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.6,
        marker={"colors": colors, "line": {"color": _BG, "width": 2}},
        hovertemplate="<b>%{label}</b>: %{value} issues<extra></extra>",
    ))
    total = sum(values)
    fig.update_layout(
        **_base_layout(height=260),
        title={"text": "Issues by Severity", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
        annotations=[{
            "text": f"<b>{total}</b><br>Total",
            "x": 0.5, "y": 0.5,
            "font_size": 18,
            "font_color": _TEXT,
            "showarrow": False,
        }],
        legend={"font": {"color": _TEXT}},
        showlegend=True,
    )
    return fig


# ── Response time distribution ─────────────────────────────────────────────────

def response_time_histogram(pages: dict[str, PageData]) -> go.Figure:
    times = [p.response_time_ms for p in pages.values() if p.response_time_ms > 0]
    if not times:
        return _empty_chart("No response time data")

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=times,
        nbinsx=30,
        marker_color="#6C63FF",
        hovertemplate="<b>%{x:.0f} ms</b><br>Count: %{y}<extra></extra>",
        name="Response Time",
    ))
    # Threshold lines
    fig.add_vline(x=2000, line_dash="dash", line_color="#FFA500",
                  annotation_text="2s threshold", annotation_font_color="#FFA500")
    fig.add_vline(x=4000, line_dash="dash", line_color="#FF4B4B",
                  annotation_text="4s critical", annotation_font_color="#FF4B4B")

    fig.update_layout(
        **_base_layout(height=260),
        title={"text": "Response Time Distribution", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
        xaxis={"title": "Response Time (ms)", "gridcolor": _GRID, "color": _TEXT},
        yaxis={"title": "Pages",              "gridcolor": _GRID, "color": _TEXT},
        showlegend=False,
    )
    return fig


# ── Page size distribution ─────────────────────────────────────────────────────

def page_size_histogram(pages: dict[str, PageData]) -> go.Figure:
    sizes_kb = [p.page_size_bytes / 1024 for p in pages.values() if p.page_size_bytes > 0]
    if not sizes_kb:
        return _empty_chart("No page size data")

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=sizes_kb,
        nbinsx=30,
        marker_color="#00C9A7",
        name="Page Size",
        hovertemplate="<b>%{x:.0f} KB</b><br>Count: %{y}<extra></extra>",
    ))
    fig.add_vline(x=2048, line_dash="dash", line_color="#FFA500",
                  annotation_text="2 MB threshold", annotation_font_color="#FFA500")

    fig.update_layout(
        **_base_layout(height=260),
        title={"text": "Page Size Distribution", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
        xaxis={"title": "Page Size (KB)", "gridcolor": _GRID, "color": _TEXT},
        yaxis={"title": "Pages",          "gridcolor": _GRID, "color": _TEXT},
        showlegend=False,
    )
    return fig


# ── Status code treemap ────────────────────────────────────────────────────────

def status_code_bar(pages: dict[str, PageData]) -> go.Figure:
    counts: dict[str, int] = {}
    for page in pages.values():
        code = page.status_code or 0
        if code == 0:
            label = "Error/Timeout"
        else:
            label = f"{code // 100}xx ({code})" if False else str(code)
            label = str(code)
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return _empty_chart("No status code data")

    # Sort by code
    sorted_items = sorted(counts.items(), key=lambda x: x[0])
    labels, values = zip(*sorted_items)

    def _code_color(label: str) -> str:
        if label.startswith("2"):
            return "#00C851"
        elif label.startswith("3"):
            return "#4B9EFF"
        elif label.startswith("4"):
            return "#FFA500"
        elif label.startswith("5"):
            return "#FF4B4B"
        return "#888888"

    colors = [_code_color(l) for l in labels]

    fig = go.Figure(go.Bar(
        x=list(labels),
        y=list(values),
        marker_color=colors,
        hovertemplate="<b>HTTP %{x}</b><br>Pages: %{y}<extra></extra>",
    ))
    fig.update_layout(
        **_base_layout(height=260),
        title={"text": "Status Code Breakdown", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
        xaxis={"title": "HTTP Status Code", "gridcolor": _GRID, "color": _TEXT},
        yaxis={"title": "Pages",            "gridcolor": _GRID, "color": _TEXT},
        showlegend=False,
    )
    return fig


# ── Crawl depth bar ────────────────────────────────────────────────────────────

def crawl_depth_bar(pages: dict[str, PageData]) -> go.Figure:
    counts: dict[int, int] = {}
    for page in pages.values():
        counts[page.depth] = counts.get(page.depth, 0) + 1

    if not counts:
        return _empty_chart("No depth data")

    depths = sorted(counts.keys())
    values = [counts[d] for d in depths]

    fig = go.Figure(go.Bar(
        x=[str(d) for d in depths],
        y=values,
        marker_color="#6C63FF",
        hovertemplate="<b>Depth %{x}</b><br>Pages: %{y}<extra></extra>",
    ))
    fig.update_layout(
        **_base_layout(height=240),
        title={"text": "Crawl Depth", "x": 0.5, "xanchor": "center",
               "font": {"size": 14, "color": _TEXT}},
        xaxis={"title": "Depth (hops from root)", "gridcolor": _GRID, "color": _TEXT},
        yaxis={"title": "Pages",                  "gridcolor": _GRID, "color": _TEXT},
        showlegend=False,
    )
    return fig


# ── Helper ─────────────────────────────────────────────────────────────────────

def _empty_chart(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, showarrow=False, font={"color": _TEXT, "size": 14})
    fig.update_layout(**_base_layout(height=260))
    return fig
