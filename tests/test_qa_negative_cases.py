"""Comprehensive negative test suite for Quality Assurance and Robustness.

Covers all 16 negative scenarios across validation, detectors, and pipelines:
1. missing trace_id
2. invalid UUID / ID format
3. unknown task_type
4. missing final_answer
5. malformed tool call
6. unknown tool
7. missing tool result
8. invalid refund value
9. PII candidate that should not pass Luhn
10. unsupported claim
11. contradiction
12. missing S3 object behavior
13. DynamoDB failure handling
14. Athena failure handling
15. duplicate SQS event
16. provider/model failure
"""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from agent.validation import validate_trace_dict
from analytics.athena_client import AthenaClient, AthenaClientError
from auditor.groundedness_detector import GroundednessDetector
from auditor.luhn import classify_card_candidate, is_luhn_valid
from auditor.models import RiskTier, Trace
from auditor.nli_classifier import MockNLIClassifier, NLIVerdict
from auditor.orchestrator import AuditOrchestrator
from auditor.policy_loader import ConfigurationError, PolicyLoader, UnknownTaskTypeError
from auditor.scope_detector import ScopeDetector

s3_repo_mod = importlib.import_module("lambda.repositories.s3_repository")
S3Repository = s3_repo_mod.S3Repository
S3NotFoundError = s3_repo_mod.S3NotFoundError

ddb_repo_mod = importlib.import_module("lambda.repositories.dynamodb_repository")
DynamoDBRepository = ddb_repo_mod.DynamoDBRepository
DynamoDBRepositoryError = ddb_repo_mod.DynamoDBRepositoryError

audit_handler_mod = importlib.import_module("lambda.audit_handler")
lambda_handler = audit_handler_mod.handler


@pytest.fixture
def base_valid_trace_dict() -> dict:
    """Minimal schema-valid trace dictionary."""
    return {
        "trace_id": "tr-00000000-0000-0000-0000-000000000001",
        "schema_version": "1.0.0",
        "task_type": "customer_refund",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "steps": [
            {
                "index": 0,
                "type": "assistant_message",
                "content": "Verifying order status.",
            },
            {
                "index": 1,
                "type": "tool_call",
                "tool_name": "order_lookup",
                "input": {"order_id": "ORD-1234"},
            },
            {
                "index": 2,
                "type": "tool_result",
                "tool_name": "order_lookup",
                "output": {
                    "order_id": "ORD-1234",
                    "status": "DELIVERED",
                    "order_total": 50.0,
                    "refundable_amount": 50.0,
                    "refund_eligible": True,
                    "found": True,
                },
            },
        ],
        "final_answer": "Order ORD-1234 was delivered and is eligible for refund.",
    }


# =============================================================================
# 1. missing trace_id
# =============================================================================
def test_negative_missing_trace_id(base_valid_trace_dict):
    data = dict(base_valid_trace_dict)
    del data["trace_id"]
    result = validate_trace_dict(data)
    assert not result.is_valid
    assert any("trace_id" in err for err in result.errors)


# =============================================================================
# 2. invalid UUID / ID format
# =============================================================================
def test_negative_invalid_uuid(base_valid_trace_dict):
    data = dict(base_valid_trace_dict)
    data["trace_id"] = ""  # Violates minLength: 1
    result = validate_trace_dict(data)
    assert not result.is_valid
    assert any("trace_id" in err for err in result.errors)


# =============================================================================
# 3. unknown task_type
# =============================================================================
def test_negative_unknown_task_type():
    loader = PolicyLoader()
    with pytest.raises((UnknownTaskTypeError, ConfigurationError)):
        loader.get_policy("unknown_nonexistent_task_policy")


# =============================================================================
# 4. missing final_answer
# =============================================================================
def test_negative_missing_final_answer(base_valid_trace_dict):
    data = dict(base_valid_trace_dict)
    del data["final_answer"]
    result = validate_trace_dict(data)
    assert not result.is_valid
    assert any("final_answer" in err for err in result.errors)


# =============================================================================
# 5. malformed tool call
# =============================================================================
def test_negative_malformed_tool_call(base_valid_trace_dict):
    data = dict(base_valid_trace_dict)
    # tool_call step without tool_name
    data["steps"] = [
        {
            "index": 0,
            "type": "tool_call",
            "input": {"param": "value"},
        }
    ]
    result = validate_trace_dict(data)
    assert not result.is_valid
    assert any("tool_name" in err for err in result.errors)


# =============================================================================
# 6. unknown tool
# =============================================================================
def test_negative_unknown_tool(base_valid_trace_dict):
    loader = PolicyLoader()
    policy = loader.get_policy("customer_refund")
    detector = ScopeDetector()

    data = dict(base_valid_trace_dict)
    data["steps"] = [
        {
            "index": 0,
            "type": "tool_call",
            "tool_name": "bash_arbitrary_shell_runner",
            "input": {"command": "rm -rf /"},
        }
    ]
    trace = Trace.model_validate(data)
    res = detector.evaluate(trace, policy)

    assert not res.passed
    assert any(f.rule_violated == "tool_not_allowed" for f in res.findings)


# =============================================================================
# 7. missing tool result
# =============================================================================
def test_negative_missing_tool_result(base_valid_trace_dict):
    data = dict(base_valid_trace_dict)
    # tool_result step missing 'output'
    data["steps"] = [
        {
            "index": 0,
            "type": "tool_result",
            "tool_name": "order_lookup",
        }
    ]
    result = validate_trace_dict(data)
    assert not result.is_valid
    assert any("output" in err for err in result.errors)


# =============================================================================
# 8. invalid refund value
# =============================================================================
def test_negative_invalid_refund_value(base_valid_trace_dict):
    loader = PolicyLoader()
    policy = loader.get_policy("customer_refund")
    detector = ScopeDetector()

    data = dict(base_valid_trace_dict)
    data["steps"] = [
        {
            "index": 0,
            "type": "tool_call",
            "tool_name": "order_lookup",
            "input": {"order_id": "ORD-1234"},
        },
        {
            "index": 1,
            "type": "tool_result",
            "tool_name": "order_lookup",
            "output": {
                "order_id": "ORD-1234",
                "order_total": 50.0,
                "refundable_amount": 50.0,
                "status": "DELIVERED",
                "refund_eligible": True,
                "found": True,
            },
        },
        {
            "index": 2,
            "type": "tool_call",
            "tool_name": "refund_tool",
            "input": {"order_id": "ORD-1234", "amount": 250.0},  # Exceeds 50.0
        },
    ]
    trace = Trace.model_validate(data)
    res = detector.evaluate(trace, policy)

    refund_violations = [f for f in res.findings if f.rule_violated == "refund_exceeds_order_total"]
    assert len(refund_violations) == 1
    assert refund_violations[0].severity == RiskTier.CRITICAL


# =============================================================================
# 9. PII candidate that should not pass Luhn
# =============================================================================
def test_negative_pii_candidate_fails_luhn():
    fake_card_fails_luhn = "4111 1111 1111 1112"
    assert is_luhn_valid(fake_card_fails_luhn) is False
    classification = classify_card_candidate(fake_card_fails_luhn)
    assert classification["is_luhn_valid"] is False
    assert classification["brand"] == "Invalid"


# =============================================================================
# 10. unsupported claim
# =============================================================================
def test_negative_unsupported_claim(base_valid_trace_dict):
    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.NEUTRAL)
    detector = GroundednessDetector(nli_classifier=mock_nli)

    data = dict(base_valid_trace_dict)
    data["final_answer"] = "The product warranty has been extended to 10 years without extra charges."
    trace = Trace.model_validate(data)

    res = detector.evaluate(trace)
    assert res.unsupported_claims >= 1
    assert not res.passed


# =============================================================================
# 11. contradiction
# =============================================================================
def test_negative_contradiction(base_valid_trace_dict):
    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.CONTRADICTION)
    # Using similarity_threshold=0.0 ensures the available evidence is selected and checked by NLI
    detector = GroundednessDetector(similarity_threshold=0.0, nli_classifier=mock_nli)

    data = dict(base_valid_trace_dict)
    data["steps"][2]["output"]["status"] = "ORDER_CANCELLED"
    data["final_answer"] = "Your package was delivered successfully to your doorstep."
    trace = Trace.model_validate(data)

    res = detector.evaluate(trace)
    assert res.contradicted_claims >= 1
    assert not res.passed


# =============================================================================
# 12. missing S3 object behavior
# =============================================================================
@mock_aws
def test_negative_missing_s3_object_behavior():
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = "test-missing-obj-bucket"
    s3.create_bucket(Bucket=bucket)

    repo = S3Repository(s3_client=s3)
    with pytest.raises(S3NotFoundError, match="Object not found"):
        repo.get_json(bucket, "traces/nonexistent-trace.json")


# =============================================================================
# 13. DynamoDB failure handling
# =============================================================================
def test_negative_dynamodb_failure_handling():
    mock_res = MagicMock()
    mock_tbl = MagicMock()
    mock_res.Table.return_value = mock_tbl
    mock_tbl.put_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throughput exceeded"}},
        "PutItem",
    )
    repo = DynamoDBRepository(dynamodb_resource=mock_res, table_name="test-table")
    with pytest.raises(DynamoDBRepositoryError, match="Failed to save audit result"):
        repo.save_audit_result({"trace_id": "tr-001", "risk_score": 10.0})


# =============================================================================
# 14. Athena failure handling
# =============================================================================
def test_negative_athena_failure_handling():
    mock_boto = MagicMock()
    client = AthenaClient(
        athena_client=mock_boto,
        database="test_db",
        output_location="s3://test-bucket/results/",
    )

    mock_boto.start_query_execution.return_value = {"QueryExecutionId": "q-12345"}
    mock_boto.get_query_execution.return_value = {
        "QueryExecution": {
            "Status": {
                "State": "FAILED",
                "StateChangeReason": "SYNTAX_ERROR: line 1:1: Table 'test_db.audit_analytics' does not exist",
            }
        }
    }

    with pytest.raises(AthenaClientError, match="SYNTAX_ERROR"):
        client.execute_query("SELECT * FROM audit_analytics;")


# =============================================================================
# 15. duplicate SQS event handling
# =============================================================================
@mock_aws
def test_negative_duplicate_sqs_event(monkeypatch, base_valid_trace_dict):
    monkeypatch.setenv("DYNAMODB_TABLE", "agent-audit-results")
    monkeypatch.setenv("RESULTS_BUCKET", "agent-audit-results-bucket")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="agent-traces-bucket")
    s3.create_bucket(Bucket="agent-audit-results-bucket")

    # Put trace into S3
    trace_key = "raw/customer_refund/tr-001.json"
    s3.put_object(
        Bucket="agent-traces-bucket",
        Key=trace_key,
        Body=json.dumps(base_valid_trace_dict),
    )

    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName="agent-audit-results",
        KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "trace_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # Use mock orchestrator for fast execution
    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.ENTAILMENT)
    orch = AuditOrchestrator()
    orch.groundedness_detector.nli_classifier = mock_nli

    # Construct SQS Event containing the duplicate record twice
    sqs_body = {
        "bucket": "agent-traces-bucket",
        "key": trace_key,
    }
    sqs_event = {
        "Records": [
            {"body": json.dumps(sqs_body)},
            {"body": json.dumps(sqs_body)},  # Duplicate SQS record
        ]
    }

    # Execute Lambda handler
    resp = lambda_handler(sqs_event, None, orchestrator=orch)
    assert resp["statusCode"] == 200
    assert resp["processed_count"] == 2

    # DynamoDB must have record updated idempotently
    ddb_record = table.get_item(
        Key={"trace_id": base_valid_trace_dict["trace_id"]},
    )
    assert "Item" in ddb_record
    assert ddb_record["Item"]["trace_id"] == base_valid_trace_dict["trace_id"]


# =============================================================================
# 16. provider/model failure
# =============================================================================
def test_negative_provider_model_failure(base_valid_trace_dict):
    mock_nli = MagicMock()
    mock_nli.classify.side_effect = RuntimeError("PyTorch runtime error during NLI forward pass")

    # similarity_threshold=0.0 routes claim to NLI classifier which simulates crash
    detector = GroundednessDetector(similarity_threshold=0.0, nli_classifier=mock_nli)
    data = dict(base_valid_trace_dict)
    trace = Trace.model_validate(data)

    # Detector handles internal classifier errors safely and marks claim as UNSUPPORTED
    res = detector.evaluate(trace)
    assert res is not None
    assert len(res.findings) >= 1
    # Fallback verdict is UNSUPPORTED when NLI provider crashes
    assert all(f.audit_verdict == "UNSUPPORTED" for f in res.findings)
