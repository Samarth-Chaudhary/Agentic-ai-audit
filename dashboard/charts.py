"""Monochrome Plotly charting utilities matching the iDraft Bento aesthetic."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Strict monochrome palette with functional status colors
TIER_COLORS = {
    "LOW": "#10B981",       # Emerald / Compliant
    "MEDIUM": "#F59E0B",    # Amber / Warning
    "HIGH": "#737373",      # Graphite / High Risk
    "CRITICAL": "#171717",  # Near-Black / Critical Risk
}


def chart_risk_distribution(df: pd.DataFrame) -> go.Figure:
    """Render high-contrast ring/donut chart of trace distribution across risk tiers."""
    if df.empty or "risk_tier" not in df.columns:
        return go.Figure()

    total_traces = int(df["trace_count"].sum()) if "trace_count" in df.columns else 0

    fig = px.pie(
        df,
        names="risk_tier",
        values="trace_count",
        color="risk_tier",
        color_discrete_map=TIER_COLORS,
        hole=0.70,
        title="<b>Risk Tier Distribution</b>",
    )
    fig.update_traces(
        textinfo="percent",
        hoverinfo="label+value+percent",
        textfont={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "size": 12, "color": "#111111"},
        marker={"line": {"color": "#FFFFFF", "width": 3}},
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "color": "#111111"},
        title_font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "size": 15, "color": "#111111"},
        margin={"t": 45, "b": 10, "l": 10, "r": 10},
        height=280,
        showlegend=True,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": -0.15,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 11, "color": "#737373"},
        },
        annotations=[
            {
                "text": f"<b>{total_traces}</b><br><span style='font-size:11px;color:#737373;'>Traces</span>",
                "x": 0.5,
                "y": 0.5,
                "font": {"size": 22, "family": "'Plus Jakarta Sans', sans-serif", "color": "#111111"},
                "showarrow": False,
            }
        ],
    )
    return fig


def chart_avg_risk_by_task(df: pd.DataFrame) -> go.Figure:
    """Render horizontal bar chart of average risk score per task type in monochrome styling."""
    if df.empty or "task_type" not in df.columns:
        return go.Figure()

    fig = px.bar(
        df,
        x="avg_risk_score",
        y="task_type",
        orientation="h",
        title="<b>Average Risk Score by Task Type</b>",
        labels={"avg_risk_score": "Average Risk Score (0-100)", "task_type": "Task Type"},
        text="avg_risk_score",
        color_discrete_sequence=["#171717"],
    )
    fig.update_traces(
        texttemplate="%{text:.1f}",
        textposition="outside",
        textfont={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "size": 12, "color": "#111111"},
        marker={"line": {"color": "#171717", "width": 1}},
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "color": "#111111"},
        title_font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "size": 15, "color": "#111111"},
        margin={"t": 45, "b": 20, "l": 20, "r": 20},
        height=280,
    )
    fig.update_xaxes(
        gridcolor="rgba(0, 0, 0, 0.05)",
        tickfont={"family": "'Plus Jakarta Sans', sans-serif", "color": "#737373"},
        title_font={"family": "'Plus Jakarta Sans', sans-serif", "color": "#111111", "size": 12},
        range=[0, 105],
    )
    fig.update_yaxes(
        tickfont={"family": "'Plus Jakarta Sans', sans-serif", "color": "#111111", "size": 12},
        title_font={"family": "'Plus Jakarta Sans', sans-serif", "color": "#111111", "size": 12},
    )
    return fig


def chart_daily_risk_trend(df: pd.DataFrame) -> go.Figure:
    """Render smooth spline area/line chart matching reference 'Weekly progress' aesthetic."""
    if df.empty or "date" not in df.columns:
        return go.Figure()

    fig = go.Figure()

    # Smooth dark line with area gradient
    if "daily_avg_risk" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["daily_avg_risk"],
                mode="lines",
                name="Avg Risk Score",
                line={"color": "#171717", "width": 3, "shape": "spline"},
                fill="tozeroy",
                fillcolor="rgba(23, 23, 23, 0.04)",
            )
        )

    annotations = []
    if "daily_avg_risk" in df.columns and not df.empty:
        max_idx = df["daily_avg_risk"].idxmax()
        peak_row = df.loc[max_idx]
        annotations.append({
            "x": peak_row["date"],
            "y": peak_row["daily_avg_risk"],
            "text": f"<b>+{peak_row['daily_avg_risk']:.0f}% Peak</b>",
            "showarrow": True,
            "arrowhead": 0,
            "ax": 0,
            "ay": -28,
            "bgcolor": "#171717",
            "font": {"family": "'Plus Jakarta Sans', sans-serif", "size": 11, "color": "#FFFFFF"},
            "borderpad": 4,
            "bordercolor": "#171717",
            "borderwidth": 1,
            "arrowcolor": "#171717",
        })

    # High-Risk ratio line
    if "daily_high_risk_ratio" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["daily_high_risk_ratio"],
                mode="lines",
                name="High Risk %",
                line={"color": "#737373", "width": 2, "dash": "dot", "shape": "spline"},
            )
        )

    fig.update_layout(
        title="<b>Daily Risk Trend & Violation Volume</b>",
        annotations=annotations,
        xaxis_title="",
        yaxis_title="Risk Score / Ratio",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "color": "#111111"},
        title_font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "size": 15, "color": "#111111"},
        margin={"t": 45, "b": 20, "l": 20, "r": 20},
        height=280,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"family": "'Plus Jakarta Sans', sans-serif", "color": "#737373", "size": 11},
        },
    )
    fig.update_xaxes(
        gridcolor="rgba(0, 0, 0, 0.04)",
        tickfont={"family": "'Plus Jakarta Sans', sans-serif", "color": "#737373", "size": 11},
    )
    fig.update_yaxes(
        gridcolor="rgba(0, 0, 0, 0.04)",
        tickfont={"family": "'Plus Jakarta Sans', sans-serif", "color": "#737373", "size": 11},
    )
    return fig


def chart_tool_violations(df: pd.DataFrame) -> go.Figure:
    """Render clean monochrome bar chart of tool-level violation counts."""
    if df.empty or "tool_name" not in df.columns:
        return go.Figure()

    fig = px.bar(
        df,
        x="tool_name",
        y="violation_count",
        title="<b>Tool-Level Violation Frequency</b>",
        labels={
            "tool_name": "Invoked Tool",
            "violation_count": "Total Violations",
        },
        text="violation_count",
        color_discrete_sequence=["#171717"],
    )
    fig.update_traces(
        textposition="outside",
        textfont={"family": "'Plus Jakarta Sans', sans-serif", "size": 11, "color": "#111111"},
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "color": "#111111"},
        title_font={"family": "'Plus Jakarta Sans', 'Inter', sans-serif", "size": 15, "color": "#111111"},
        margin={"t": 45, "b": 20, "l": 20, "r": 20},
        height=280,
    )
    fig.update_xaxes(
        gridcolor="rgba(0, 0, 0, 0.04)",
        tickfont={"family": "'Plus Jakarta Sans', sans-serif", "color": "#737373"},
        title_font={"family": "'Plus Jakarta Sans', sans-serif", "color": "#111111", "size": 12},
    )
    fig.update_yaxes(
        gridcolor="rgba(0, 0, 0, 0.04)",
        tickfont={"family": "'Plus Jakarta Sans', sans-serif", "color": "#737373"},
        title_font={"family": "'Plus Jakarta Sans', sans-serif", "color": "#111111", "size": 12},
    )
    return fig


def chart_3d_trail_replay(
    timeline: list[dict[str, Any]],
    findings: dict[str, list[dict[str, Any]]],
) -> go.Figure:
    """Render interactive 3D execution trail replay in high-contrast dark space."""
    if not timeline:
        return go.Figure()

    layer_map = {
        "user_message": 0,
        "assistant_message": 1,
        "tool_call": 2,
        "tool_result": 3,
        "final_answer": 4,
    }
    layer_names = ["User Message", "Agent Reasoning", "Tool Call", "Tool Observation", "Final Answer"]

    # Extract coordinates
    x_steps = []
    y_layers = []
    z_risks = []
    hover_texts = []
    marker_colors = []

    scope_findings = findings.get("scope", [])
    pii_findings = findings.get("pii", [])
    groundedness_findings = findings.get("groundedness", [])

    for idx, step in enumerate(timeline):
        s_idx = step.get("step_index", idx)
        s_type = step.get("type", "assistant_message")
        y_val = layer_map.get(s_type, 1)

        # Risk severity computation (0-10)
        has_scope = any(f.get("step_index") == s_idx for f in scope_findings)
        has_pii = any(f.get("step_index") == s_idx for f in pii_findings)
        has_ground = any(f.get("evidence_step_index") == s_idx for f in groundedness_findings)

        if has_pii:
            z_val = 10.0
            color = "#EF4444"
        elif has_scope:
            z_val = 7.5
            color = "#F59E0B"
        elif has_ground:
            z_val = 5.0
            color = "#F59E0B"
        else:
            z_val = 0.5
            color = "#10B981"

        x_steps.append(s_idx)
        y_layers.append(y_val)
        z_risks.append(z_val)
        marker_colors.append(color)

        desc = step.get("content") or step.get("tool_name") or s_type
        hover_texts.append(f"Step {s_idx}: {s_type}<br>{desc}<br>Risk Level: {z_val}/10")

    fig = go.Figure()

    # Trajectory 3D path line
    fig.add_trace(
        go.Scatter3d(
            x=x_steps,
            y=y_layers,
            z=z_risks,
            mode="lines",
            name="Execution Path",
            line={"color": "#FFFFFF", "width": 4},
            hoverinfo="none",
        )
    )

    # 3D Node markers
    fig.add_trace(
        go.Scatter3d(
            x=x_steps,
            y=y_layers,
            z=z_risks,
            mode="markers+text",
            name="Audit Steps",
            text=[f"S{i}" for i in x_steps],
            textposition="top center",
            textfont={"size": 10, "color": "#FFFFFF"},
            marker={"size": 7, "color": marker_colors, "symbol": "circle", "line": {"color": "#171717", "width": 1}},
            hovertext=hover_texts,
            hoverinfo="text",
        )
    )

    fig.update_layout(
        title="<b>Interactive 3D Agent Trajectory & State Space</b>",
        paper_bgcolor="#171717",
        plot_bgcolor="#171717",
        font={"family": "'Plus Jakarta Sans', sans-serif", "color": "#FFFFFF"},
        title_font={"size": 15, "color": "#FFFFFF"},
        margin={"t": 50, "b": 20, "l": 20, "r": 20},
        height=480,
        scene={
            "xaxis": {
                "title": {"text": "Step Sequence (X)", "font": {"color": "#FFFFFF"}},
                "backgroundcolor": "#171717",
                "gridcolor": "#333333",
                "tickfont": {"color": "#999999"},
            },
            "yaxis": {
                "title": {"text": "Layer (Y)", "font": {"color": "#FFFFFF"}},
                "tickvals": [0, 1, 2, 3, 4],
                "ticktext": layer_names,
                "backgroundcolor": "#171717",
                "gridcolor": "#333333",
                "tickfont": {"color": "#999999"},
            },
            "zaxis": {
                "title": {"text": "Risk Severity (Z)", "font": {"color": "#FFFFFF"}},
                "range": [0, 11],
                "backgroundcolor": "#171717",
                "gridcolor": "#333333",
                "tickfont": {"color": "#999999"},
            },
            "camera": {"eye": {"x": 1.6, "y": -1.6, "z": 1.2}},
        },
    )
    return fig
