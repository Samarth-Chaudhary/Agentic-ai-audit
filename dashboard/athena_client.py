"""Athena service client for the Risk Analytics tab in the Streamlit Dashboard.

Executes predefined, sanitized SQL queries from analytics/sql/ and formats
results into Python dictionaries and pandas DataFrames.
Enforces query safety: strictly prohibits arbitrary user-injected SQL.
Supports rich offline demo datasets for reviewer inspection.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.athena_client import AthenaClient, AthenaClientError

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent.parent / "analytics" / "sql"

# -----------------------------------------------------------------------------
# Curated Analytical Demo Data for Dashboard Charts
# -----------------------------------------------------------------------------
DEMO_ANALYTICS: dict[str, list[dict[str, Any]]] = {
    "01_avg_risk_by_task": [
        {"task_type": "financial_reporting", "total_traces": 58, "avg_risk_score": 67.4, "min_risk_score": 10.0, "max_risk_score": 95.0},
        {"task_type": "financial_analysis", "total_traces": 44, "avg_risk_score": 48.2, "min_risk_score": 5.0, "max_risk_score": 85.0},
        {"task_type": "customer_support", "total_traces": 112, "avg_risk_score": 22.6, "min_risk_score": 0.0, "max_risk_score": 88.0},
    ],
    "02_risk_distribution": [
        {"risk_tier": "LOW", "trace_count": 118, "percentage_share": 55.14},
        {"risk_tier": "MEDIUM", "trace_count": 46, "percentage_share": 21.50},
        {"risk_tier": "HIGH", "trace_count": 32, "percentage_share": 14.95},
        {"risk_tier": "CRITICAL", "trace_count": 18, "percentage_share": 8.41},
    ],
    "03_high_risk_by_date": [
        {"date": "2026-09-23", "total_traces": 40, "high_or_critical_traces": 7, "high_risk_percentage": 17.5},
        {"date": "2026-09-24", "total_traces": 42, "high_or_critical_traces": 9, "high_risk_percentage": 21.43},
        {"date": "2026-09-25", "total_traces": 45, "high_or_critical_traces": 12, "high_risk_percentage": 26.67},
        {"date": "2026-09-26", "total_traces": 38, "high_or_critical_traces": 8, "high_risk_percentage": 21.05},
        {"date": "2026-09-27", "total_traces": 49, "high_or_critical_traces": 14, "high_risk_percentage": 28.57},
    ],
    "04_scope_violations_by_task": [
        {"task_type": "financial_reporting", "total_traces": 58, "total_scope_violations": 19, "traces_with_violations": 15, "violation_rate_percentage": 25.86},
        {"task_type": "customer_support", "total_traces": 112, "total_scope_violations": 11, "traces_with_violations": 9, "violation_rate_percentage": 8.04},
        {"task_type": "financial_analysis", "total_traces": 44, "total_scope_violations": 5, "traces_with_violations": 4, "violation_rate_percentage": 9.09},
    ],
    "05_pii_by_task": [
        {"task_type": "customer_support", "total_traces": 112, "total_pii_entities": 34, "traces_with_pii": 21, "pii_leakage_rate_percentage": 18.75},
        {"task_type": "financial_reporting", "total_traces": 58, "total_pii_entities": 14, "traces_with_pii": 8, "pii_leakage_rate_percentage": 13.79},
        {"task_type": "financial_analysis", "total_traces": 44, "total_pii_entities": 4, "traces_with_pii": 3, "pii_leakage_rate_percentage": 6.82},
    ],
    "06_groundedness_failures": [
        {"task_type": "financial_analysis", "total_traces": 44, "total_groundedness_failures": 24, "total_unsupported_claims": 16, "total_contradicted_claims": 8, "traces_with_hallucinations": 14, "hallucination_rate_percentage": 31.82},
        {"task_type": "financial_reporting", "total_traces": 58, "total_groundedness_failures": 21, "total_unsupported_claims": 14, "total_contradicted_claims": 7, "traces_with_hallucinations": 13, "hallucination_rate_percentage": 22.41},
        {"task_type": "customer_support", "total_traces": 112, "total_groundedness_failures": 10, "total_unsupported_claims": 8, "total_contradicted_claims": 2, "traces_with_hallucinations": 8, "hallucination_rate_percentage": 7.14},
    ],
    "07_unsupported_claims": [
        {"date": "2026-09-27", "task_type": "financial_analysis", "total_traces": 12, "total_unsupported_claims": 6, "avg_unsupported_claims_per_trace": 0.50},
        {"date": "2026-09-27", "task_type": "financial_reporting", "total_traces": 14, "total_unsupported_claims": 5, "avg_unsupported_claims_per_trace": 0.36},
        {"date": "2026-09-26", "task_type": "financial_analysis", "total_traces": 10, "total_unsupported_claims": 4, "avg_unsupported_claims_per_trace": 0.40},
        {"date": "2026-09-25", "task_type": "customer_support", "total_traces": 22, "total_unsupported_claims": 3, "avg_unsupported_claims_per_trace": 0.14},
    ],
    "08_contradicted_claims": [
        {"date": "2026-09-27", "task_type": "financial_analysis", "trace_id": "tr-demo-c1", "risk_score": 88.0, "risk_tier": "CRITICAL", "contradicted_claims": 2, "summary": "Direct contradiction regarding EPS and reported growth."},
        {"date": "2026-09-27", "task_type": "financial_reporting", "trace_id": "tr-demo-c2", "risk_score": 92.5, "risk_tier": "CRITICAL", "contradicted_claims": 1, "summary": "Fabricated guidance figures contradicting SEC filing."},
        {"date": "2026-09-26", "task_type": "financial_analysis", "trace_id": "tr-demo-c3", "risk_score": 75.0, "risk_tier": "HIGH", "contradicted_claims": 1, "summary": "Stated delivery confirmed when tool returned cancellation."},
    ],
    "09_daily_risk_trend": [
        {"date": "2026-09-23", "daily_trace_count": 40, "daily_avg_risk": 28.5, "daily_scope_violations": 4, "daily_pii_detections": 6, "daily_groundedness_failures": 7, "daily_high_risk_ratio": 17.5},
        {"date": "2026-09-24", "daily_trace_count": 42, "daily_avg_risk": 32.1, "daily_scope_violations": 5, "daily_pii_detections": 8, "daily_groundedness_failures": 9, "daily_high_risk_ratio": 21.43},
        {"date": "2026-09-25", "daily_trace_count": 45, "daily_avg_risk": 38.6, "daily_scope_violations": 8, "daily_pii_detections": 12, "daily_groundedness_failures": 14, "daily_high_risk_ratio": 26.67},
        {"date": "2026-09-26", "daily_trace_count": 38, "daily_avg_risk": 31.4, "daily_scope_violations": 6, "daily_pii_detections": 9, "daily_groundedness_failures": 10, "daily_high_risk_ratio": 21.05},
        {"date": "2026-09-27", "daily_trace_count": 49, "daily_avg_risk": 41.2, "daily_scope_violations": 12, "daily_pii_detections": 17, "daily_groundedness_failures": 15, "daily_high_risk_ratio": 28.57},
    ],
    "10_tool_violation_analysis": [
        {"tool_name": "bash_command_runner", "violation_count": 14, "impacted_traces": 12, "avg_risk_when_violated": 91.5},
        {"tool_name": "web_search", "violation_count": 11, "impacted_traces": 9, "avg_risk_when_violated": 58.2},
        {"tool_name": "external_api_requester", "violation_count": 7, "impacted_traces": 5, "avg_risk_when_violated": 74.0},
        {"tool_name": "delete_customer_record", "violation_count": 3, "impacted_traces": 3, "avg_risk_when_violated": 98.0},
    ],
}


class DashboardAthenaService:
    """Manages predefined Athena queries for the Streamlit dashboard."""

    def __init__(
        self,
        athena_client: AthenaClient | None = None,
        demo_mode: bool = False,
    ) -> None:
        """Initialize service.

        Args:
            athena_client: Optional injected AthenaClient.
            demo_mode: If True, uses local demo datasets instead of submitting AWS queries.
        """
        env_demo = os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")
        self.demo_mode = demo_mode or env_demo or (athena_client is None and not os.environ.get("AWS_EXECUTION_ENV"))
        self._client = athena_client if not self.demo_mode else None

    def run_named_query(self, query_name: str) -> pd.DataFrame:
        """Execute a predefined SQL file by name safely.

        Prohibits raw SQL injection by only executing mapped queries.

        Args:
            query_name: Name of query (e.g. '01_avg_risk_by_task' or '01_avg_risk_by_task.sql').

        Returns:
            pandas DataFrame containing the query results.
        """
        clean_name = query_name.replace(".sql", "")

        # Fallback to local demo dataset if in demo mode or offline
        if self.demo_mode:
            if clean_name in DEMO_ANALYTICS:
                return pd.DataFrame(DEMO_ANALYTICS[clean_name])
            raise KeyError(f"Unknown predefined query '{query_name}' in demo dataset")

        # Live Execution via AthenaClient
        sql_file = SQL_DIR / f"{clean_name}.sql"
        if not sql_file.exists():
            raise FileNotFoundError(f"Predefined query file not found: {sql_file}")

        query_text = sql_file.read_text(encoding="utf-8").strip()
        client = self._client or AthenaClient()
        try:
            records = client.execute_query(query_text, timeout_seconds=45.0)
            return pd.DataFrame(records)
        except AthenaClientError as exc:
            logger.error("Athena execution failed for query '%s': %s", query_name, exc)
            raise RuntimeError(f"Athena Query Failed: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error executing '%s': %s", query_name, exc)
            raise RuntimeError(f"Query Service Error: {exc}") from exc

    def get_all_analytics_tables(self) -> dict[str, pd.DataFrame]:
        """Load results for all 10 predefined analytical queries."""
        results: dict[str, pd.DataFrame] = {}
        for key in DEMO_ANALYTICS:
            try:
                results[key] = self.run_named_query(key)
            except Exception as exc:
                logger.warning("Could not execute query %s: %s", key, exc)
                results[key] = pd.DataFrame()
        return results
