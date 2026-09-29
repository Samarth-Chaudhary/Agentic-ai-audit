"""Unit tests for AWS cloud repositories (S3, DynamoDB, SNS) using moto."""

from __future__ import annotations

import importlib

import boto3
import pytest
from moto import mock_aws

s3_repo_mod = importlib.import_module("lambda.repositories.s3_repository")
S3Repository = s3_repo_mod.S3Repository
S3NotFoundError = s3_repo_mod.S3NotFoundError
S3RepositoryError = s3_repo_mod.S3RepositoryError

ddb_repo_mod = importlib.import_module("lambda.repositories.dynamodb_repository")
DynamoDBRepository = ddb_repo_mod.DynamoDBRepository
DynamoDBRepositoryError = ddb_repo_mod.DynamoDBRepositoryError

sns_repo_mod = importlib.import_module("lambda.repositories.sns_repository")
SNSRepository = sns_repo_mod.SNSRepository
SNSRepositoryError = sns_repo_mod.SNSRepositoryError


@pytest.fixture
def aws_env(monkeypatch):
    """Set dummy AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


class TestS3Repository:
    """Tests for S3Repository using mock S3."""

    def test_parse_s3_uri(self):
        bucket, key = S3Repository.parse_s3_uri("s3://my-bucket/traces/task1/tr-001.json")
        assert bucket == "my-bucket"
        assert key == "traces/task1/tr-001.json"

        with pytest.raises(ValueError, match="scheme"):
            S3Repository.parse_s3_uri("https://my-bucket/traces/tr-001.json")

        with pytest.raises(ValueError, match="missing"):
            S3Repository.parse_s3_uri("s3://")

    @mock_aws
    def test_read_write_json_and_strings(self, aws_env):
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = "test-agent-traces"
        s3.create_bucket(Bucket=bucket_name)

        repo = S3Repository(s3_client=s3)

        assert not repo.object_exists(bucket_name, "traces/tr-001.json")

        # Put JSON
        sample_data = {"trace_id": "tr-001", "task_type": "customer_support", "steps": [1, 2, 3]}
        uri = repo.put_json(bucket_name, "traces/tr-001.json", sample_data)
        assert uri == f"s3://{bucket_name}/traces/tr-001.json"
        assert repo.object_exists(bucket_name, "traces/tr-001.json")

        # Get JSON
        retrieved = repo.get_json(bucket_name, "traces/tr-001.json")
        assert retrieved == sample_data

        # Get string
        retrieved_str = repo.get_object_as_string(bucket_name, "traces/tr-001.json")
        assert '"tr-001"' in retrieved_str

    @mock_aws
    def test_get_nonexistent_object_raises_s3_not_found(self, aws_env):
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = "test-empty-bucket"
        s3.create_bucket(Bucket=bucket_name)

        repo = S3Repository(s3_client=s3)
        with pytest.raises(S3NotFoundError):
            repo.get_object_as_string(bucket_name, "nonexistent.json")


class TestDynamoDBRepository:
    """Tests for DynamoDBRepository using mock DynamoDB."""

    @pytest.fixture
    def ddb_table(self, aws_env):
        with mock_aws():
            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            table = dynamodb.create_table(
                TableName="test-audit-results",
                KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "trace_id", "AttributeType": "S"},
                    {"AttributeName": "task_type", "AttributeType": "S"},
                    {"AttributeName": "processed_at", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "TaskTypeIndex",
                        "KeySchema": [
                            {"AttributeName": "task_type", "KeyType": "HASH"},
                            {"AttributeName": "processed_at", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            yield table, dynamodb

    def test_save_and_get_audit_result(self, ddb_table):
        table, dynamodb = ddb_table
        repo = DynamoDBRepository(table_name="test-audit-results", dynamodb_resource=dynamodb)

        sample_audit_result = {
            "trace_id": "tr-mock-100",
            "task_type": "financial_reporting",
            "processed_at": "2026-09-27T12:00:00Z",
            "risk_score": 67.5,
            "risk_tier": "HIGH",
            "scope_findings": [{"tool_name": "calc", "severity": "LOW"}],
            "pii_findings": [],
            "groundedness_findings": [{"finding_id": "g-1", "severity": "HIGH"}],
            "counts": {
                "total_steps": 5,
                "tool_calls": 2,
                "tool_results": 2,
                "errors": 0,
                "scope_violations": 1,
                "pii_entities_detected": 0,
                "unsupported_claims": 1,
            },
            "summary": "Trace had high risk groundedness issue",
            "status": "COMPLETED",
        }

        # 1. Save item
        saved = repo.save_audit_result(
            sample_audit_result,
            raw_trace_s3_uri="s3://traces-bucket/traces/financial_reporting/tr-mock-100.json",
        )
        assert saved["trace_id"] == "tr-mock-100"

        # 2. Retrieve item
        retrieved = repo.get_audit_result("tr-mock-100")
        assert retrieved is not None
        assert retrieved["trace_id"] == "tr-mock-100"
        assert retrieved["risk_score"] == 67.5
        assert isinstance(retrieved["risk_score"], float)
        assert retrieved["risk_tier"] == "HIGH"
        assert retrieved["raw_trace_s3_uri"] == "s3://traces-bucket/traces/financial_reporting/tr-mock-100.json"
        assert len(retrieved["findings"]["scope"]) == 1

        # 3. Nonexistent item returns None
        assert repo.get_audit_result("nonexistent-trace") is None

    def test_idempotent_saving_same_trace(self, ddb_table):
        table, dynamodb = ddb_table
        repo = DynamoDBRepository(table_name="test-audit-results", dynamodb_resource=dynamodb)

        audit_result = {
            "trace_id": "tr-idempotent-001",
            "task_type": "customer_support",
            "processed_at": "2026-09-27T12:00:00Z",
            "risk_score": 10.0,
            "risk_tier": "LOW",
            "counts": {"total_steps": 1, "tool_calls": 0, "tool_results": 0, "errors": 0, "scope_violations": 0, "pii_entities_detected": 0, "unsupported_claims": 0},
            "summary": "Clean trace",
        }

        # Save twice
        repo.save_audit_result(audit_result, raw_trace_s3_uri="s3://b/k")
        repo.save_audit_result(audit_result, raw_trace_s3_uri="s3://b/k")

        # Scan should only have 1 record
        items, _ = repo.list_audit_results(limit=10)
        assert len(items) == 1
        assert items[0]["trace_id"] == "tr-idempotent-001"


class TestSNSRepository:
    """Tests for SNSRepository using mock SNS."""

    @mock_aws
    def test_publish_high_risk_alert_safe_payload(self, aws_env):
        sns = boto3.client("sns", region_name="us-east-1")
        topic_res = sns.create_topic(Name="test-high-risk-alerts")
        topic_arn = topic_res["TopicArn"]

        repo = SNSRepository(topic_arn=topic_arn, sns_client=sns)

        msg_id = repo.publish_risk_alert(
            trace_id="tr-alert-001",
            task_type="customer_support",
            risk_score=85.0,
            risk_tier="CRITICAL",
            short_explanation="Trace contained severe unauthorized access",
        )
        assert msg_id is not None
        assert len(msg_id) > 0

    @mock_aws
    def test_publish_rejects_low_medium_tiers(self, aws_env):
        sns = boto3.client("sns", region_name="us-east-1")
        topic_res = sns.create_topic(Name="test-alerts")
        topic_arn = topic_res["TopicArn"]

        repo = SNSRepository(topic_arn=topic_arn, sns_client=sns)

        with pytest.raises(ValueError, match="only published for HIGH or CRITICAL"):
            repo.publish_risk_alert(
                trace_id="tr-low-001",
                task_type="default",
                risk_score=5.0,
                risk_tier="LOW",
                short_explanation="Clean trace",
            )
