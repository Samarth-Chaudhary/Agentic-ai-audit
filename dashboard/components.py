"""Reusable Streamlit UI presentation components for the Agent Governance Dashboard."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

# Consistent Visual Semantic Palettes
TIER_COLORS: dict[str, str] = {
    "LOW": "#10b981",       # Emerald Green
    "MEDIUM": "#f59e0b",    # Amber Yellow
    "HIGH": "#f97316",      # Bright Orange
    "CRITICAL": "#ef4444",  # Crimson Red
}

TIER_BG: dict[str, str] = {
    "LOW": "rgba(16, 185, 129, 0.15)",
    "MEDIUM": "rgba(245, 158, 11, 0.15)",
    "HIGH": "rgba(249, 115, 22, 0.15)",
    "CRITICAL": "rgba(239, 68, 68, 0.15)",
}


def render_header(demo_mode: bool = True) -> None:
    """Render top header and deployment status badge."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("🛡️ AI Agent Governance & Audit Analyzer")
        st.caption("Deterministic Multi-Control Post-Hoc Audit Pipeline & Analytics Dashboard")

    with col2:
        st.write("")
        if demo_mode:
            st.warning("⚠️ **DEMO / LOCAL DATA**\n\n*Reviewer Demonstration Mode*", icon="⚠️")
        else:
            st.success("🟢 **LIVE AWS DATA**\n\n*Connected to AWS Pipeline*", icon="✅")


def render_kpi_metrics(metrics: dict[str, Any]) -> None:
    """Render 6-card KPI summary metrics bar."""
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Total Traces", metrics.get("total_traces", 0))
    with c2:
        st.metric("High-Risk Traces", metrics.get("high_risk_traces", 0), delta_color="inverse")
    with c3:
        st.metric("Critical Traces", metrics.get("critical_risk_traces", 0), delta_color="inverse")
    with c4:
        st.metric("Scope Violations", metrics.get("scope_violations", 0), delta_color="inverse")
    with c5:
        st.metric("PII Detections", metrics.get("pii_findings", 0), delta_color="inverse")
    with c6:
        st.metric("Groundedness Issues", metrics.get("groundedness_failures", 0), delta_color="inverse")


def render_risk_badge(tier: str, score: float) -> str:
    """Return HTML formatted risk badge string."""
    color = TIER_COLORS.get(tier.upper(), "#6b7280")
    bg = TIER_BG.get(tier.upper(), "rgba(107, 114, 128, 0.15)")
    return (
        f'<span style="background-color: {bg}; color: {color}; '
        f'padding: 4px 10px; border-radius: 6px; font-weight: 700; '
        f'border: 1px solid {color};">'
        f'{tier} ({score:.1f})</span>'
    )


def render_engine_badge(engine_info: dict[str, Any] | None = None, is_degraded: bool = False) -> str:
    """Return HTML formatted engine identity badge displaying engine info next to risk score."""
    degraded = is_degraded or (bool(engine_info.get("is_degraded")) if engine_info else False)

    if degraded:
        reasons = (engine_info or {}).get("degraded_reasons", [])
        reasons_str = f"<br><span style='color: #fca5a5;'>Reason: {', '.join(reasons)}</span>" if reasons else ""
        nli = (engine_info or {}).get("nli_engine", "heuristic-fallback")
        emb = (engine_info or {}).get("embedding_engine", "jaccard-tfidf-fallback")
        pii = (engine_info or {}).get("pii_engine", "regex-only-fallback")
        return (
            f'<div style="margin-top: 8px; padding: 6px 10px; border-radius: 6px; '
            f'background-color: rgba(239, 68, 68, 0.12); border: 1px solid #ef4444; color: #ef4444; font-size: 0.82em;">'
            f'<strong>⚠️ DEGRADED ENGINE</strong>{reasons_str}<br>'
            f'<span style="color: #cbd5e1;">NLI:</span> <code>{nli}</code><br>'
            f'<span style="color: #cbd5e1;">Embeddings:</span> <code>{emb}</code><br>'
            f'<span style="color: #cbd5e1;">PII:</span> <code>{pii}</code>'
            f'</div>'
        )

    nli = (engine_info or {}).get("nli_engine", "cross-encoder/nli-deberta-v3-small")
    emb = (engine_info or {}).get("embedding_engine", "sentence-transformers/all-MiniLM-L6-v2")
    pii = (engine_info or {}).get("pii_engine", "presidio-nlp (spacy: en_core_web_sm)")
    return (
        f'<div style="margin-top: 8px; padding: 6px 10px; border-radius: 6px; '
        f'background-color: rgba(16, 185, 129, 0.10); border: 1px solid #10b981; color: #10b981; font-size: 0.82em;">'
        f'<strong>🛡️ VERIFIED ML ENGINE</strong><br>'
        f'<span style="color: #cbd5e1;">NLI:</span> <code>{nli}</code><br>'
        f'<span style="color: #cbd5e1;">Embeddings:</span> <code>{emb}</code><br>'
        f'<span style="color: #cbd5e1;">PII:</span> <code>{pii}</code>'
        f'</div>'
    )


def render_degraded_banner(is_degraded: bool, degraded_reasons: list[str] | None = None) -> None:
    """Render prominent visual warning banner if audit result is in degraded mode."""
    if is_degraded:
        reasons_bullets = "\n".join(f"- {r}" for r in (degraded_reasons or [])) if degraded_reasons else "- Fallback heuristic engines utilized"
        st.error(
            f"### ⚠️ DEGRADED AUDIT WARNING\n\n"
            f"This audit ran in **DEGRADED MODE** because one or more required ML models were unavailable.\n\n"
            f"**Degraded Reasons:**\n{reasons_bullets}\n\n"
            f"*Notice: Confidence is reduced. Results were produced via heuristic fallback engines and require manual review.*",
            icon="⚠️",
        )


def render_trace_timeline(timeline: list[dict[str, Any]], findings: dict[str, list[dict[str, Any]]]) -> None:
    """Render chronological execution timeline with findings overlay."""
    st.subheader("⏱️ Chronological Execution Timeline")
    st.caption("Inspect each step of the agent execution. Violations are overlaid inline next to the failing step.")

    if not timeline:
        st.info("No detailed execution steps recorded for this trace.")
        return

    # Index findings by step index
    scope_by_step: dict[int, list[dict[str, Any]]] = {}
    for f in findings.get("scope", []):
        idx = f.get("step_index")
        if idx is not None:
            scope_by_step.setdefault(idx, []).append(f)

    pii_by_step: dict[int, list[dict[str, Any]]] = {}
    for f in findings.get("pii", []):
        idx = f.get("step_index")
        if idx is not None:
            pii_by_step.setdefault(idx, []).append(f)

    groundedness_by_step: dict[int, list[dict[str, Any]]] = {}
    for f in findings.get("groundedness", []):
        idx = f.get("evidence_step_index") if f.get("evidence_step_index") is not None else f.get("evidence_step")
        if idx is not None:
            groundedness_by_step.setdefault(int(idx), []).append(f)

    for i, step in enumerate(timeline):
        step_idx = step.get("step_index", i)
        step_type = str(step.get("type", "UNKNOWN")).upper()
        tool_name = step.get("tool_name")

        # Formulate human-readable step description matching Part 9 reviewer guidelines
        if tool_name:
            if "CALL" in step_type:
                step_desc = f"{tool_name} tool call"
            elif "RESULT" in step_type or "OBSERVATION" in step_type:
                step_desc = f"{tool_name} tool result"
            else:
                step_desc = f"{tool_name} ({step_type.lower()})"
        elif step_type in ("USER_INPUT", "USER"):
            step_desc = "user message"
        elif step_type in ("ASSISTANT", "ACTION", "AGENT"):
            step_desc = "assistant/action message"
        elif step_type in ("FINAL_ANSWER", "ANSWER"):
            step_desc = "final answer message"
        else:
            step_desc = step_type.lower().replace("_", " ")

        header_label = f"STEP {step_idx} - {step_desc}"

        # Check if any findings are attached to this step
        step_scope = scope_by_step.get(step_idx, [])
        step_pii = pii_by_step.get(step_idx, [])
        step_ground = groundedness_by_step.get(step_idx, [])
        has_violations = bool(step_scope or step_pii or step_ground)

        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                st.markdown(f"**{header_label}**")
            with cols[1]:
                if has_violations:
                    st.markdown('<span style="color: #ef4444; font-weight: 700;">⚠️ VIOLATION DETECTED</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span style="color: #10b981; font-weight: 500;">✓ Compliant</span>', unsafe_allow_html=True)

            # -------------------------------------------------------------
            # Inline Findings Overlay (Prominent non-JSON explanation)
            # -------------------------------------------------------------
            for sc in step_scope:
                severity = sc.get("severity", "HIGH")
                explanation = sc.get("explanation") or sc.get("detail", "Unauthorized tool invocation detected.")
                st.error(
                    f"**🚨 {severity} - SCOPE VIOLATION**\n\n"
                    f"{explanation}\n\n"
                    f"*Tool:* `{sc.get('tool_name') or sc.get('tool')}` | *Rule:* `{sc.get('rule_violated') or sc.get('rule')}`"
                )

            for pi in step_pii:
                severity = pi.get("severity", "CRITICAL")
                pii_type = pi.get("pii_type") or pi.get("type", "SENSITIVE_DATA")
                field = pi.get("field_path") or pi.get("field", "payload")
                redacted = pi.get("redacted_snippet", "<REDACTED>")
                st.error(
                    f"**🔒 {severity} - PII VIOLATION**\n\n"
                    f"**Type:** `{pii_type}` in **Field:** `{field}`\n\n"
                    f"**Redacted Snippet:** `{redacted}` (Confidence: {pi.get('confidence_score', 1.0):.2f})"
                )

            for gr in step_ground:
                verdict = gr.get("audit_verdict", "UNSUPPORTED")
                severity = gr.get("severity", "HIGH")
                st.warning(
                    f"**⚠️ {severity} - GROUNDEDNESS {verdict}**\n\n"
                    f"**Claim:** \"{gr.get('claim')}\"\n\n"
                    f"**Evidence Snippet:** \"{gr.get('evidence_snippet')}\""
                )

            # Step content rendering
            if step.get("content"):
                st.markdown(f"**Content / Message:**\n\n{step['content']}")

            if step.get("tool_input"):
                st.markdown("**Tool Input Parameters:**")
                st.code(json.dumps(step["tool_input"], indent=2, default=str), language="json")

            if step.get("observation"):
                st.markdown(f"**Tool Observation / Output:**\n\n{step['observation']}")


def render_evidence_panel(findings: dict[str, list[dict[str, Any]]]) -> None:
    """Render structured evidence tabs for deeper technical inspection."""
    st.subheader("📑 Audit Evidence & Policy Findings")
    st.caption("Technical audit findings across the three independent governance controls.")

    tab_scope, tab_pii, tab_ground = st.tabs(["Scope Violations", "Sensitive Data (PII)", "Factual Groundedness"])

    with tab_scope:
        scope_findings = findings.get("scope", [])
        if not scope_findings:
            st.success("✅ Zero scope violations detected. Tool usage conformed to task policy.")
        else:
            for item in scope_findings:
                tool = item.get("tool_name") or item.get("tool", "unknown_tool")
                step = item.get("step_index") if item.get("step_index") is not None else item.get("step", 0)
                rule = item.get("rule_violated") or item.get("rule", "ALLOWED_TOOLS")
                severity = item.get("severity", "HIGH")
                explanation = item.get("explanation") or item.get("detail", "Unauthorized tool invocation.")
                engine = item.get("engine", "policy-rule-engine")

                with st.expander(f"Tool `{tool}` - {severity}", expanded=True):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.write(f"**Tool:** `{tool}`")
                    c2.write(f"**Step:** `{step}`")
                    c3.write(f"**Severity:** `{severity}`")
                    c4.write(f"**Engine:** `{engine}`")
                    st.write(f"**Rule:** `{rule}`")
                    st.write(f"**Explanation:** {explanation}")

    with tab_pii:
        pii_findings = findings.get("pii", [])
        if not pii_findings:
            st.success("✅ Zero PII or sensitive secrets detected in execution trace.")
        else:
            for item in pii_findings:
                pii_type = item.get("pii_type") or item.get("type", "UNKNOWN")
                step = item.get("step_index") if item.get("step_index") is not None else item.get("step", 0)
                field = item.get("field_path") or item.get("field", "unknown_field")
                severity = item.get("severity", "CRITICAL")
                snippet = item.get("redacted_snippet", "<REDACTED>")
                engine = item.get("engine", "presidio-nlp (spacy: en_core_web_sm)")

                with st.expander(f"Entity `{pii_type}` - {severity}", expanded=True):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.write(f"**Type:** `{pii_type}`")
                    c2.write(f"**Step:** `{step}`")
                    c3.write(f"**Severity:** `{severity}`")
                    c4.write(f"**Engine:** `{engine}`")
                    st.write(f"**Field:** `{field}`")
                    st.write(f"**Redacted Snippet:** `{snippet}`")

    with tab_ground:
        ground_findings = findings.get("groundedness", [])
        if not ground_findings:
            st.success("✅ Final answer statements are fully grounded in verified tool observations.")
        else:
            for item in ground_findings:
                claim = item.get("claim", "")
                evidence = item.get("evidence_snippet", "")
                ev_step = item.get("evidence_step_index") if item.get("evidence_step_index") is not None else item.get("evidence_step", "N/A")
                sim = float(item.get("similarity", 0.0))
                nli_verdict = item.get("nli_verdict", "NEUTRAL")
                audit_verdict = item.get("audit_verdict", "UNSUPPORTED")
                engine = item.get("engine", "cross-encoder/nli-deberta-v3-small")

                with st.expander(f"Claim: \"{claim[:60]}...\" - {audit_verdict}", expanded=True):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.write(f"**Audit Verdict:** `{audit_verdict}`")
                    c2.write(f"**NLI Verdict:** `{nli_verdict}`")
                    c3.write(f"**Similarity:** `{sim:.2f}`")
                    c4.write(f"**Engine:** `{engine}`")
                    st.write(f"**Claim:** {claim}")
                    st.write(f"**Evidence Snippet:** {evidence}")
                    st.write(f"**Evidence Step:** `{ev_step}`")
