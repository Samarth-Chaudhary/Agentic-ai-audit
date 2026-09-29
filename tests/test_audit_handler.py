"""Integration and unit tests for the operational Audit Lambda handler."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from auditor.nli_classifier import MockNLIClassifier, NLIVerdict
from auditor.orchestrator import AuditOrchestrator

audit_handler_mod = importlib.import_module("lambda.audit_handler")
handler = audit_handler_mod.handler
extract_s3_events_from_sqs_record = audit_handler_mod.extract_s3_events_from_sqs_record

s3_repo_mod = importlib.import_module("lambda.repositories.s3_repository")
S3Repository = s3_repo_mod.S3Repository

ddb_repo_mod = importlib.import_module("lambda.repositories.dynamodb_repository")
DynamoDBRepository = ddb_repo_mod.DynamoDBRepository

sns_repo_mod = importlib.import_module("lambda.repositories.sns_repository")
SNSRepository = sns_repo_mod.SNSRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "traces"


@pytest.fixture
def aws_env(monkeypatch):
    """Set dummy AWS credentials and env vars for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("DYNAMODB_TABLE", "test-audit-results")
    monkeypatch.setenv("RESULTS_BUCKET", "test-results-bucket")


@pytest.fixture
def mock_orchestrator() -> AuditOrchestrator:
    """Orchestrator with deterministic mock NLI for fast testing."""
    def rule(premise: str, hypothesis: str) -> NLIVerdict | None:
        p = premise.lower()
        h = hypothesis.lower()
        if "delivered" in p and "delivered" in h:
            return NLIVerdict.ENTAILMENT
        if "delivered" in p and "cancelled" in h:
            return NLIVerdict.CONTRADICTION
        return None

    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.NEUTRAL, custom_rule=rule)
    orch = AuditOrchestrator()
    orch.groundedness_detector.nli_classifier = mock_nli
    return orch


class TestSQSEventParsing:
    """Tests for SQS and S3 event extraction."""

    def test_extract_s3_notification_from_sqs_record(self):
        s3_notification = {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": "traces-bucket"},
                        "object": {"key": "traces%2Fcustomer_support%2Ftr-001.json"},
                    }
                }
            ]
        }
        record = {"body": json.dumps(s3_notification)}
        extracted = extract_s3_events_from_sqs_record(record)
        assert len(extracted) == 1
        assert extracted[0] == ("traces-bucket", "traces/customer_support/tr-001.json")

    def test_extract_direct_sqs_payload(self):
        record = {"body": json.dumps({"bucket": "custom-bucket", "key": "traces/task/tr-1.json"})}
        extracted = extract_s3_events_from_sqs_record(record)
        assert extracted == [("custom-bucket", "traces/task/tr-1.json")]

    def test_extract_s3_uri_payload(self):
        record = {"body": json.dumps({"s3_uri": "s3://uri-bucket/traces/task/tr-2.json"})}
        extracted = extract_s3_events_from_sqs_record(record)
        assert extracted == [("uri-bucket", "traces/task/tr-2.json")]

    def test_invalid_json_body_returns_empty(self):
        record = {"body": "not-valid-json{"}
        assert extract_s3_events_from_sqs_record(record) == []


class TestAuditHandlerFlow:
    """End-to-end operational flow tests using moto."""

    @pytest.fixture
    def setup_aws_resources(self, aws_env):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket="test-traces-bucket")
            s3.create_bucket(Bucket="test-results-bucket")

            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            table = dynamodb.create_table(
                TableName="test-audit-results",
                KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "trace_id", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            sns = boto3.client("sns", region_name="us-east-1")
            topic_res = sns.create_topic(Name="test-high-risk-alerts")
            topic_arn = topic_res["TopicArn"]

            s3_repo = S3Repository(s3_client=s3)
            ddb_repo = DynamoDBRepository(table_name="test-audit-results", dynamodb_resource=dynamodb)
            sns_repo = SNSRepository(topic_arn=topic_arn, sns_client=sns)

            yield {
                "s3": s3,
                "dynamodb": dynamodb,
                "table": table,
                "sns": sns,
                "topic_arn": topic_arn,
                "s3_repo": s3_repo,
                "ddb_repo": ddb_repo,
                "sns_repo": sns_repo,
            }

def make_test_trace(
    trace_id: str = "tr-clean-001",
    task_type: str = "customer_support",
    tool_name: str = "lookup_order_status",
    tool_input: dict | None = None,
    tool_output: dict | None = None,
    final_answer: str = "Order status is confirmed as DELIVERED.",
    data_source: str | None = "customer_orders_api",
) -> dict:
    return {
        "trace_id": trace_id,
        "schema_version": "1.0.0",
        "task_type": task_type,
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "metadata": {
            "agent_id": "test-agent",
            "scenario": "test",
        },
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "call_id": "call-001",
                "tool_name": tool_name,
                "input": tool_input or {"order_id": "ORD-9921"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "call_id": "call-001",
                "tool_name": tool_name,
                "output": tool_output or {
                    "text": "Order status is confirmed as DELIVERED.",
                    "status": "DELIVERED",
                    "source_type": data_source,
                },
            },
        ],
        "final_answer": final_answer,
    }


    def test_audit_clean_trace_flow(self, setup_aws_resources, mock_orchestrator):
        res = setup_aws_resources
        s3 = res["s3"]
        ddb_repo = res["ddb_repo"]

        # 1. Upload clean trace to S3
        clean_trace = make_test_trace(trace_id="tr-clean-001")
        s3.put_object(
            Bucket="test-traces-bucket",
            Key="traces/customer_support/tr-clean-001.json",
            Body=json.dumps(clean_trace).encode("utf-8"),
        )

        # 2. Construct SQS event
        sqs_event = {
            "Records": [
                {
                    "body": json.dumps({
                        "Records": [
                            {
                                "s3": {
                                    "bucket": {"name": "test-traces-bucket"},
                                    "object": {"key": "traces/customer_support/tr-clean-001.json"},
                                }
                            }
                        ]
                    })
                }
            ]
        }

        # 3. Execute Lambda handler
        response = handler(
            event=sqs_event,
            orchestrator=mock_orchestrator,
            s3_repo=res["s3_repo"],
            dynamodb_repo=ddb_repo,
            sns_repo=res["sns_repo"],
        )

        assert response["statusCode"] == 200
        assert response["processed_count"] == 1
        item_info = response["results"][0]
        assert item_info["trace_id"] == "tr-clean-001"
        assert item_info["risk_tier"] == "LOW"
        assert item_info["sns_message_id"] is None  # No alert for LOW

        # 4. Verify DynamoDB persistence
        ddb_record = ddb_repo.get_audit_result("tr-clean-001")
        assert ddb_record is not None
        assert ddb_record["trace_id"] == "tr-clean-001"
        assert ddb_record["risk_tier"] == "LOW"
        assert ddb_record["raw_trace_s3_uri"] == "s3://test-traces-bucket/traces/customer_support/tr-clean-001.json"

        # 5. Verify analytics result in S3 with partitioned structure
        analytics_obj = res["s3_repo"].get_json("test-results-bucket", "results/date=2026-09-27/task_type=customer_support/tr-clean-001.json")
        assert analytics_obj["trace_id"] == "tr-clean-001"
        assert analytics_obj["risk_tier"] == "LOW"
        assert analytics_obj["date"] == "2026-09-27"
        assert analytics_obj["scope_violations"] == 0
        assert analytics_obj["pii_count"] == 0
        assert analytics_obj["groundedness_failures"] == 0
        assert "violated_tools" in analytics_obj

    def test_audit_high_risk_trace_publishes_sns(self, setup_aws_resources, mock_orchestrator):
        res = setup_aws_resources
        s3 = res["s3"]
        ddb_repo = res["ddb_repo"]

        # Upload high risk trace (unauthorized tools + contradicted claim)
        high_risk_trace = make_test_trace(
            trace_id="tr-scope-001",
            tool_name="unauthorized_exec_tool",
            tool_output={"text": "Order was cancelled."},
            final_answer="Your order is delivered successfully.",
        )
        s3.put_object(
            Bucket="test-traces-bucket",
            Key="traces/customer_support/tr-scope-001.json",
            Body=json.dumps(high_risk_trace).encode("utf-8"),
        )

        sqs_event = {
            "Records": [
                {
                    "body": json.dumps({
                        "bucket": "test-traces-bucket",
                        "key": "traces/customer_support/tr-scope-001.json",
                    })
                }
            ]
        }

        response = handler(
            event=sqs_event,
            orchestrator=mock_orchestrator,
            s3_repo=res["s3_repo"],
            dynamodb_repo=ddb_repo,
            sns_repo=res["sns_repo"],
        )

        assert response["statusCode"] == 200
        assert response["processed_count"] == 1
        item_info = response["results"][0]
        assert item_info["trace_id"] == "tr-scope-001"
        assert item_info["risk_tier"] in ("HIGH", "CRITICAL")
        # SNS alert must have been published
        assert item_info["sns_message_id"] is not None

        # Verify DynamoDB has recorded findings
        ddb_record = ddb_repo.get_audit_result("tr-scope-001")
        assert ddb_record is not None
        assert len(ddb_record["findings"]["scope"]) >= 1

    def test_idempotent_reprocessing(self, setup_aws_resources, mock_orchestrator):
        res = setup_aws_resources
        s3 = res["s3"]
        ddb_repo = res["ddb_repo"]

        clean_trace = make_test_trace(trace_id="tr-clean-001")
        s3.put_object(
            Bucket="test-traces-bucket",
            Key="traces/customer_support/tr-clean-001.json",
            Body=json.dumps(clean_trace).encode("utf-8"),
        )

        sqs_event = {
            "Records": [
                {
                    "body": json.dumps({
                        "bucket": "test-traces-bucket",
                        "key": "traces/customer_support/tr-clean-001.json",
                    })
                }
            ]
        }

        # Process twice
        res1 = handler(event=sqs_event, orchestrator=mock_orchestrator, s3_repo=res["s3_repo"], dynamodb_repo=ddb_repo, sns_repo=res["sns_repo"])
        res2 = handler(event=sqs_event, orchestrator=mock_orchestrator, s3_repo=res["s3_repo"], dynamodb_repo=ddb_repo, sns_repo=res["sns_repo"])

        assert res1["statusCode"] == 200
        assert res2["statusCode"] == 200

        # Must still be exactly 1 item in DynamoDB
        items, _ = ddb_repo.list_audit_results(limit=10)
        assert len(items) == 1
