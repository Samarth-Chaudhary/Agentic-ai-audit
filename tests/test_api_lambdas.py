"""Unit and integration tests for API Gateway read Lambdas (list_traces and get_trace)."""

from __future__ import annotations

import importlib
import json

import boto3
import pytest
from moto import mock_aws

list_traces_mod = importlib.import_module("lambda.list_traces")
list_traces_handler = list_traces_mod.handler

get_trace_mod = importlib.import_module("lambda.get_trace")
get_trace_handler = get_trace_mod.handler
redact_execution_timeline = get_trace_mod.redact_execution_timeline

ddb_repo_mod = importlib.import_module("lambda.repositories.dynamodb_repository")
DynamoDBRepository = ddb_repo_mod.DynamoDBRepository

s3_repo_mod = importlib.import_module("lambda.repositories.s3_repository")
S3Repository = s3_repo_mod.S3Repository


@pytest.fixture
def aws_env(monkeypatch):
    """Set dummy AWS credentials and env vars for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("DYNAMODB_TABLE", "test-api-audit-results")


class TestListTracesLambda:
    """Tests for GET /traces lambda handler."""

    @pytest.fixture
    def setup_ddb(self, aws_env):
        with mock_aws():
            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName="test-api-audit-results",
                KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "trace_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            repo = DynamoDBRepository(table_name="test-api-audit-results", dynamodb_resource=dynamodb)

            # Insert sample audit records
            for i in range(1, 4):
                repo.save_audit_result({
                    "trace_id": f"tr-api-{i:03d}",
                    "task_type": "customer_support",
                    "processed_at": f"2026-09-27T10:0{i}:00Z",
                    "risk_score": float(i * 15.0),
                    "risk_tier": "LOW" if i == 1 else ("MEDIUM" if i == 2 else "HIGH"),
                    "scope_findings": [],
                    "pii_findings": [],
                    "groundedness_findings": [],
                    "counts": {
                        "total_steps": 4,
                        "tool_calls": 2,
                        "tool_results": 2,
                        "errors": 0,
                        "scope_violations": i - 1,
                        "pii_entities_detected": i,
                        "unsupported_claims": 0,
                    },
                    "summary": f"Audit summary for trace {i}",
                }, raw_trace_s3_uri=f"s3://bucket/traces/customer_support/tr-api-{i:03d}.json")

            yield repo

    def test_list_traces_returns_summary_records(self, setup_ddb):
        repo = setup_ddb
        event = {"queryStringParameters": {"limit": "10"}}
        resp = list_traces_handler(event, dynamodb_repo=repo)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["count"] == 3
        items = body["items"]

        # Check required summary fields
        first = items[0]
        assert "trace_id" in first
        assert "task_type" in first
        assert "risk_score" in first
        assert "risk_tier" in first
        assert "processed_at" in first
        assert "pii_count" in first
        assert "scope_violation_count" in first
        assert "groundedness_failure_count" in first

        # Confirm large raw traces are not returned in list response
        assert "steps" not in first
        assert "execution_timeline" not in first

    def test_list_traces_pagination_limit(self, setup_ddb):
        repo = setup_ddb
        event = {"queryStringParameters": {"limit": "2"}}
        resp = list_traces_handler(event, dynamodb_repo=repo)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["count"] == 2


class TestGetTraceLambda:
    """Tests for GET /traces/{trace_id} lambda handler."""

    @pytest.fixture
    def setup_trace_data(self, aws_env):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket="test-api-bucket")

            raw_trace = {
                "trace_id": "tr-detail-001",
                "task_type": "customer_support",
                "steps": [
                    {
                        "step_index": 0,
                        "type": "USER_INPUT",
                        "content": "My SSN is 000-12-3456 and email is customer@example.com",
                    },
                    {
                        "step_index": 1,
                        "type": "TOOL_CALL",
                        "tool_name": "lookup_account",
                        "tool_input": {"secret_token": "api_key: secrettoken12345"},
                    },
                    {
                        "step_index": 2,
                        "type": "TOOL_RESULT",
                        "observation": "Account found. Credit card is 4111 2222 3333 4444.",
                    },
                    {
                        "step_index": 3,
                        "type": "FINAL_ANSWER",
                        "content": "Your account balance is $150.00.",
                    },
                ],
            }

            s3.put_object(
                Bucket="test-api-bucket",
                Key="traces/customer_support/tr-detail-001.json",
                Body=json.dumps(raw_trace).encode("utf-8"),
            )

            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName="test-api-audit-results",
                KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "trace_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            d_repo = DynamoDBRepository(table_name="test-api-audit-results", dynamodb_resource=dynamodb)
            s_repo = S3Repository(s3_client=s3)

            d_repo.save_audit_result({
                "trace_id": "tr-detail-001",
                "task_type": "customer_support",
                "processed_at": "2026-09-27T10:00:00Z",
                "risk_score": 85.0,
                "risk_tier": "CRITICAL",
                "scope_findings": [],
                "pii_findings": [
                    {"field_path": "steps[0].content", "severity": "HIGH", "pii_type": "US_SSN"},
                ],
                "groundedness_findings": [],
                "counts": {
                    "total_steps": 4,
                    "tool_calls": 1,
                    "tool_results": 1,
                    "errors": 0,
                    "scope_violations": 0,
                    "pii_entities_detected": 1,
                    "unsupported_claims": 0,
                },
                "summary": "Trace had critical PII leakage",
            }, raw_trace_s3_uri="s3://test-api-bucket/traces/customer_support/tr-detail-001.json")

            yield d_repo, s_repo

    def test_get_trace_success_and_redaction(self, setup_trace_data):
        d_repo, s_repo = setup_trace_data
        event = {"pathParameters": {"trace_id": "tr-detail-001"}}

        resp = get_trace_handler(event, dynamodb_repo=d_repo, s3_repo=s_repo)
        assert resp["statusCode"] == 200

        body = json.loads(resp["body"])
        assert body["trace_id"] == "tr-detail-001"
        assert body["task_type"] == "customer_support"
        assert "summary" in body
        assert "risk" in body
        assert "findings" in body
        assert "execution_timeline" in body

        # Verify that sensitive information (SSN, Email, CC, API Key) in timeline is masked
        timeline = body["execution_timeline"]
        assert len(timeline) == 4

        step0_content = timeline[0]["content"]
        assert "<REDACTED_SSN>" in step0_content
        assert "000-12-3456" not in step0_content
        assert "<REDACTED_EMAIL>" in step0_content
        assert "customer@example.com" not in step0_content

        step1_input = json.dumps(timeline[1]["tool_input"])
        assert "<REDACTED_SECRET>" in step1_input
        assert "secrettoken12345" not in step1_input

        step2_obs = timeline[2]["observation"]
        assert "<REDACTED_CC>" in step2_obs
        assert "4111 2222 3333 4444" not in step2_obs

    def test_get_trace_not_found(self, setup_trace_data):
        d_repo, s_repo = setup_trace_data
        event = {"pathParameters": {"trace_id": "non-existent-trace"}}

        resp = get_trace_handler(event, dynamodb_repo=d_repo, s3_repo=s_repo)
        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert "not found" in body["error"].lower()

    def test_get_trace_missing_path_param(self, setup_trace_data):
        d_repo, s_repo = setup_trace_data
        event = {"pathParameters": {}}

        resp = get_trace_handler(event, dynamodb_repo=d_repo, s3_repo=s_repo)
        assert resp["statusCode"] == 400
