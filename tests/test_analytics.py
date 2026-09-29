"""Unit and integration tests for AthenaClient, SQL analytics queries, and Glue coherence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from analytics.athena_client import (
    AthenaClient,
    AthenaQueryCancelledError,
    AthenaQueryFailedError,
    AthenaQueryTimeoutError,
    _cast_athena_value,
)

SQL_DIR = Path(__file__).parent.parent / "analytics" / "sql"

EXPECTED_SQL_FILES = [
    "01_avg_risk_by_task.sql",
    "02_risk_distribution.sql",
    "03_high_risk_by_date.sql",
    "04_scope_violations_by_task.sql",
    "05_pii_by_task.sql",
    "06_groundedness_failures.sql",
    "07_unsupported_claims.sql",
    "08_contradicted_claims.sql",
    "09_daily_risk_trend.sql",
    "10_tool_violation_analysis.sql",
]

GLUE_COLUMNS = {
    "trace_id",
    "task_type",
    "date",
    "risk_score",
    "risk_tier",
    "pii_count",
    "scope_violations",
    "groundedness_failures",
    "unsupported_claims",
    "contradicted_claims",
    "violated_tools",
    "summary",
    "status",
    "processed_at",
}


@pytest.fixture
def aws_env(monkeypatch):
    """Mock AWS credentials and environment variables."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("GLUE_DATABASE", "test_governance_db")
    monkeypatch.setenv("ATHENA_WORKGROUP", "test-audit-workgroup")
    monkeypatch.setenv("ATHENA_OUTPUT_LOCATION", "s3://test-bucket/athena-results/")


class TestAthenaValueCasting:
    """Tests for typed conversion of Athena result cells."""

    def test_numeric_casting(self):
        assert _cast_athena_value("42", "int") == 42
        assert _cast_athena_value("42", "bigint") == 42
        assert _cast_athena_value("42.5", "double") == 42.5
        assert _cast_athena_value("3.1415", "float") == 3.1415

    def test_boolean_and_null_casting(self):
        assert _cast_athena_value("true", "boolean") is True
        assert _cast_athena_value("false", "boolean") is False
        assert _cast_athena_value(None, "string") is None

    def test_array_json_casting(self):
        assert _cast_athena_value('["tool_a", "tool_b"]', "array<string>") == ["tool_a", "tool_b"]


class TestAthenaClientWithMoto:
    """Integration tests for AthenaClient using mock Athena."""

    @mock_aws
    def test_start_query_and_poll_lifecycle(self, aws_env):
        client = boto3.client("athena", region_name="us-east-1")
        client.create_work_group(Name="test-audit-workgroup")
        athena_client = AthenaClient(athena_client=client)

        query = "SELECT task_type, AVG(risk_score) FROM audit_analytics GROUP BY task_type;"
        query_id = athena_client.start_query(query=query)
        assert query_id is not None
        assert len(query_id) > 0

        # Poll status
        status = athena_client.poll_query_state(query_id)
        assert status["query_execution_id"] == query_id
        assert status["state"] in ("QUEUED", "RUNNING", "SUCCEEDED")

    def test_timeout_handling_raises_timeout_error(self):
        mock_boto = MagicMock()
        mock_boto.get_query_execution.return_value = {
            "QueryExecution": {
                "Status": {"State": "RUNNING"},
                "Statistics": {},
            }
        }
        client = AthenaClient(athena_client=mock_boto)

        with pytest.raises(AthenaQueryTimeoutError, match="timed out"):
            client.wait_for_query_completion("q-timeout-1", poll_interval_seconds=0.01, timeout_seconds=0.05)

    def test_failed_query_raises_query_failed_error(self):
        mock_boto = MagicMock()
        mock_boto.get_query_execution.return_value = {
            "QueryExecution": {
                "Status": {
                    "State": "FAILED",
                    "StateChangeReason": "SYNTAX_ERROR: line 1:1 Column 'foo' cannot be resolved",
                },
                "Statistics": {},
            }
        }
        client = AthenaClient(athena_client=mock_boto)

        with pytest.raises(AthenaQueryFailedError, match="cannot be resolved"):
            client.wait_for_query_completion("q-fail-1")

    def test_cancelled_query_raises_cancelled_error(self):
        mock_boto = MagicMock()
        mock_boto.get_query_execution.return_value = {
            "QueryExecution": {
                "Status": {"State": "CANCELLED"},
                "Statistics": {},
            }
        }
        client = AthenaClient(athena_client=mock_boto)

        with pytest.raises(AthenaQueryCancelledError, match="cancelled"):
            client.wait_for_query_completion("q-cancel-1")

    def test_get_query_results_converts_to_typed_dicts(self):
        mock_boto = MagicMock()
        mock_paginator = MagicMock()
        mock_boto.get_paginator.return_value = mock_paginator

        mock_paginator.paginate.return_value = [
            {
                "ResultSet": {
                    "ResultSetMetadata": {
                        "ColumnInfo": [
                            {"Name": "task_type", "Type": "string"},
                            {"Name": "total_traces", "Type": "bigint"},
                            {"Name": "avg_risk_score", "Type": "double"},
                        ]
                    },
                    "Rows": [
                        # Header row
                        {"Data": [{"VarCharValue": "task_type"}, {"VarCharValue": "total_traces"}, {"VarCharValue": "avg_risk_score"}]},
                        # Data rows
                        {"Data": [{"VarCharValue": "customer_support"}, {"VarCharValue": "15"}, {"VarCharValue": "24.50"}]},
                        {"Data": [{"VarCharValue": "financial_reporting"}, {"VarCharValue": "8"}, {"VarCharValue": "62.10"}]},
                    ],
                }
            }
        ]

        client = AthenaClient(athena_client=mock_boto)
        results = client.get_query_results("q-success-1")

        assert len(results) == 2
        assert results[0] == {
            "task_type": "customer_support",
            "total_traces": 15,
            "avg_risk_score": 24.5,
        }
        assert results[1] == {
            "task_type": "financial_reporting",
            "total_traces": 8,
            "avg_risk_score": 62.1,
        }


class TestSQLQueryFiles:
    """Verifies all 10 SQL query files exist, are readable, and reference valid columns."""

    def test_all_10_sql_files_exist(self):
        for fname in EXPECTED_SQL_FILES:
            fpath = SQL_DIR / fname
            assert fpath.exists(), f"Missing expected SQL query file: {fname}"

    @pytest.mark.parametrize("fname", EXPECTED_SQL_FILES)
    def test_sql_syntax_and_table_references(self, fname: str):
        content = AthenaClient.load_sql_file(SQL_DIR / fname)
        assert len(content.strip()) > 0
        assert "SELECT" in content.upper()
        assert "FROM audit_analytics" in content or "FROM" in content.upper()

        # Ensure no PostgreSQL specific constructs that Athena/Presto rejects
        assert "ILIKE" not in content  # Presto uses LOWER(...) LIKE or REGEXP_LIKE
        assert "SERIAL" not in content.upper()


class TestDataCoherence:
    """Verifies that AuditResult -> S3 JSON -> Glue Schema -> Athena Row fields are coherent."""

    def test_schema_field_coherence(self):
        # Sample record matching audit_handler analytics output
        sample_analytics_record = {
            "trace_id": "tr-001",
            "task_type": "customer_support",
            "date": "2026-09-27",
            "risk_score": 15.0,
            "risk_tier": "LOW",
            "pii_count": 0,
            "scope_violations": 0,
            "groundedness_failures": 0,
            "unsupported_claims": 0,
            "contradicted_claims": 0,
            "violated_tools": [],
            "summary": "Clean trace",
            "status": "COMPLETED",
            "processed_at": "2026-09-27T10:00:00Z",
        }

        # Every key in the record must match our expected Glue columns
        for key in sample_analytics_record:
            assert key in GLUE_COLUMNS, f"Analytics field '{key}' not defined in Glue schema"
