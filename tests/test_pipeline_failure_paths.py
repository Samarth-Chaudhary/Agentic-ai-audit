"""Automated tests verifying pipeline failure paths and resilience (Task 3).

Explicitly tests:
1. Duplicate S3 Event: Does not create conflicting DynamoDB records (idempotent write).
2. Malformed Trace: Rejected with clear error and forwarded to Dead Letter Queue (DLQ).
3. Mid-Audit Timeout: Leaves the system in a clean, retryable state without corrupted records.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from auditor.nli_classifier import MockNLIClassifier, NLIVerdict
from auditor.orchestrator import AuditOrchestrator

REPO_ROOT = Path(__file__).resolve().parent.parent

audit_handler_mod = importlib.import_module("lambda.audit_handler")
handler = audit_handler_mod.handler


@pytest.fixture
def fast_orchestrator() -> AuditOrchestrator:
    """Deterministic fast orchestrator for pipeline testing."""
    def rule(premise: str, hypothesis: str) -> NLIVerdict | None:
        return NLIVerdict.ENTAILMENT

    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.ENTAILMENT, custom_rule=rule)
    orch = AuditOrchestrator()
    orch.groundedness_detector.nli_classifier = mock_nli
    return orch


@pytest.fixture
def aws_env(monkeypatch):
    """Set dummy credentials and configuration for Moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("DYNAMODB_TABLE", "agent-audit-results-test")
    monkeypatch.setenv("RESULTS_BUCKET", "agent-audit-results-test")


@mock_aws
def test_failure_path_duplicate_s3_event_idempotency(aws_env, fast_orchestrator):
    """Scenario 1: Duplicate S3 event does not produce two conflicting DynamoDB records."""
    s3 = boto3.client("s3", region_name="us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    raw_bucket = "agent-audit-raw-traces-test"
    results_bucket = "agent-audit-results-test"
    s3.create_bucket(Bucket=raw_bucket)
    s3.create_bucket(Bucket=results_bucket)

    table_name = "agent-audit-results-test"
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "trace_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    trace_id = "tr-duplicate-test-001"
    fixture_path = REPO_ROOT / "fixtures" / "valid_customer_refund.json"
    with open(fixture_path, encoding="utf-8") as f:
        valid_trace = json.load(f)
    valid_trace["trace_id"] = trace_id

    object_key = f"traces/{trace_id}.json"
    s3.put_object(Bucket=raw_bucket, Key=object_key, Body=json.dumps(valid_trace))

    sqs_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": raw_bucket},
                    "object": {"key": object_key},
                }
            }
        ]
    }

    # First event delivery
    resp1 = handler(sqs_event, orchestrator=fast_orchestrator)
    assert resp1["statusCode"] == 200
    assert resp1["processed_count"] == 1

    # Second event delivery (Duplicate replay)
    resp2 = handler(sqs_event, orchestrator=fast_orchestrator)
    assert resp2["statusCode"] == 200
    assert resp2["processed_count"] == 1

    # Verification: DynamoDB has exactly 1 record for this trace_id
    scan_resp = table.scan()
    items = [it for it in scan_resp.get("Items", []) if it.get("trace_id") == trace_id]
    assert len(items) == 1, f"Expected exactly 1 DynamoDB record for {trace_id}, found {len(items)}"
    assert items[0]["trace_id"] == trace_id


@mock_aws
def test_failure_path_malformed_trace_rejected_to_dlq(aws_env, monkeypatch):
    """Scenario 2: Malformed trace is rejected with clear error and routed to Dead Letter Queue."""
    s3 = boto3.client("s3", region_name="us-east-1")
    sqs = boto3.client("sqs", region_name="us-east-1")

    raw_bucket = "agent-audit-raw-traces-test"
    results_bucket = "agent-audit-results-test"
    s3.create_bucket(Bucket=raw_bucket)
    s3.create_bucket(Bucket=results_bucket)

    dlq_queue = sqs.create_queue(QueueName="agent-audit-traces-dlq-test")
    dlq_url = dlq_queue["QueueUrl"]
    monkeypatch.setenv("DLQ_URL", dlq_url)

    # Malformed trace missing required schema fields ('steps' missing, invalid task_type)
    malformed_trace = {
        "trace_id": "tr-malformed-001",
        "invalid_field": "corrupted payload",
    }

    object_key = "traces/tr-malformed-001.json"
    s3.put_object(Bucket=raw_bucket, Key=object_key, Body=json.dumps(malformed_trace))

    sqs_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": raw_bucket},
                    "object": {"key": object_key},
                }
            }
        ]
    }

    # Handler should reject with validation error and not swallow the exception silently
    with pytest.raises(Exception) as exc_info:
        handler(sqs_event)

    assert "validation" in str(exc_info.value).lower() or "trace_id" in str(exc_info.value) or "error" in str(exc_info.value).lower()

    # Verify message landed on DLQ
    messages = sqs.receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=10).get("Messages", [])
    assert len(messages) == 1, "Expected exactly 1 error notification in DLQ"
    body = json.loads(messages[0]["Body"])
    assert body["bucket"] == raw_bucket
    assert body["key"] == object_key
    assert "error" in body


@mock_aws
def test_failure_path_mid_audit_timeout_leaves_clean_retryable_state(aws_env):
    """Scenario 3: Simulated mid-audit timeout leaves system in clean, retryable state with no corrupted records."""
    s3 = boto3.client("s3", region_name="us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    raw_bucket = "agent-audit-raw-traces-test"
    results_bucket = "agent-audit-results-test"
    s3.create_bucket(Bucket=raw_bucket)
    s3.create_bucket(Bucket=results_bucket)

    table_name = "agent-audit-results-test"
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "trace_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    trace_id = "tr-timeout-test-001"
    valid_trace = {
        "trace_id": trace_id,
        "task_type": "customer_refund",
        "started_at": "2026-09-29T10:00:00Z",
        "completed_at": "2026-09-29T10:00:05Z",
        "steps": [
            {
                "step_index": 0,
                "step_type": "USER_INPUT",
                "timestamp": "2026-09-29T10:00:00Z",
                "input_prompt": "What is status?",
            },
        ],
    }

    object_key = f"traces/{trace_id}.json"
    s3.put_object(Bucket=raw_bucket, Key=object_key, Body=json.dumps(valid_trace))

    sqs_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": raw_bucket},
                    "object": {"key": object_key},
                }
            }
        ]
    }

    # Simulate timeout exception occurring inside orchestrator mid-audit
    mock_orch = MagicMock(spec=AuditOrchestrator)
    mock_orch.run.side_effect = TimeoutError("Lambda execution timed out mid-audit (15.00s limit reached)")

    with pytest.raises(TimeoutError) as exc_info:
        handler(sqs_event, orchestrator=mock_orch)

    assert "timed out mid-audit" in str(exc_info.value)

    # Verify: Zero corrupted or partial records in DynamoDB
    item = table.get_item(Key={"trace_id": trace_id}).get("Item")
    assert item is None, "DynamoDB must contain no corrupted or half-written record after timeout"

    # Verify: Zero records in analytics S3 bucket
    objects = s3.list_objects_v2(Bucket=results_bucket).get("Contents", [])
    assert len(objects) == 0, "Results bucket must contain no partial analytics file after timeout"
