"""Plotly charting utilities for the Risk Analytics tab."""

from __future__ import annotations

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
