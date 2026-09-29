"""API Gateway Lambda handler for listing audit traces with pagination.

Endpoint: GET /traces
Returns paginated summary records containing core governance metrics without large payloads.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

try:
    from .repositories.dynamodb_repository import DynamoDBRepository
except (ImportError, ValueError):
    from repositories.dynamodb_repository import DynamoDBRepository  # type: ignore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _encode_next_token(key_dict: dict[str, Any] | None) -> str | None:
    """Encode DynamoDB LastEvaluatedKey to a base64 token string."""
    if not key_dict:
        return None
    try:
        raw_bytes = json.dumps(key_dict).encode("utf-8")
        return base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    except Exception as exc:
        logger.warning("Failed to encode next_token: %s", exc)
        return None


def _decode_next_token(token_str: str | None) -> dict[str, Any] | None:
    """Decode a base64 next_token string back into a DynamoDB key dict."""
    if not token_str:
        return None
    try:
        raw_bytes = base64.urlsafe_b64decode(token_str.encode("utf-8"))
        return json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to decode next_token '%s': %s", token_str, exc)
        return None


def handler(
    event: dict[str, Any],
    context: Any | None = None,
    dynamodb_repo: DynamoDBRepository | None = None,
) -> dict[str, Any]:
    """List traces API Gateway Lambda handler.

    Args:
        event: API Gateway REST proxy event.
        context: Lambda execution context.
        dynamodb_repo: Injected DynamoDBRepository (for testing).

    Returns:
        API Gateway HTTP response dictionary.
    """
    table_name = os.environ.get("DYNAMODB_TABLE", "agent-audit-results")
    repo = dynamodb_repo or DynamoDBRepository(table_name=table_name)

    query_params = event.get("queryStringParameters") or {}

    # Parse limit
    try:
        limit_param = int(query_params.get("limit", 20))
    except (ValueError, TypeError):
        limit_param = 20

    # Parse pagination token
    next_token_param = query_params.get("next_token")
    start_key = _decode_next_token(next_token_param)

    try:
        items, last_eval_key = repo.list_audit_results(limit=limit_param, last_evaluated_key=start_key)

        # Build clean summary records adhering strictly to Part 7 specification
        summary_records = []
        for item in items:
            counts = item.get("counts") or {}
            summary_records.append({
                "trace_id": item.get("trace_id"),
                "task_type": item.get("task_type"),
                "risk_score": float(item.get("risk_score", 0.0)),
                "risk_tier": item.get("risk_tier", "LOW"),
                "processed_at": item.get("processed_at"),
                "is_degraded": bool(item.get("is_degraded", False)),
                "engine_info": item.get("engine_info"),
                "pii_count": int(counts.get("pii_entities_detected", 0)),
                "scope_violation_count": int(counts.get("scope_violations", 0)),
                "groundedness_failure_count": int(counts.get("unsupported_claims", 0)),
            })

        response_body = {
            "items": summary_records,
            "count": len(summary_records),
            "next_token": _encode_next_token(last_eval_key),
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,OPTIONS",
            },
            "body": json.dumps(response_body),
        }

    except Exception as exc:
        logger.error("Error listing traces: %s", exc)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Internal Server Error", "message": str(exc)}),
        }
