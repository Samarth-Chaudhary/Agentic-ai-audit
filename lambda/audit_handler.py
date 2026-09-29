"""AWS Lambda handler for operational audit orchestration.

Receives SQS event messages (triggered by S3 ObjectCreated events on the traces/ prefix),
retrieves raw traces from S3, runs the deterministic multi-control audit engine,
persists the AuditResult to DynamoDB, writes the analytics result to S3,
and publishes safe alerts to SNS if risk tier is HIGH or CRITICAL.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Any

from auditor.orchestrator import (
    AuditOrchestrator,
)

try:
    from .repositories.dynamodb_repository import DynamoDBRepository
    from .repositories.s3_repository import S3Repository
    from .repositories.sns_repository import SNSRepository
except (ImportError, ValueError):
    from repositories.dynamodb_repository import DynamoDBRepository  # type: ignore
    from repositories.s3_repository import S3Repository  # type: ignore
    from repositories.sns_repository import SNSRepository  # type: ignore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def extract_s3_events_from_sqs_record(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract (bucket, key) tuples from an SQS record body.

    Handles:
    1. SQS message containing an S3 Event Notification JSON payload.
    2. Direct JSON payload with {"bucket": "...", "key": "..."}.
    3. Direct JSON payload with {"s3_uri": "s3://..."}.

    Args:
        record: SQS message record dictionary.

    Returns:
        List of (bucket_name, object_key) pairs.
    """
    body_str = record.get("body", "")
    if not body_str:
        return []

    try:
        body = json.loads(body_str) if isinstance(body_str, str) else body_str
    except json.JSONDecodeError:
        logger.warning("SQS record body is not valid JSON: %s", body_str[:200])
        return []

    results: list[tuple[str, str]] = []

    # Case 1: Standard S3 Event Notification format inside SQS message
    if isinstance(body, dict) and "Records" in body:
        for s3_rec in body.get("Records", []):
            s3_data = s3_rec.get("s3", {})
            bucket = s3_data.get("bucket", {}).get("name")
            raw_key = s3_data.get("object", {}).get("key")
            if bucket and raw_key:
                unquoted_key = urllib.parse.unquote_plus(raw_key)
                results.append((bucket, unquoted_key))

    # Case 2: Custom direct SQS message with bucket and key
    elif isinstance(body, dict) and "bucket" in body and "key" in body:
        results.append((body["bucket"], urllib.parse.unquote_plus(body["key"])))

    # Case 3: S3 URI direct payload
    elif isinstance(body, dict) and "s3_uri" in body:
        bucket, key = S3Repository.parse_s3_uri(body["s3_uri"])
        results.append((bucket, key))

    return results


def handler(
    event: dict[str, Any],
    context: Any | None = None,
    orchestrator: AuditOrchestrator | None = None,
    s3_repo: S3Repository | None = None,
    dynamodb_repo: DynamoDBRepository | None = None,
    sns_repo: SNSRepository | None = None,
) -> dict[str, Any]:
    """Audit Lambda entry point for processing SQS trace events.

    Operational flow:
    1. Parse event and extract bucket/key pairs.
    2. Retrieve trace JSON from S3.
    3. Run local audit orchestrator (Validate -> Scope -> PII -> Groundedness -> Risk -> AuditResult).
    4. Write AuditResult to DynamoDB (idempotent write).
    5. Write deterministic analytics result to S3.
    6. Publish safe alert to SNS if risk tier is HIGH or CRITICAL.
    7. Return processing summary.

    Args:
        event: AWS Lambda event payload (SQS or test event).
        context: AWS Lambda execution context.
        orchestrator: Injected AuditOrchestrator (for testing).
        s3_repo: Injected S3Repository (for testing).
        dynamodb_repo: Injected DynamoDBRepository (for testing).
        sns_repo: Injected SNSRepository (for testing).

    Returns:
        Summary dict containing status and processed trace IDs.
    """
    # Initialize dependencies / repositories
    s3_repository = s3_repo or S3Repository()
    dynamodb_table_name = os.environ.get("DYNAMODB_TABLE", "agent-audit-results")
    dynamo_repository = dynamodb_repo or DynamoDBRepository(table_name=dynamodb_table_name)

    results_bucket_env = os.environ.get("RESULTS_BUCKET")
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    sns_repository = sns_repo or (SNSRepository(topic_arn=sns_topic_arn) if sns_topic_arn else None)

    audit_orchestrator = orchestrator or AuditOrchestrator()

    # Step 1: Extract all target trace references from event
    targets: list[tuple[str, str]] = []
    if "Records" in event:
        for rec in event["Records"]:
            # If this is directly an S3 event (e.g. S3 direct invocation or test)
            if "s3" in rec:
                b = rec.get("s3", {}).get("bucket", {}).get("name")
                k = rec.get("s3", {}).get("object", {}).get("key")
                if b and k:
                    targets.append((b, urllib.parse.unquote_plus(k)))
            # Otherwise assume SQS event wrapping an S3 notification
            else:
                extracted = extract_s3_events_from_sqs_record(rec)
                targets.extend(extracted)
    elif "bucket" in event and "key" in event:
        targets.append((event["bucket"], urllib.parse.unquote_plus(event["key"])))
    elif "s3_uri" in event:
        targets.append(S3Repository.parse_s3_uri(event["s3_uri"]))

    if not targets:
        logger.warning("No S3 trace references found in incoming Lambda event")
        return {
            "statusCode": 200,
            "processed_count": 0,
            "results": [],
            "message": "No actionable S3 trace records found",
        }

    processed_results: list[dict[str, Any]] = []

    # Step 2-7: Process each trace reference
    for bucket, key in targets:
        # Ignore files not starting with traces/ or not ending with .json
        if not key.endswith(".json"):
            logger.info("Skipping non-JSON object: s3://%s/%s", bucket, key)
            continue

        raw_trace_s3_uri = f"s3://{bucket}/{key}"
        logger.info("Beginning audit processing for %s", raw_trace_s3_uri)

        # 3. Retrieve raw trace from S3
        trace_dict = s3_repository.get_json(bucket, key)

        # 4-10. Validate, detect scope/PII/groundedness, calculate risk, assemble AuditResult
        audit_result = audit_orchestrator.run(trace_dict, raw_trace_uri=raw_trace_s3_uri)
        trace_id = audit_result["trace_id"]
        task_type = audit_result.get("task_type", "default")
        risk_tier = audit_result.get("risk_tier", "LOW")
        risk_score = audit_result.get("risk_score", 0.0)

        # 11. Write to DynamoDB (idempotent write keyed by trace_id)
        dynamo_repository.save_audit_result(audit_result, raw_trace_s3_uri=raw_trace_s3_uri)
        logger.info("Saved audit result to DynamoDB for trace %s", trace_id)

        # 12. Write deterministic analytics result to S3
        # Extract date string for partition: date=YYYY-MM-DD
        from datetime import datetime, timezone
        processed_at = audit_result.get("processed_at", "")
        date_str = processed_at[:10] if len(processed_at) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Extract counts and metrics for analytics-friendly flat schema
        counts = audit_result.get("counts", {})
        scope_findings = audit_result.get("scope_findings", [])
        groundedness_findings = audit_result.get("groundedness_findings", [])
        contradicted_count = sum(
            1 for f in groundedness_findings
            if f.get("audit_verdict") == "CONTRADICTED" or f.get("nli_verdict") == "CONTRADICTION"
        )
        unsupported_count = int(counts.get("unsupported_claims", 0))
        groundedness_failures = unsupported_count + contradicted_count
        violated_tools = [f.get("tool_name") for f in scope_findings if f.get("tool_name")]

        # Construct analytics-friendly record conforming to Glue/Athena schema
        analytics_record = dict(audit_result)
        analytics_record.update({
            "date": date_str,
            "pii_count": int(counts.get("pii_entities_detected", 0)),
            "scope_violations": int(counts.get("scope_violations", 0)),
            "groundedness_failures": groundedness_failures,
            "unsupported_claims": unsupported_count,
            "contradicted_claims": contradicted_count,
            "violated_tools": violated_tools,
        })

        target_results_bucket = results_bucket_env or bucket
        analytics_key = f"results/date={date_str}/task_type={task_type}/{trace_id}.json"
        analytics_s3_uri = s3_repository.put_json(
            bucket=target_results_bucket,
            key=analytics_key,
            data=analytics_record,
        )
        logger.info("Saved analytics result to S3 at %s", analytics_s3_uri)

        # 13. Publish SNS alert only when configured risk tier is HIGH or CRITICAL
        sns_message_id = None
        if risk_tier in ("HIGH", "CRITICAL") and sns_repository:
            try:
                sns_message_id = sns_repository.publish_risk_alert(
                    trace_id=trace_id,
                    task_type=task_type,
                    risk_score=risk_score,
                    risk_tier=risk_tier,
                    short_explanation=audit_result.get("summary", ""),
                )
                logger.info("Published SNS risk alert (%s) MessageId: %s", risk_tier, sns_message_id)
            except Exception as exc:
                logger.error("Failed to publish SNS alert for trace %s: %s", trace_id, exc)

        processed_results.append({
            "trace_id": trace_id,
            "task_type": task_type,
            "risk_score": risk_score,
            "risk_tier": risk_tier,
            "raw_trace_uri": raw_trace_s3_uri,
            "analytics_s3_uri": analytics_s3_uri,
            "sns_message_id": sns_message_id,
            "status": "PROCESSED",
        })

    return {
        "statusCode": 200,
        "processed_count": len(processed_results),
        "results": processed_results,
    }
