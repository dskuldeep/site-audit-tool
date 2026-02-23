"""
Site Audit Tool — Streamlit Application
A comprehensive technical SEO audit tool.
"""
from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from models import AuditConfig, AuditResult, Issue, PageData, Severity
from crawler.crawler import crawl
from analyzers.orchestrator import run_all_analyzers
from reporting.exporter import issues_to_df, pages_to_df, to_csv_bytes, issues_summary_df
from scoring.scorer import score_label, score_color
from ui.charts import (
    health_score_gauge,
    issues_by_category_bar,
    issues_by_severity_donut,
    response_time_histogram,
    page_size_histogram,
    status_code_bar,
    crawl_depth_bar,
)
from config import DEFAULT_MAX_PAGES, DEFAULT_MAX_WORKERS, DEFAULT_REQUEST_TIMEOUT, DEFAULT_USER_AGENT, USER_AGENT_PRESETS

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Site Audit Tool",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Hide default streamlit header padding */
.block-container { padding-top: 1rem; }

/* Metric cards */
.metric-card {
    background: #1A1D27;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.5rem;
    border-left: 4px solid;
}
.metric-card.critical { border-color: #FF4B4B; }
.metric-card.warning  { border-color: #FFA500; }
.metric-card.info     { border-color: #4B9EFF; }
.metric-card.success  { border-color: #00C851; }
.metric-card.neutral  { border-color: #6C63FF; }

.metric-val  { font-size: 2rem; font-weight: 700; margin: 0; }
.metric-lbl  { font-size: 0.8rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }

/* Severity pills */
.pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.pill.critical { background: #FF4B4B22; color: #FF4B4B; border: 1px solid #FF4B4B55; }
.pill.warning  { background: #FFA50022; color: #FFA500; border: 1px solid #FFA50055; }
.pill.info     { background: #4B9EFF22; color: #4B9EFF; border: 1px solid #4B9EFF55; }

/* Issue table alternating rows */
.issues-table tr:nth-child(even) { background: #1A1D27; }

/* Hide plotly modebar */
.modebar { display: none !important; }

/* Sidebar */
.sidebar-logo { font-size: 1.5rem; font-weight: 800; color: #6C63FF; margin-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)


# ── State helpers ──────────────────────────────────────────────────────────────

def _clear_results():
    for key in ["audit_result", "audit_running"]:
        st.session_state.pop(key, None)


def _has_result() -> bool:
    return "audit_result" in st.session_state and st.session_state.audit_result is not None


# ── Sidebar ────────────────────────────────────────────────────────────────────

def render_sidebar() -> AuditConfig | None:
    with st.sidebar:
        st.markdown('<div class="sidebar-logo">🔍 Site Audit</div>', unsafe_allow_html=True)
        st.caption("Technical SEO Audit Tool")
        st.divider()

        st.subheader("Target")
        domain = st.text_input(
            "Domain URL",
            placeholder="https://example.com",
            help="Full URL including https://",
        )
        sitemap_url = st.text_input(
            "Sitemap URL (optional)",
            placeholder="https://example.com/sitemap.xml",
            help="Leave blank to auto-discover /sitemap.xml",
        )

        st.subheader("Crawl Settings")
        max_pages = st.slider("Max pages to crawl", 50, 10000, DEFAULT_MAX_PAGES, 50)
        max_workers = st.slider("Concurrent workers", 1, 20, DEFAULT_MAX_WORKERS, 1)
        timeout = st.slider("Request timeout (s)", 5, 60, DEFAULT_REQUEST_TIMEOUT, 5)
        respect_robots = st.toggle("Respect robots.txt", value=True)
        check_external = st.toggle("Check external links", value=True)

        st.subheader("Advanced")
        ua_label = st.selectbox(
            "Crawl as",
            options=list(USER_AGENT_PRESETS.keys()),
            index=0,
        )
        user_agent = USER_AGENT_PRESETS[ua_label]
        st.caption(f"`{user_agent}`")

        st.divider()

        if _has_result():
            if st.button("🔄 New Audit", type="primary", use_container_width=True):
                _clear_results()
                st.rerun()
            st.divider()

        start = st.button("Start Audit", type="primary", use_container_width=True)

        if not _has_result():
            st.divider()
            st.caption("Enter a domain URL and click **Start Audit** to begin a full technical SEO scan.")

    if start and domain:
        # Normalize domain
        if not domain.startswith("http"):
            domain = "https://" + domain

        parsed = urlparse(domain)
        clean_domain = parsed.netloc or parsed.path

        return AuditConfig(
            domain=clean_domain,
            start_url=domain.rstrip("/"),
            sitemap_url=sitemap_url.strip() if sitemap_url else "",
            max_pages=max_pages,
            max_workers=max_workers,
            request_timeout=timeout,
            user_agent=user_agent,
            respect_robots=respect_robots,
            check_external_links=check_external,
        )

    return None


# ── Run audit ──────────────────────────────────────────────────────────────────

def run_audit(config: AuditConfig) -> None:
    progress_messages: list[str] = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    def on_progress(update: dict):
        pct = update.get("pct", 0)
        msg = update.get("message", "")
        progress_bar.progress(min(pct, 100))
        status_text.markdown(f"**{msg}**")

    with st.status("Running audit…", expanded=True) as status_widget:
        st.write(f"Starting crawl of **{config.start_url}**…")

        try:
            # Phase 1: Crawl
            result = crawl(config, progress_callback=on_progress)
            st.write(f"Crawled **{len(result.pages)}** pages.")

            # Phase 2: Analyse
            st.write("Running technical SEO analysis…")
            result = run_all_analyzers(result, progress_callback=on_progress)
            st.write(f"Found **{len(result.issues)}** issues.")

        except Exception as exc:
            status_widget.update(label="Audit failed", state="error")
            st.error(f"Audit failed: {exc}")
            return

        status_widget.update(label="Audit complete!", state="complete")

    progress_bar.empty()
    status_text.empty()

    st.session_state.audit_result = result
    st.rerun()


# ── Dashboard: Overview ────────────────────────────────────────────────────────

def render_overview(result: AuditResult) -> None:
    issues = result.issues
    pages  = result.pages
    stats  = result.crawl_stats

    sev_counts = result.issues_by_severity
    n_critical = len(sev_counts.get(Severity.CRITICAL, []))
    n_warning  = len(sev_counts.get(Severity.WARNING,  []))
    n_info     = len(sev_counts.get(Severity.INFO,     []))

    # ── Top row: score + summary ────────────────────────────────────────────
    col_gauge, col_stats = st.columns([1, 2])

    with col_gauge:
        st.plotly_chart(health_score_gauge(result.health_score), use_container_width=True)
        label = score_label(result.health_score)
        color = score_color(result.health_score)
        st.markdown(
            f'<div style="text-align:center;font-size:1.1rem;font-weight:700;color:{color}">{label}</div>',
            unsafe_allow_html=True,
        )

    with col_stats:
        c1, c2, c3, c4 = st.columns(4)
        _metric_card(c1, "Pages Crawled",   stats.get("total_pages", 0),   "neutral")
        _metric_card(c2, "Critical Issues", n_critical,                     "critical")
        _metric_card(c3, "Warnings",        n_warning,                      "warning")
        _metric_card(c4, "Notices",         n_info,                         "info")

        c5, c6, c7, c8 = st.columns(4)
        _metric_card(c5, "Avg Response",    f"{stats.get('avg_response_time_ms', 0):.0f} ms", "neutral")
        _metric_card(c6, "Broken Pages",    stats.get("broken_pages", 0),   "critical" if stats.get("broken_pages", 0) else "success")
        _metric_card(c7, "Indexable Pages", stats.get("indexable_pages", 0),"success")
        _metric_card(c8, "Crawl Time",      f"{result.duration_seconds:.1f}s", "neutral")

    # ── Charts row ─────────────────────────────────────────────────────────
    st.divider()
    c_left, c_right = st.columns(2)
    with c_left:
        st.plotly_chart(issues_by_category_bar(issues), use_container_width=True)
    with c_right:
        st.plotly_chart(issues_by_severity_donut(issues), use_container_width=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.plotly_chart(response_time_histogram(pages), use_container_width=True)
    with c2:
        st.plotly_chart(page_size_histogram(pages), use_container_width=True)
    with c3:
        st.plotly_chart(status_code_bar(pages), use_container_width=True)

    # ── Top 20 critical issues ──────────────────────────────────────────────
    st.divider()
    st.subheader("Top Critical Issues")
    critical_issues = sev_counts.get(Severity.CRITICAL, [])[:20]
    if critical_issues:
        _render_issue_table(critical_issues)
    else:
        st.success("No critical issues found!")

    # ── Crawl depth ─────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Crawl Depth")
    st.plotly_chart(crawl_depth_bar(pages), use_container_width=True)


# ── Dashboard: Issues by Category ─────────────────────────────────────────────

def render_by_category(result: AuditResult) -> None:
    by_cat = result.issues_by_category
    if not by_cat:
        st.success("No issues found!")
        return

    categories = sorted(by_cat.keys(), key=lambda c: -(
        sum(1 for i in by_cat[c] if i.severity == Severity.CRITICAL) * 100 +
        sum(1 for i in by_cat[c] if i.severity == Severity.WARNING)  * 10  +
        len(by_cat[c])
    ))

    # Category filter
    cat_filter = st.multiselect(
        "Filter by category",
        options=categories,
        default=categories,
    )

    sev_filter = st.multiselect(
        "Filter by severity",
        options=[Severity.CRITICAL, Severity.WARNING, Severity.INFO],
        default=[Severity.CRITICAL, Severity.WARNING, Severity.INFO],
        format_func=lambda s: s.capitalize(),
    )

    for cat in cat_filter:
        cat_issues = [i for i in by_cat.get(cat, []) if i.severity in sev_filter]
        if not cat_issues:
            continue

        n_crit = sum(1 for i in cat_issues if i.severity == Severity.CRITICAL)
        n_warn = sum(1 for i in cat_issues if i.severity == Severity.WARNING)
        n_info = sum(1 for i in cat_issues if i.severity == Severity.INFO)

        badge_html = " ".join([
            f'<span class="pill critical">{n_crit} critical</span>' if n_crit else "",
            f'<span class="pill warning">{n_warn} warning</span>'   if n_warn else "",
            f'<span class="pill info">{n_info} notice</span>'       if n_info else "",
        ])

        with st.expander(f"**{cat}** — {len(cat_issues)} issues", expanded=(cat == categories[0])):
            st.markdown(badge_html, unsafe_allow_html=True)
            st.markdown("")

            # Group by issue_type within category
            by_type: dict[str, list[Issue]] = {}
            for issue in cat_issues:
                by_type.setdefault(issue.issue_type, []).append(issue)

            for issue_type, type_issues in sorted(by_type.items(), key=lambda x: -(
                sum(1 for i in x[1] if i.severity == Severity.CRITICAL) * 100 + len(x[1])
            )):
                sample = type_issues[0]
                sev_class = sample.severity
                icon = Severity.ICONS.get(sample.severity, "•")

                with st.expander(
                    f"{icon} **{_humanize(issue_type)}** — {len(type_issues)} page(s)",
                    expanded=False,
                ):
                    st.markdown(f"**Description:** {sample.description}")
                    st.markdown(f"**Recommendation:** {sample.recommendation}")
                    st.markdown("")
                    _render_issue_table(type_issues)


# ── Dashboard: Pages ──────────────────────────────────────────────────────────

def render_pages(result: AuditResult) -> None:
    pages = result.pages
    if not pages:
        st.info("No pages crawled.")
        return

    df = pages_to_df(pages)

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        search = st.text_input("Search URL", placeholder="Filter by URL…")
    with col2:
        status_options = sorted(df["Status"].unique().tolist())
        status_filter = st.multiselect("Status code", status_options, default=status_options)
    with col3:
        indexable_filter = st.multiselect(
            "Indexable", [True, False], default=[True, False],
            format_func=lambda x: "Indexable" if x else "Non-indexable",
        )

    filtered = df.copy()
    if search:
        filtered = filtered[filtered["URL"].str.contains(search, case=False, na=False)]
    if status_filter:
        filtered = filtered[filtered["Status"].isin(status_filter)]
    if indexable_filter is not None:
        filtered = filtered[filtered["Indexable"].isin(indexable_filter)]

    st.caption(f"Showing {len(filtered)} of {len(df)} pages")

    # Issues count per page
    url_issue_counts: dict[str, int] = {}
    for issue in result.issues:
        url_issue_counts[issue.url] = url_issue_counts.get(issue.url, 0) + 1
    filtered["Issues"] = filtered["URL"].map(url_issue_counts).fillna(0).astype(int)

    st.dataframe(
        filtered[["URL", "Status", "Title", "Word Count", "Response (ms)", "Size (KB)", "Issues", "Depth", "Indexable"]],
        use_container_width=True,
        height=500,
        column_config={
            "URL":           st.column_config.TextColumn("URL", width="large"),
            "Status":        st.column_config.NumberColumn("Status", format="%d"),
            "Response (ms)": st.column_config.NumberColumn("Response (ms)", format="%.0f ms"),
            "Size (KB)":     st.column_config.NumberColumn("Size (KB)", format="%.1f KB"),
            "Issues":        st.column_config.NumberColumn("Issues", format="%d"),
        },
    )

    # Page detail expander
    st.divider()
    st.subheader("Page Detail")
    selected_url = st.selectbox("Select a page to inspect:", options=[""] + list(pages.keys()))

    if selected_url and selected_url in pages:
        _render_page_detail(pages[selected_url], result)


# ── Dashboard: Sitemap & Robots ────────────────────────────────────────────────

def render_crawlability(result: AuditResult) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("robots.txt")
        rd = result.robots_data
        if rd:
            status_color = "green" if rd.exists else "red"
            st.markdown(f"**Status:** HTTP {rd.status_code}")
            st.markdown(f"**URL:** `{rd.url}`")
            if rd.sitemap_urls:
                st.markdown(f"**Sitemap declared:** {', '.join(rd.sitemap_urls)}")
            if rd.crawl_delay:
                st.markdown(f"**Crawl-delay:** {rd.crawl_delay}s")

            if rd.raw_text:
                with st.expander("View robots.txt content"):
                    st.code(rd.raw_text, language="text")

            if rd.disallow_rules:
                with st.expander(f"Disallow rules ({len(rd.disallow_rules)})"):
                    rows = pd.DataFrame(rd.disallow_rules)
                    st.dataframe(rows, use_container_width=True)
        else:
            st.warning("robots.txt was not checked.")

    with col2:
        st.subheader("Sitemap")
        sm = result.sitemap_data
        if sm:
            st.markdown(f"**URL:** `{sm.url}`")
            st.markdown(f"**Exists:** {'Yes' if sm.exists else 'No'}")
            st.markdown(f"**URLs found:** {sm.url_count:,}")
            if sm.is_index:
                st.markdown(f"**Type:** Sitemap Index ({len(sm.child_sitemaps)} child sitemaps)")
            if sm.parse_errors:
                for err in sm.parse_errors:
                    st.error(err)
        else:
            st.warning("No sitemap data available.")

    st.divider()
    st.subheader("Crawlability Issues")
    crawl_cats = {"Sitemap", "Robots"}
    crawl_issues = [i for i in result.issues if i.category in crawl_cats]
    if crawl_issues:
        _render_issue_table(crawl_issues)
    else:
        st.success("No crawlability issues found.")


# ── Dashboard: Export ─────────────────────────────────────────────────────────

def render_export(result: AuditResult) -> None:
    st.subheader("Export Data")

    col1, col2, col3 = st.columns(3)

    with col1:
        df_issues = issues_to_df(result.issues)
        st.download_button(
            "Download All Issues (CSV)",
            data=to_csv_bytes(df_issues),
            file_name=f"issues_{result.config.domain}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(f"{len(df_issues)} issues")

    with col2:
        df_pages = pages_to_df(result.pages)
        st.download_button(
            "Download All Pages (CSV)",
            data=to_csv_bytes(df_pages),
            file_name=f"pages_{result.config.domain}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(f"{len(df_pages)} pages")

    with col3:
        df_summary = issues_summary_df(result.issues)
        st.download_button(
            "Download Issue Summary (CSV)",
            data=to_csv_bytes(df_summary),
            file_name=f"summary_{result.config.domain}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.divider()
    st.subheader("All Issues Table")
    df_issues_full = issues_to_df(result.issues)
    if not df_issues_full.empty:
        st.dataframe(df_issues_full, use_container_width=True, height=600)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _metric_card(col, label: str, value, card_class: str = "neutral") -> None:
    with col:
        st.markdown(
            f'<div class="metric-card {card_class}">'
            f'<div class="metric-lbl">{label}</div>'
            f'<div class="metric-val">{value}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_issue_table(issues: list[Issue]) -> None:
    if not issues:
        return

    rows = []
    for i in issues:
        sev_pill = f'<span class="pill {i.severity}">{i.severity}</span>'
        rows.append({
            "Sev":   i.severity.upper(),
            "URL":   i.url,
            "Issue": _humanize(i.issue_type),
            "Description": i.description,
            "Detail": i.detail or "",
        })

    df = pd.DataFrame(rows)

    sev_order = {Severity.CRITICAL.upper(): 0, Severity.WARNING.upper(): 1, Severity.INFO.upper(): 2}
    df["_o"] = df["Sev"].map(sev_order)
    df = df.sort_values("_o").drop(columns=["_o"]).reset_index(drop=True)

    def _sev_style(val):
        colors = {"CRITICAL": "#FF4B4B", "WARNING": "#FFA500", "INFO": "#4B9EFF"}
        c = colors.get(val, "#888")
        return f"color: {c}; font-weight: bold"

    styled = df.style.applymap(_sev_style, subset=["Sev"])

    st.dataframe(
        df,
        use_container_width=True,
        height=min(600, len(df) * 36 + 60),
        column_config={
            "Sev":         st.column_config.TextColumn("Severity", width="small"),
            "URL":         st.column_config.TextColumn("URL",      width="large"),
            "Issue":       st.column_config.TextColumn("Issue",    width="medium"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Detail":      st.column_config.TextColumn("Detail",   width="medium"),
        },
    )


def _render_page_detail(page: PageData, result: AuditResult) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status Code",    page.status_code)
        st.metric("Response Time",  f"{page.response_time_ms:.0f} ms")
        st.metric("Page Size",      f"{page.page_size_bytes / 1024:.1f} KB" if page.page_size_bytes else "N/A")
    with col2:
        st.metric("Word Count",     page.word_count)
        st.metric("H1 Tags",        len(page.h1_tags))
        st.metric("Images",         len(page.images))
    with col3:
        st.metric("Internal Links", len(page.internal_links))
        st.metric("External Links", len(page.external_links))
        st.metric("Crawl Depth",    page.depth)

    if page.title:
        st.markdown(f"**Title:** {page.title}")
    if page.meta_description:
        st.markdown(f"**Description:** {page.meta_description}")
    if page.canonical_url:
        st.markdown(f"**Canonical:** `{page.canonical_url}`")
    if page.redirect_chain:
        st.markdown(f"**Redirect chain:** {' → '.join(page.redirect_chain)} → {page.final_url}")

    # Issues for this page
    page_issues = [i for i in result.issues if i.url == page.url]
    if page_issues:
        st.markdown(f"**Issues on this page ({len(page_issues)}):**")
        _render_issue_table(page_issues)


def _humanize(snake: str) -> str:
    return snake.replace("_", " ").title()


# ── Landing / empty state ──────────────────────────────────────────────────────

def render_landing() -> None:
    st.markdown("""
    <div style="text-align:center; padding: 4rem 2rem;">
        <div style="font-size:4rem">🔍</div>
        <h1 style="font-size:2.5rem; font-weight:800; color:#6C63FF; margin:0.5rem 0">Site Audit Tool</h1>
        <p style="font-size:1.1rem; color:#888; max-width:600px; margin:0 auto 2rem">
            A comprehensive technical SEO audit platform. Crawls your entire site and reports
            on broken links, meta issues, redirect problems, performance, security, structured data, and more.
        </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    _feature_card(col1, "🕷️", "Deep Crawl", "Crawls every internal page, checks all links and resources")
    _feature_card(col2, "📊", "100+ Checks", "Meta tags, headings, canonicals, hreflang, schema, OG tags")
    _feature_card(col3, "⚡", "Performance", "Response time, page size, render-blocking scripts")
    _feature_card(col4, "🔐", "Security", "HTTPS, mixed content, security response headers")


def _feature_card(col, icon: str, title: str, desc: str) -> None:
    with col:
        st.markdown(
            f'<div class="metric-card neutral" style="text-align:center">'
            f'<div style="font-size:2rem">{icon}</div>'
            f'<div style="font-weight:700;margin:0.5rem 0">{title}</div>'
            f'<div style="font-size:0.85rem;color:#888">{desc}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    config = render_sidebar()

    # Start a new audit
    if config is not None:
        _clear_results()
        run_audit(config)
        return

    if not _has_result():
        render_landing()
        return

    # Show results
    result: AuditResult = st.session_state.audit_result

    # Header
    sev_counts = result.issues_by_severity
    n_crit = len(sev_counts.get(Severity.CRITICAL, []))
    st.title(f"Audit: {result.config.domain}")
    st.caption(
        f"Crawled {result.crawl_stats.get('total_pages', 0)} pages "
        f"in {result.duration_seconds:.1f}s · "
        f"Score: **{result.health_score}/100** · "
        f"{n_crit} critical issue(s)"
    )

    # Tabs
    tab_names = ["Overview", "Issues by Category", "Pages", "Crawlability", "Export"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        render_overview(result)

    with tabs[1]:
        render_by_category(result)

    with tabs[2]:
        render_pages(result)

    with tabs[3]:
        render_crawlability(result)

    with tabs[4]:
        render_export(result)


if __name__ == "__main__":
    main()
