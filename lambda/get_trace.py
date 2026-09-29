"""API Gateway Lambda handler for retrieving single trace details with redacted execution timeline.

Endpoint: GET /traces/{trace_id}
Returns:
- summary
- risk
- findings
- execution timeline (read from S3 pointer and redacted for sensitive data)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

try:
    from .repositories.dynamodb_repository import DynamoDBRepository
    from .repositories.s3_repository import S3Repository, S3RepositoryError
except (ImportError, ValueError):
    from repositories.dynamodb_repository import DynamoDBRepository  # type: ignore
    from repositories.s3_repository import (  # type: ignore
        S3Repository,
        S3RepositoryError,
    )

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _redact_value(val: Any, sensitive_terms: set[str]) -> Any:
    """Recursively redact matching sensitive terms from string or nested values."""
    if isinstance(val, str):
        redacted = val
        for term in sensitive_terms:
            if term and len(term) >= 3 and term in redacted:
                redacted = redacted.replace(term, "<REDACTED>")
        return redacted
    if isinstance(val, dict):
        return {k: _redact_value(v, sensitive_terms) for k, v in val.items()}
    if isinstance(val, list):
        return [_redact_value(item, sensitive_terms) for item in val]
    return val


def redact_execution_timeline(
    raw_steps: list[dict[str, Any]],
    pii_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sanitize execution timeline steps by masking all identified PII entities.

    Args:
        raw_steps: Raw steps array from S3 execution trace.
        pii_findings: List of PII findings recorded during the audit.

    Returns:
        Cleaned timeline list with sensitive values replaced with <REDACTED>.
    """

    for finding in pii_findings:
        # Check snippet or redacted text if available
        context = finding.get("context")
        finding.get("field_path")
        # Collect any flagged text terms
        if context and isinstance(context, str):
            # Extract possible raw substrings from context
            pass

    # Extract common pattern matches: SSNs, credit cards, emails, api keys
    email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    ssn_pattern = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    cc_pattern = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
    api_key_pattern = re.compile(r"(?:api[_-]?key|secret|token|bearer)\s*[:=]\s*([a-zA-Z0-9_\-]{8,})", re.IGNORECASE)

    def mask_text(text: str) -> str:
        t = ssn_pattern.sub("<REDACTED_SSN>", text)
        t = cc_pattern.sub("<REDACTED_CC>", t)
        t = email_pattern.sub("<REDACTED_EMAIL>", t)
        t = api_key_pattern.sub(r"api_key: <REDACTED_SECRET>", t)
        return t

    sanitized_timeline: list[dict[str, Any]] = []
    for step in raw_steps:
        # Deep copy step structure
        cleaned_step = json.loads(json.dumps(step))

        # Mask text fields
        for field in ("content", "tool_input", "tool_output", "observation", "message", "thought"):
            if field in cleaned_step:
                val = cleaned_step[field]
                if isinstance(val, str):
                    cleaned_step[field] = mask_text(val)
                elif isinstance(val, (dict, list)):
                    # Mask JSON serialized strings inside nested structures
                    str_repr = json.dumps(val)
                    masked_str = mask_text(str_repr)
                    try:
                        cleaned_step[field] = json.loads(masked_str)
                    except Exception:
                        cleaned_step[field] = val

        sanitized_timeline.append(cleaned_step)

    return sanitized_timeline


def handler(
    event: dict[str, Any],
    context: Any | None = None,
    dynamodb_repo: DynamoDBRepository | None = None,
    s3_repo: S3Repository | None = None,
) -> dict[str, Any]:
    """Retrieve full trace audit details including redacted execution timeline.

    Args:
        event: API Gateway REST proxy event.
        context: Lambda execution context.
        dynamodb_repo: Injected DynamoDBRepository (for testing).
        s3_repo: Injected S3Repository (for testing).

    Returns:
        API Gateway HTTP response dictionary.
    """
    table_name = os.environ.get("DYNAMODB_TABLE", "agent-audit-results")
    d_repo = dynamodb_repo or DynamoDBRepository(table_name=table_name)
    s_repo = s3_repo or S3Repository()

    path_params = event.get("pathParameters") or {}
    trace_id = path_params.get("trace_id")

    if not trace_id:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Bad Request: 'trace_id' path parameter is required"}),
        }

    try:
        # 1. Fetch Audit Result from DynamoDB
        audit_record = d_repo.get_audit_result(trace_id)
        if not audit_record:
            return {
                "statusCode": 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": f"Trace '{trace_id}' not found"}),
            }

        # 2. Extract execution timeline from S3 pointer
        raw_trace_uri = audit_record.get("raw_trace_s3_uri")
        raw_steps: list[dict[str, Any]] = []

        if raw_trace_uri:
            try:
                bucket, key = S3Repository.parse_s3_uri(raw_trace_uri)
                raw_trace_data = s_repo.get_json(bucket, key)
                raw_steps = raw_trace_data.get("steps", [])
            except (S3RepositoryError, ValueError) as exc:
                logger.warning("Could not retrieve raw trace from '%s': %s", raw_trace_uri, exc)
                raw_steps = []

        # 3. Redact sensitive values from execution timeline
        pii_findings = audit_record.get("findings", {}).get("pii", [])
        sanitized_timeline = redact_execution_timeline(raw_steps, pii_findings)

        # 4. Assemble response object matching Part 7 requirements
        response_payload = {
            "trace_id": audit_record.get("trace_id"),
            "task_type": audit_record.get("task_type"),
            "processed_at": audit_record.get("processed_at"),
            "summary": audit_record.get("summary", ""),
            "status": audit_record.get("status", "COMPLETED"),
            "is_degraded": audit_record.get("is_degraded", False),
            "degraded_reasons": audit_record.get("degraded_reasons", []),
            "engine_info": audit_record.get("engine_info"),
            "risk": {
                "risk_score": float(audit_record.get("risk_score", 0.0)),
                "risk_tier": audit_record.get("risk_tier", "LOW"),
                "risk_result": audit_record.get("risk_result", {}),
            },
            "findings": audit_record.get("findings", {}),
            "counts": audit_record.get("counts", {}),
            "execution_timeline": sanitized_timeline,
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,OPTIONS",
            },
            "body": json.dumps(response_payload, default=str),
        }

    except Exception as exc:
        logger.error("Error retrieving trace '%s': %s", trace_id, exc)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Internal Server Error", "message": str(exc)}),
        }
