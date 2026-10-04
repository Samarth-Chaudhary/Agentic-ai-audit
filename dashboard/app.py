"""AI Agent Governance & Audit Trail Analyzer - Reviewer Dashboard.

Two Major Tabs:
- TAB 1: Audit Explorer (Operational Trace Inspection via API Gateway / DynamoDB / S3)
- TAB 2: Risk Analytics (Aggregate Analytics via Athena & SQL Queries)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path when launched via Streamlit CLI
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import importlib

import pandas as pd
import streamlit as st

# Dynamic module reload ensures Streamlit daemon picks up updated modules on every rerun
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith(("dashboard.", "auditor.")):
        try:
            importlib.reload(sys.modules[mod_name])
        except Exception:
            pass

try:
    from dashboard.api_client import AuditApiClient
    from dashboard.athena_client import DashboardAthenaService
    from dashboard.charts import (
        chart_avg_risk_by_task,
        chart_daily_risk_trend,
        chart_risk_distribution,
        chart_tool_violations,
    )
    from dashboard.components import (
        render_3d_trail_replay,
        render_compliance_export_card,
        render_cryptographic_integrity_card,
        render_degraded_banner,
        render_engine_badge,
        render_evidence_panel,
        render_header,
        render_kpi_metrics,
        render_risk_badge,
        render_trace_timeline,
    )
    from dashboard.theme import inject_theme
except ImportError:
    from api_client import AuditApiClient  # type: ignore[no-redef]
    from athena_client import DashboardAthenaService  # type: ignore[no-redef]
    from charts import (  # type: ignore[no-redef]
        chart_avg_risk_by_task,
        chart_daily_risk_trend,
        chart_risk_distribution,
        chart_tool_violations,
    )
    from components import (  # type: ignore[no-redef]
        render_3d_trail_replay,
        render_compliance_export_card,
        render_cryptographic_integrity_card,
        render_degraded_banner,
        render_engine_badge,
        render_evidence_panel,
        render_header,
        render_kpi_metrics,
        render_risk_badge,
        render_trace_timeline,
    )
    from theme import inject_theme  # type: ignore[no-redef]


# Page configuration
st.set_page_config(
    page_title="AI Agent Governance & Audit Analyzer",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    # -------------------------------------------------------------------------
    # Centralized Glassmorphic Theme Injection
    # -------------------------------------------------------------------------
    inject_theme()

    # -------------------------------------------------------------------------
    # Sidebar: Mode Selection & Filters (Reference Floating Sidebar Style)
    # -------------------------------------------------------------------------
    st.sidebar.markdown(
        '<div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">'
        '<span style="font-size:26px;">🛡️</span>'
        '<div>'
        '<div style="font-size:18px; font-weight:800; color:#111111; letter-spacing:-0.03em;">AGY Audit</div>'
        '<div style="font-size:10.5px; color:#8E8E93; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Enterprise Assurance</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("### ENVIRONMENT")

    # Mode Selector
    default_demo = os.environ.get("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    data_mode = st.sidebar.radio(
        "Data Source Environment:",
        options=["Demo / Local Data", "Live AWS Pipeline"],
        index=0 if default_demo else 1,
        help="Switch between local demonstration fixtures and live AWS API Gateway/Athena connection.",
    )
    is_demo_mode = data_mode == "Demo / Local Data"

    # API Base URL configuration if in Live mode
    default_api_url = os.environ.get("API_GATEWAY_URL", "http://localhost:8000")
    if not is_demo_mode:
        api_url = st.sidebar.text_input(
            "API Gateway URL:",
            value=default_api_url,
            placeholder="http://localhost:8000 or AWS API Gateway URL",
            help="For 100% free local AWS pipeline, use http://localhost:8000. For cloud AWS, paste your API Gateway invoke URL.",
        )
        st.sidebar.caption("💡 **Zero-Cost AWS Pipeline:** Run `python scripts/run_free_pipeline.py` in your terminal.")
    else:
        api_url = ""

    st.sidebar.divider()
    st.sidebar.markdown("### FILTERS")

    selected_task_type = st.sidebar.selectbox(
        "Task Type:",
        options=["All Tasks", "customer_refund", "research_summary"],
        index=0,
    )
    task_filter = None if selected_task_type == "All Tasks" else selected_task_type

    selected_risk_tier = st.sidebar.selectbox(
        "Risk Tier:",
        options=["All Tiers", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
        index=0,
    )
    tier_filter = None if selected_risk_tier == "All Tiers" else selected_risk_tier

    selected_date = st.sidebar.selectbox(
        "Date:",
        options=["All Dates", "2026-09-27", "2026-09-26", "2026-09-25", "2026-09-24", "2026-09-23"],
        index=0,
        help="Filter traces by audit timestamp date.",
    )
    date_filter = None if selected_date == "All Dates" else selected_date

    st.sidebar.divider()
    st.sidebar.markdown(
        "### GOVERNANCE STANDARDS\n"
        "- **Scope Control:** Tool authorization & limits\n"
        "- **PII Control:** Presidio / Regex redaction\n"
        "- **Groundedness Control:** NLI factual entailment\n"
        "- **Risk Engine:** Composite weighted scoring\n"
    )

    st.sidebar.markdown(
        '<div style="margin-top:20px; padding-top:12px; border-top:1px solid rgba(0,0,0,0.06); font-size:12px; font-weight:600; color:#737373; display:flex; align-items:center; gap:8px;">'
        '⚙️ Settings & System Policies'
        '</div>',
        unsafe_allow_html=True,
    )

    # Initialize Services
    api_client = AuditApiClient(base_url=api_url, demo_mode=is_demo_mode)
    athena_service = DashboardAthenaService(demo_mode=is_demo_mode)

    # -------------------------------------------------------------------------
    # Main Header & High-Level KPIs
    # -------------------------------------------------------------------------
    render_header(demo_mode=is_demo_mode)

    try:
        metrics = api_client.get_summary_metrics()
    except Exception as exc:
        st.error(f"Could not load summary metrics: {exc}")
        metrics = {}

    render_kpi_metrics(metrics)
    st.write("")

    # -------------------------------------------------------------------------
    # Two Major Dashboard Tabs
    # -------------------------------------------------------------------------
    tab_explorer, tab_analytics, tab_replay = st.tabs([
        "🔍 TAB 1: Audit Explorer",
        "📊 TAB 2: Risk Analytics",
        "🤖 TAB 3: Trail Replay",
    ])

    # =========================================================================
    # TAB 1: AUDIT EXPLORER (Operational Inspection)
    # =========================================================================
    with tab_explorer:
        # Compact Header Strip
        st.markdown(
            '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; background:#FFFFFF; border-radius:18px; padding:12px 18px; border:1px solid rgba(0,0,0,0.06); box-shadow:0 2px 8px rgba(0,0,0,0.02);">'
            '<div style="display:flex; align-items:center; gap:10px;">'
            '<span style="font-size:18px;">🛡️</span>'
            '<div>'
            '<span style="font-size:14px; font-weight:800; color:#111111;">Operational Trace Explorer & Deep Audit</span>'
            '<span style="font-size:11.5px; color:#737373; margin-left:10px;">Post-hoc multi-control policy verification</span>'
            '</div>'
            '</div>'
            '<div style="display:flex; gap:6px;">'
            '<span style="background:#F4F4F6; color:#111111; font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;">⚡ SCOPE</span>'
            '<span style="background:#F4F4F6; color:#111111; font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;">🔒 PII</span>'
            '<span style="background:#F4F4F6; color:#111111; font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;">📑 NLI</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        try:
            traces_list = api_client.list_traces(
                task_type=task_filter,
                risk_tier=tier_filter,
                date_filter=date_filter,
                limit=100,
            )
        except ConnectionError as exc:
            st.error(f"⚠️ **API Gateway Unavailable**: {exc}. Please verify connectivity or switch to Demo Mode in sidebar.")
            traces_list = []
        except Exception as exc:
            st.error(f"⚠️ **Failed to retrieve traces from API Gateway**: {exc}")
            traces_list = []

        if not traces_list:
            st.info("No traces matched the selected filter criteria.")
        else:
            trace_map = {t["trace_id"]: t for t in traces_list}
            trace_ids = [t["trace_id"] for t in traces_list]

            # 2-Column Split: Left = Selection, Briefing & Crypto; Right = Timeline / Evidence / 3D State Space
            col_left, col_right = st.columns([5, 7], gap="medium")

            with col_left:
                # 1. Trace Selector Dropdown with high-visibility formatting
                selected_trace_id = st.selectbox(
                    "Select Audited Execution Trace:",
                    options=trace_ids,
                    index=0,
                    format_func=lambda tid: (
                        f"{tid} — {trace_map[tid].get('task_type', '')} "
                        f"[{trace_map[tid].get('risk_tier', 'LOW')} | Score: {float(trace_map[tid].get('risk_score', 0)):.1f}]"
                    ),
                )

                # Quick Traces summary table (collapsible)
                with st.expander("📋 View All Filtered Traces Summary", expanded=False):
                    df_table = pd.DataFrame([
                        {
                            "Trace ID": t["trace_id"],
                            "Task Type": t["task_type"],
                            "Date/Time": t.get("processed_at", ""),
                            "Risk Score": f"{float(t['risk_score']):.1f}",
                            "Risk Tier": t["risk_tier"],
                            "Engine Mode": "⚠️ DEGRADED" if t.get("is_degraded") else "🛡️ Full ML",
                            "Scope Issues": t.get("scope_violation_count", t.get("scope_violations", 0)),
                            "PII Issues": t.get("pii_count", t.get("pii_findings", 0)),
                            "Groundedness Issues": t.get("groundedness_failure_count", t.get("groundedness_failures", 0)),
                        }
                        for t in traces_list
                    ])
                    st.dataframe(df_table, use_container_width=True, hide_index=True, height=140)

                if selected_trace_id:
                    try:
                        trace_detail = api_client.get_trace(selected_trace_id)
                    except KeyError:
                        st.error(f"🔍 **Trace Not Found**: Trace '{selected_trace_id}' was not found.")
                        trace_detail = None
                    except ConnectionError as exc:
                        st.error(f"⚠️ **API Connection Error**: {exc}")
                        trace_detail = None
                    except Exception as exc:
                        st.error(f"⚠️ **Error Fetching Trace Details**: {exc}")
                        trace_detail = None

                    if trace_detail:
                        raw_score = trace_detail.get("risk_score")
                        if raw_score is None:
                            raw_score = trace_detail.get("risk", {}).get("risk_score", 0.0)
                        score = float(raw_score or 0.0)
                        tier = str(trace_detail.get("risk_tier") or trace_detail.get("risk", {}).get("risk_tier", "LOW"))
                        processed_at = trace_detail.get("processed_at", "N/A")
                        summary = trace_detail.get("summary", "No summary generated.")
                        is_degraded = bool(trace_detail.get("is_degraded", False))
                        degraded_reasons = trace_detail.get("degraded_reasons", [])
                        engine_info = trace_detail.get("engine_info")

                        if is_degraded:
                            render_degraded_banner(is_degraded=True, degraded_reasons=degraded_reasons)

                        findings = trace_detail.get("findings", {})
                        scope_count = len(findings.get("scope", []))
                        pii_count = len(findings.get("pii", []))
                        ground_count = len(findings.get("groundedness", []))

                        where_steps = []
                        for f in findings.get("scope", []):
                            where_steps.append(f"Step {f.get('step_index', '?')} (Scope)")
                        for f in findings.get("pii", []):
                            where_steps.append(f"Step {f.get('step_index', '?')} (PII)")
                        for f in findings.get("groundedness", []):
                            ev = f.get('evidence_step_index') or f.get('evidence_step')
                            where_steps.append(f"Step {ev if ev is not None else '?'} (Groundedness)")

                        where_text = ", ".join(where_steps) if where_steps else "None (Trace is fully compliant)"

                        # Compact Trace Verdict & Briefing Card
                        with st.container(border=True):
                            c_top1, c_top2 = st.columns([3, 2])
                            with c_top1:
                                st.markdown(f"### Trace `{trace_detail.get('trace_id')}`")
                                st.caption(f"Task: `{trace_detail.get('task_type')}` | Processed: `{processed_at}`")
                            with c_top2:
                                st.markdown(render_risk_badge(tier, score), unsafe_allow_html=True)
                                st.markdown(render_engine_badge(engine_info, is_degraded=is_degraded), unsafe_allow_html=True)

                            st.markdown(f"**WHAT:** {summary}")
                            st.markdown(f"**WHERE:** `{where_text}`")
                            st.markdown(f"**WHY:** Risk score of {score:.1f} ({tier}) derived from {scope_count} scope violations, {pii_count} sensitive PII leaks, and {ground_count} groundedness issues.")

                        # Cryptographic Integrity & Regulatory Compliance Attestation
                        render_cryptographic_integrity_card(trace_detail)
                        render_compliance_export_card(trace_detail)

            with col_right:
                if selected_trace_id and trace_detail:
                    timeline = trace_detail.get("execution_timeline", [])
                    findings = trace_detail.get("findings", {})

                    # Deep Dive Sub-Tabs inside single card container
                    sub_timeline, sub_evidence, sub_3d = st.tabs([
                        "⏱️ Chronological Timeline",
                        "📑 Policy Evidence Findings",
                        "🌐 3D State Space Trajectory",
                    ])

                    with sub_timeline:
                        render_trace_timeline(timeline, findings)

                    with sub_evidence:
                        render_evidence_panel(findings)

                    with sub_3d:
                        render_3d_trail_replay(timeline, findings)

    # =========================================================================
    # TAB 3: TRAIL REPLAY (Interactive 3D Isometric Bot Animation)
    # =========================================================================
    with tab_replay:
        st.subheader("🤖 Interactive 3D Agent Trail Replay")
        st.caption("Visual isometric replay of the agent's path, tool calls, data flow, and policy violations.")

        import streamlit.components.v1 as components

        try:
            from dashboard.trail_replay import render_replay_html
        except ImportError:
            from trail_replay import render_replay_html

        try:
            replay_traces = api_client.list_traces(
                task_type=task_filter,
                risk_tier=tier_filter,
                date_filter=date_filter,
                limit=100,
            )
        except Exception:
            replay_traces = []

        if not replay_traces:
            st.info("No traces available to replay matching current filter criteria.")
        else:
            trace_map = {t["trace_id"]: t for t in replay_traces}
            selected_replay_id = st.selectbox(
                "Select Trace to Replay:",
                options=list(trace_map.keys()),
                key="trail_replay_trace_selector",
                format_func=lambda tid: f"{tid} — {trace_map[tid].get('task_type', '')} (Risk: {trace_map[tid].get('risk_tier', '')}, Score: {trace_map[tid].get('risk_score', '')})",
            )

            if selected_replay_id:
                try:
                    replay_detail = api_client.get_trace(selected_replay_id)
                except Exception as exc:
                    st.error(f"Failed to load trace {selected_replay_id}: {exc}")
                    replay_detail = None

                if replay_detail:
                    replay_html = render_replay_html(replay_detail)
                    components.html(replay_html, height=780, scrolling=True)

    # =========================================================================
    # TAB 2: RISK ANALYTICS (Aggregate SQL & Athena)
    # =========================================================================
    with tab_analytics:
        st.subheader("📈 Historical Governance & Risk Analytics")
        st.caption("Macro governance trends, violation distributions, and tool failure analytics queried via Athena SQL.")

        # Row 1: Risk Distribution & Average Risk by Task
        c_left, c_right = st.columns(2)

        with c_left:
            try:
                df_dist = athena_service.run_named_query("02_risk_distribution")
                st.plotly_chart(chart_risk_distribution(df_dist), use_container_width=True)
            except Exception as exc:
                st.error(f"⚠️ Query 02 (Risk Distribution) failed: {exc}")

        with c_right:
            try:
                df_avg_task = athena_service.run_named_query("01_avg_risk_by_task")
                st.plotly_chart(chart_avg_risk_by_task(df_avg_task), use_container_width=True)
            except Exception as exc:
                st.error(f"⚠️ Query 01 (Avg Risk by Task) failed: {exc}")

        # Row 2: Daily Risk Trend & High Risk Proportions
        st.write("---")
        try:
            df_trend = athena_service.run_named_query("09_daily_risk_trend")
            st.plotly_chart(chart_daily_risk_trend(df_trend), use_container_width=True)
        except Exception as exc:
            st.error(f"⚠️ Query 09 (Daily Risk Trend) failed: {exc}")

        # Row 3: Tool-Level Violation Analysis & High Risk by Date
        st.write("---")
        c_tool, c_high_date = st.columns(2)

        with c_tool:
            try:
                df_tools = athena_service.run_named_query("10_tool_violation_analysis")
                st.plotly_chart(chart_tool_violations(df_tools), use_container_width=True)
            except Exception as exc:
                st.error(f"⚠️ Query 10 (Tool Violation Analysis) failed: {exc}")

        with c_high_date:
            try:
                df_high_date = athena_service.run_named_query("03_high_risk_by_date")
                st.markdown("#### 🚨 High-Risk Traces by Date")
                st.dataframe(df_high_date, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"⚠️ Query 03 (High Risk by Date) failed: {exc}")

        # Row 4: Multi-Control Violation Tables (Scope, PII, Groundedness, Unsupported, Contradicted)
        st.write("---")
        st.markdown("### 🔍 Multi-Control Breakdown Tables")

        t_scope, t_pii, t_ground, t_unsupp, t_contra = st.tabs([
            "Scope by Task",
            "PII Leakage by Task",
            "Groundedness by Task",
            "Unsupported Claims",
            "Contradicted Claims",
        ])

        with t_scope:
            try:
                df_sc = athena_service.run_named_query("04_scope_violations_by_task")
                st.dataframe(df_sc, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"⚠️ Query 04 (Scope Violations by Task) failed: {exc}")

        with t_pii:
            try:
                df_pi = athena_service.run_named_query("05_pii_by_task")
                st.dataframe(df_pi, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"⚠️ Query 05 (PII by Task) failed: {exc}")

        with t_ground:
            try:
                df_gr = athena_service.run_named_query("06_groundedness_failures")
                st.dataframe(df_gr, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"⚠️ Query 06 (Groundedness Failures) failed: {exc}")

        with t_unsupp:
            try:
                df_un = athena_service.run_named_query("07_unsupported_claims")
                st.dataframe(df_un, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"⚠️ Query 07 (Unsupported Claims) failed: {exc}")

        with t_contra:
            try:
                df_ct = athena_service.run_named_query("08_contradicted_claims")
                st.dataframe(df_ct, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"⚠️ Query 08 (Contradicted Claims) failed: {exc}")

        # Athena SQL Query Inspector (Security & Transparency)
        st.write("---")
        with st.expander("🛠️ Athena SQL Query Inspector (Predefined Queries)", expanded=False):
            st.caption("Inspect the exact Presto/Trino SQL queries powering each visualization.")
            selected_query = st.selectbox(
                "Select Predefined Query to Inspect:",
                options=[
                    "01_avg_risk_by_task",
                    "02_risk_distribution",
                    "03_high_risk_by_date",
                    "04_scope_violations_by_task",
                    "05_pii_by_task",
                    "06_groundedness_failures",
                    "07_unsupported_claims",
                    "08_contradicted_claims",
                    "09_daily_risk_trend",
                    "10_tool_violation_analysis",
                ],
            )
            sql_path = os.path.join("analytics", "sql", f"{selected_query}.sql")
            if os.path.exists(sql_path):
                with open(sql_path, encoding="utf-8") as f:
                    st.code(f.read(), language="sql")


if __name__ == "__main__":
    main()
