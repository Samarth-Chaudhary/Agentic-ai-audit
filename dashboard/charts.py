"""Plotly charting utilities for the Risk Analytics tab."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

TIER_COLORS = {
    "LOW": "#10b981",
    "MEDIUM": "#f59e0b",
    "HIGH": "#f97316",
    "CRITICAL": "#ef4444",
}


def chart_risk_distribution(df: pd.DataFrame) -> go.Figure:
    """Render donut chart of trace distribution across risk tiers."""
    if df.empty or "risk_tier" not in df.columns:
        return go.Figure()

    fig = px.pie(
        df,
        names="risk_tier",
        values="trace_count",
        color="risk_tier",
        color_discrete_map=TIER_COLORS,
        hole=0.45,
        title="<b>Trace Distribution Across Risk Tiers</b>",
    )
    fig.update_traces(textinfo="percent+label", hoverinfo="value+percent")
    fig.update_layout(margin={"t": 50, "b": 20, "l": 20, "r": 20}, height=350)
    return fig


def chart_avg_risk_by_task(df: pd.DataFrame) -> go.Figure:
    """Render horizontal bar chart of average risk score per task type."""
    if df.empty or "task_type" not in df.columns:
        return go.Figure()

    fig = px.bar(
        df,
        x="avg_risk_score",
        y="task_type",
        orientation="h",
        color="avg_risk_score",
        color_continuous_scale=["#10b981", "#f59e0b", "#f97316", "#ef4444"],
        range_color=[0, 100],
        title="<b>Average Risk Score by Task Type</b>",
        labels={"avg_risk_score": "Average Risk Score (0-100)", "task_type": "Task Type"},
        text="avg_risk_score",
    )
    fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    fig.update_layout(margin={"t": 50, "b": 20, "l": 20, "r": 20}, height=350)
    return fig


def chart_daily_risk_trend(df: pd.DataFrame) -> go.Figure:
    """Render multi-line chart showing daily risk score trend and violation volume."""
    if df.empty or "date" not in df.columns:
        return go.Figure()

    fig = go.Figure()

    # Average risk score line
    if "daily_avg_risk" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["daily_avg_risk"],
                mode="lines+markers",
                name="Avg Risk Score",
                line={"color": "#f97316", "width": 3},
            )
        )

    # High risk percentage line
    if "daily_high_risk_ratio" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["daily_high_risk_ratio"],
                mode="lines+markers",
                name="High/Critical Risk %",
                line={"color": "#ef4444", "width": 2, "dash": "dot"},
            )
        )

    fig.update_layout(
        title="<b>Daily Risk Score & High-Risk Violation Trends</b>",
        xaxis_title="Date",
        yaxis_title="Score / Percentage",
        margin={"t": 50, "b": 20, "l": 20, "r": 20},
        height=350,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return fig


def chart_tool_violations(df: pd.DataFrame) -> go.Figure:
    """Render bar chart of violations per tool name."""
    if df.empty or "tool_name" not in df.columns:
        return go.Figure()

    fig = px.bar(
        df,
        x="tool_name",
        y="violation_count",
        color="avg_risk_when_violated",
        color_continuous_scale=["#f59e0b", "#f97316", "#ef4444"],
        title="<b>Tool-Level Violation Frequency & Risk Severity</b>",
        labels={
            "tool_name": "Invoked Tool",
            "violation_count": "Total Violations",
            "avg_risk_when_violated": "Avg Risk Score",
        },
        text="violation_count",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(margin={"t": 50, "b": 20, "l": 20, "r": 20}, height=350)
    return fig


def chart_3d_trail_replay(
    timeline: list[dict[str, Any]],
    findings: dict[str, list[dict[str, Any]]],
) -> go.Figure:
    """Render interactive 3D execution trail replay of agent trajectory.

    Dimensions:
    - X-axis: Chronological step sequence (0, 1, ..., N)
    - Y-axis: Agent Execution Layer (User -> Thought -> Tool -> Observation -> Answer)
    - Z-axis: Risk & Anomaly Severity Score (0 = Compliant, 10 = Critical Violation)
    """
    if not timeline:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="<b>3D Execution Trail (No steps recorded)</b>",
            scene={
                "xaxis_title": "Step",
                "yaxis_title": "Layer",
                "zaxis_title": "Risk",
            },
        )
        return empty_fig

    # Pre-index findings by step
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

    ground_by_step: dict[int, list[dict[str, Any]]] = {}
    for f in findings.get("groundedness", []):
        ev = f.get("evidence_step_index") if f.get("evidence_step_index") is not None else f.get("evidence_step")
        if ev is not None:
            ground_by_step.setdefault(int(ev), []).append(f)

    layer_map = {
        "USER_INPUT": (1.0, "User Prompt"),
        "USER": (1.0, "User Prompt"),
        "ASSISTANT": (2.0, "Reasoning"),
        "ACTION": (2.0, "Reasoning"),
        "AGENT": (2.0, "Reasoning"),
        "TOOL_CALL": (3.0, "Tool Invocation"),
        "CALL": (3.0, "Tool Invocation"),
        "TOOL_RESULT": (4.0, "Observation"),
        "OBSERVATION": (4.0, "Observation"),
        "FINAL_ANSWER": (5.0, "Final Response"),
        "ANSWER": (5.0, "Final Response"),
    }

    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    labels: list[str] = []
    hover_texts: list[str] = []
    node_colors: list[str] = []
    node_sizes: list[int] = []

    for i, step in enumerate(timeline):
        step_idx = step.get("step_index", i)
        raw_type = str(step.get("type", "UNKNOWN")).upper()
        tool_name = step.get("tool_name", "")

        # Compute Y layer coordinate
        y_val, layer_name = layer_map.get(raw_type, (2.5, "Execution"))
        if tool_name:
            if "RESULT" in raw_type or "OBSERVATION" in raw_type:
                y_val, layer_name = 4.0, f"Tool Output ({tool_name})"
            else:
                y_val, layer_name = 3.0, f"Tool Call ({tool_name})"

        # Compute Z risk severity
        s_viol = scope_by_step.get(step_idx, [])
        p_viol = pii_by_step.get(step_idx, [])
        g_viol = ground_by_step.get(step_idx, [])

        if p_viol:
            z_val = 9.5
            color = "#ef4444"  # Red
            status_text = "CRITICAL PII LEAK"
            size = 14
        elif s_viol:
            z_val = 7.0
            color = "#f97316"  # Orange
            status_text = "SCOPE VIOLATION"
            size = 12
        elif g_viol:
            z_val = 5.0
            color = "#f59e0b"  # Amber
            status_text = "UNGROUNDED CLAIM"
            size = 12
        else:
            z_val = 1.0
            color = "#10b981"  # Emerald Green
            status_text = "COMPLIANT"
            size = 10

        xs.append(float(step_idx))
        ys.append(y_val)
        zs.append(z_val)
        node_colors.append(color)
        node_sizes.append(size)

        step_title = f"Step {step_idx}: {layer_name}"
        labels.append(step_title)

        snippet = step.get("content") or step.get("observation") or ""
        snippet_clean = (snippet[:100] + "...") if len(str(snippet)) > 100 else str(snippet)
        hover_html = (
            f"<b>{step_title}</b><br>"
            f"<b>Status:</b> {status_text}<br>"
            f"<b>Layer:</b> {layer_name}<br>"
            f"<b>Risk Level:</b> {z_val:.1f} / 10.0<br>"
            f"<b>Details:</b> {snippet_clean}"
        )
        hover_texts.append(hover_html)

    fig = go.Figure()

    # 1. 3D Trajectory Tube / Connecting Line
    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="lines",
            line={"color": "#38bdf8", "width": 5},
            name="Execution Path",
            hoverinfo="none",
        )
    )

    # 2. 3D State Nodes
    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="markers+text",
            marker={
                "size": node_sizes,
                "color": node_colors,
                "opacity": 0.95,
                "line": {"color": "#ffffff", "width": 1},
            },
            text=[f"S{int(x)}" for x in xs],
            textposition="top center",
            textfont={"color": "#e2e8f0", "size": 10},
            hovertext=hover_texts,
            hoverinfo="text",
            name="Steps",
        )
    )

    # Setup animation frames for step-by-step 3D trail replay
    frames = []
    for k in range(len(xs)):
        frame_trace_line = go.Scatter3d(
            x=xs[: k + 1],
            y=ys[: k + 1],
            z=zs[: k + 1],
            mode="lines",
            line={"color": "#38bdf8", "width": 6},
        )
        frame_trace_nodes = go.Scatter3d(
            x=xs[: k + 1],
            y=ys[: k + 1],
            z=zs[: k + 1],
            mode="markers+text",
            marker={
                "size": node_sizes[: k + 1],
                "color": node_colors[: k + 1],
                "opacity": 1.0,
                "line": {"color": "#ffffff", "width": 1},
            },
            text=[f"S{int(x)}" for x in xs[: k + 1]],
            textposition="top center",
            textfont={"color": "#ffffff", "size": 11},
            hovertext=hover_texts[: k + 1],
            hoverinfo="text",
        )
        frames.append(go.Frame(data=[frame_trace_line, frame_trace_nodes], name=f"step_{k}"))

    fig.frames = frames

    # Play/Pause and Step Controls
    sliders = [
        {
            "steps": [
                {
                    "method": "animate",
                    "args": [[f"step_{k}"], {"mode": "immediate", "frame": {"duration": 350, "redraw": True}}],
                    "label": f"Step {k}",
                }
                for k in range(len(xs))
            ],
            "active": len(xs) - 1,
            "transition": {"duration": 200},
            "x": 0.1,
            "y": 0,
            "currentvalue": {"font": {"size": 12, "color": "#94a3b8"}, "prefix": "Replay: ", "visible": True, "xanchor": "right"},
            "len": 0.85,
        }
    ]

    updatemenus = [
        {
            "type": "buttons",
            "showactive": False,
            "x": 0.0,
            "y": 0,
            "xanchor": "right",
            "yanchor": "top",
            "pad": {"t": 0, "r": 10},
            "buttons": [
                {
                    "label": "▶ Play",
                    "method": "animate",
                    "args": [None, {"frame": {"duration": 450, "redraw": True}, "fromcurrent": True, "transition": {"duration": 200}}],
                },
                {
                    "label": "⏸ Pause",
                    "method": "animate",
                    "args": [[None], {"mode": "immediate", "frame": {"duration": 0, "redraw": False}}],
                },
            ],
        }
    ]

    fig.update_layout(
        title="<b>Interactive 3D Agent Trail Replay</b> (Play / Pause / Rotate)",
        template="plotly_dark",
        paper_bgcolor="rgba(15, 23, 42, 0.9)",
        plot_bgcolor="rgba(15, 23, 42, 0.9)",
        margin={"l": 10, "r": 10, "b": 10, "t": 40},
        height=480,
        updatemenus=updatemenus,
        sliders=sliders,
        scene={
            "xaxis": {
                "title": "Execution Step",
                "backgroundcolor": "rgba(30, 41, 59, 0.6)",
                "gridcolor": "#334155",
                "showbackground": True,
                "zerolinecolor": "#475569",
            },
            "yaxis": {
                "title": "Execution Layer",
                "tickvals": [1.0, 2.0, 3.0, 4.0, 5.0],
                "ticktext": ["User", "Reasoning", "Tool Call", "Tool Result", "Answer"],
                "backgroundcolor": "rgba(30, 41, 59, 0.6)",
                "gridcolor": "#334155",
                "showbackground": True,
                "zerolinecolor": "#475569",
            },
            "zaxis": {
                "title": "Risk Severity (0-10)",
                "range": [0, 11],
                "backgroundcolor": "rgba(30, 41, 59, 0.6)",
                "gridcolor": "#334155",
                "showbackground": True,
                "zerolinecolor": "#475569",
            },
            "camera": {
                "eye": {"x": 1.65, "y": -1.55, "z": 0.95},
            },
            "aspectmode": "manual",
            "aspectratio": {"x": 1.8, "y": 1.2, "z": 0.8},
        },
    )
    return fig

