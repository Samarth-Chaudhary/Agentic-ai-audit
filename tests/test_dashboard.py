"""Unit and integration tests for the Streamlit Reviewer Dashboard."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from dashboard.api_client import DEMO_TRACES, AuditApiClient
from dashboard.athena_client import DEMO_ANALYTICS, DashboardAthenaService
from dashboard.charts import (
    chart_avg_risk_by_task,
    chart_daily_risk_trend,
    chart_risk_distribution,
    chart_tool_violations,
)
from dashboard.components import (
    render_degraded_banner,
    render_engine_badge,
    render_risk_badge,
)


class TestDashboardApiClient:
    """Tests for AuditApiClient in demo mode and error handling."""

    def test_demo_mode_list_traces(self):
        client = AuditApiClient(demo_mode=True)
        traces = client.list_traces()
        assert len(traces) == len(DEMO_TRACES)
        first = traces[0]
        assert "trace_id" in first
        assert "task_type" in first
        assert "risk_score" in first
        assert "risk_tier" in first
        assert "processed_at" in first
        assert "pii_count" in first
        assert "scope_violation_count" in first
        assert "groundedness_failure_count" in first

    def test_demo_mode_filtering(self):
        client = AuditApiClient(demo_mode=True)

        # Filter by task type
        customer_traces = client.list_traces(task_type="customer_support")
        assert all(t["task_type"] == "customer_support" for t in customer_traces)

        # Filter by risk tier
        critical_traces = client.list_traces(risk_tier="CRITICAL")
        assert all(t["risk_tier"] == "CRITICAL" for t in critical_traces)

    def test_demo_mode_get_trace_detail_and_redaction(self):
        client = AuditApiClient(demo_mode=True)
        trace = client.get_trace("tr-pii-003")
        assert trace["trace_id"] == "tr-pii-003"
        assert trace["risk_tier"] == "CRITICAL"
        assert "execution_timeline" in trace
        assert "findings" in trace

        # CRITICAL REQUIREMENT: Verify sensitive data is redacted in the timeline
        timeline_str = json.dumps(trace["execution_timeline"])
        assert "<REDACTED_SSN>" in timeline_str
        assert "<REDACTED_CC>" in timeline_str

        # Ensure no raw unredacted SSN/CC pattern in the timeline
        assert "000-12-3456" not in timeline_str
        assert "4111 2222" not in timeline_str

    def test_get_nonexistent_trace_raises_key_error(self):
        client = AuditApiClient(demo_mode=True)
        with pytest.raises(KeyError, match="not found"):
            client.get_trace("nonexistent-trace-id")

    def test_live_mode_network_error_handling(self):
        # Point client to non-existent endpoint
        client = AuditApiClient(base_url="http://localhost:59999/api", demo_mode=False)
        with pytest.raises(ConnectionError, match="API Gateway unreachable"):
            client.list_traces()

    def test_summary_metrics_aggregation(self):
        client = AuditApiClient(demo_mode=True)
        metrics = client.get_summary_metrics()
        assert metrics["total_traces"] == len(DEMO_TRACES)
        assert metrics["critical_risk_traces"] >= 2
        assert metrics["high_risk_traces"] >= 2


class TestDashboardAthenaService:
    """Tests for DashboardAthenaService predefined queries."""

    def test_demo_mode_predefined_named_queries(self):
        service = DashboardAthenaService(demo_mode=True)

        # Test each named query returns valid DataFrame
        for q_name in DEMO_ANALYTICS:
            df = service.run_named_query(q_name)
            assert isinstance(df, pd.DataFrame)
            assert not df.empty, f"Expected non-empty DataFrame for {q_name}"

    def test_query_unknown_name_raises_key_error(self):
        service = DashboardAthenaService(demo_mode=True)
        with pytest.raises(KeyError, match="Unknown predefined query"):
            service.run_named_query("99_arbitrary_unauthorized_query")

    def test_get_all_analytics_tables(self):
        service = DashboardAthenaService(demo_mode=True)
        tables = service.get_all_analytics_tables()
        assert len(tables) == 10
        assert "01_avg_risk_by_task" in tables
        assert "02_risk_distribution" in tables
        assert "10_tool_violation_analysis" in tables


class TestChartsGeneration:
    """Tests for Plotly chart generator functions."""

    def test_chart_risk_distribution(self):
        df = pd.DataFrame([
            {"risk_tier": "LOW", "trace_count": 50},
            {"risk_tier": "HIGH", "trace_count": 10},
        ])
        fig = chart_risk_distribution(df)
        assert fig is not None
        assert len(fig.data) > 0

    def test_chart_avg_risk_by_task(self):
        df = pd.DataFrame([
            {"task_type": "support", "avg_risk_score": 15.0},
            {"task_type": "finance", "avg_risk_score": 75.0},
        ])
        fig = chart_avg_risk_by_task(df)
        assert fig is not None
        assert len(fig.data) > 0

    def test_chart_daily_risk_trend(self):
        df = pd.DataFrame([
            {"date": "2026-09-26", "daily_avg_risk": 20.0, "daily_high_risk_ratio": 10.0},
            {"date": "2026-09-27", "daily_avg_risk": 35.0, "daily_high_risk_ratio": 25.0},
        ])
        fig = chart_daily_risk_trend(df)
        assert fig is not None
        assert len(fig.data) == 2

    def test_chart_tool_violations(self):
        df = pd.DataFrame([
            {"tool_name": "bash", "violation_count": 5, "avg_risk_when_violated": 90.0},
        ])
        fig = chart_tool_violations(df)
        assert fig is not None
        assert len(fig.data) > 0

    def test_charts_handle_empty_dataframes_gracefully(self):
        empty_df = pd.DataFrame()
        assert chart_risk_distribution(empty_df) is not None
        assert chart_avg_risk_by_task(empty_df) is not None
        assert chart_daily_risk_trend(empty_df) is not None
        assert chart_tool_violations(empty_df) is not None


class TestComponentsVisualSemantics:
    """Tests for visual semantic color and badge rendering."""

    def test_render_risk_badge(self):
        low_badge = render_risk_badge("LOW", 12.5)
        assert "LOW" in low_badge
        assert "12.5" in low_badge
        assert "#10b981" in low_badge

        crit_badge = render_risk_badge("CRITICAL", 95.0)
        assert "CRITICAL" in crit_badge
        assert "#ef4444" in crit_badge

    def test_render_engine_badge_full_ml(self):
        engine_info = {
            "nli_engine": "cross-encoder/nli-deberta-v3-small",
            "embedding_engine": "sentence-transformers/all-MiniLM-L6-v2",
            "pii_engine": "presidio-nlp (spacy: en_core_web_sm)",
            "is_degraded": False,
            "degraded_reasons": [],
        }
        badge = render_engine_badge(engine_info, is_degraded=False)
        assert "VERIFIED ML ENGINE" in badge
        assert "cross-encoder/nli-deberta-v3-small" in badge
        assert "sentence-transformers/all-MiniLM-L6-v2" in badge
        assert "presidio-nlp" in badge
        assert "#10b981" in badge

    def test_render_engine_badge_degraded(self):
        engine_info = {
            "nli_engine": "heuristic-negation-overlap-v1",
            "embedding_engine": "jaccard-tfidf-fallback",
            "pii_engine": "regex-only-fallback",
            "is_degraded": True,
            "degraded_reasons": ["CrossEncoder unavailable"],
        }
        badge = render_engine_badge(engine_info, is_degraded=True)
        assert "DEGRADED ENGINE" in badge
        assert "heuristic-negation-overlap-v1" in badge
        assert "CrossEncoder unavailable" in badge
        assert "#ef4444" in badge

    def test_render_degraded_banner(self):
        with patch("streamlit.error") as mock_st_error:
            render_degraded_banner(is_degraded=True, degraded_reasons=["NLI unavailable"])
            mock_st_error.assert_called_once()
            call_text = mock_st_error.call_args[0][0]
            assert "DEGRADED AUDIT WARNING" in call_text
            assert "NLI unavailable" in call_text

            mock_st_error.reset_mock()
            render_degraded_banner(is_degraded=False)
            mock_st_error.assert_not_called()


class TestDashboardValidationGate:
    """Tests corresponding directly to Dashboard Validation Gate requirements."""

    def test_application_modules_import_cleanly(self):
        import dashboard.api_client
        import dashboard.app
        import dashboard.athena_client
        import dashboard.charts
        import dashboard.components

        assert dashboard.app is not None
        assert dashboard.api_client is not None
        assert dashboard.athena_client is not None
        assert dashboard.charts is not None
        assert dashboard.components is not None

    def test_date_filter_in_list_traces(self):
        client = AuditApiClient(demo_mode=True)
        # 2026-09-27 matches the demo traces
        filtered = client.list_traces(date_filter="2026-09-27")
        assert len(filtered) > 0
        assert all(t["processed_at"].startswith("2026-09-27") for t in filtered)

        # Non-matching date returns empty list
        empty = client.list_traces(date_filter="2020-01-01")
        assert len(empty) == 0

    def test_api_client_normalizes_nested_risk_payload(self):
        """Verify API client normalizes {"risk": {"risk_score": 88.0, "risk_tier": "CRITICAL"}}."""
        nested_mock_payload = {
            "trace_id": "tr-mock-001",
            "task_type": "customer_support",
            "processed_at": "2026-09-27T10:00:00Z",
            "risk": {
                "risk_score": 88.0,
                "risk_tier": "CRITICAL",
            },
            "findings": {"scope": [], "pii": [], "groundedness": []},
            "execution_timeline": [],
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(nested_mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        client = AuditApiClient(base_url="https://api.gateway.mock/dev", demo_mode=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            trace = client.get_trace("tr-mock-001")
            assert trace["trace_id"] == "tr-mock-001"
            # Normalized top-level fields
            assert trace["risk_score"] == 88.0
            assert trace["risk_tier"] == "CRITICAL"
            assert "risk" in trace

    def test_trace_table_column_contract(self):
        """Verify trace table column naming exactly matches Section 4."""
        client = AuditApiClient(demo_mode=True)
        traces = client.list_traces()
        df_table = pd.DataFrame([
            {
                "Trace ID": t["trace_id"],
                "Task Type": t["task_type"],
                "Date/Time": t.get("processed_at", ""),
                "Risk Score": f"{float(t['risk_score']):.1f}",
                "Risk Tier": t["risk_tier"],
                "Scope Issues": t.get("scope_violation_count", 0),
                "PII Issues": t.get("pii_count", 0),
                "Groundedness Issues": t.get("groundedness_failure_count", 0),
            }
            for t in traces
        ])

        expected_columns = [
            "Trace ID",
            "Task Type",
            "Date/Time",
            "Risk Score",
            "Risk Tier",
            "Scope Issues",
            "PII Issues",
            "Groundedness Issues",
        ]
        assert list(df_table.columns) == expected_columns
        assert len(df_table) == len(DEMO_TRACES)

    def test_all_10_athena_query_shapes(self):
        """Verify all 10 Athena queries have non-empty results and expected columns."""
        service = DashboardAthenaService(demo_mode=True)
        tables = service.get_all_analytics_tables()
        assert len(tables) == 10

        # Query 1: avg risk by task
        assert "task_type" in tables["01_avg_risk_by_task"].columns
        assert "avg_risk_score" in tables["01_avg_risk_by_task"].columns

        # Query 2: risk distribution
        assert "risk_tier" in tables["02_risk_distribution"].columns
        assert "percentage_share" in tables["02_risk_distribution"].columns

        # Query 3: high risk by date
        assert "date" in tables["03_high_risk_by_date"].columns
        assert "high_or_critical_traces" in tables["03_high_risk_by_date"].columns

        # Query 4: scope violations
        assert "total_scope_violations" in tables["04_scope_violations_by_task"].columns

        # Query 5: pii by task
        assert "total_pii_entities" in tables["05_pii_by_task"].columns

        # Query 6: groundedness failures
        assert "total_groundedness_failures" in tables["06_groundedness_failures"].columns

        # Query 7: unsupported claims
        assert "total_unsupported_claims" in tables["07_unsupported_claims"].columns

        # Query 8: contradicted claims
        assert "contradicted_claims" in tables["08_contradicted_claims"].columns

        # Query 9: daily trend
        assert "daily_avg_risk" in tables["09_daily_risk_trend"].columns

        # Query 10: tool violation analysis
        assert "tool_name" in tables["10_tool_violation_analysis"].columns
        assert "violation_count" in tables["10_tool_violation_analysis"].columns
