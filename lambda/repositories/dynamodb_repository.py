"""DynamoDB repository module for persisting and retrieving audit results."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError


class DynamoDBRepositoryError(Exception):
    """Base exception for DynamoDB repository operations."""


class DynamoDBNotFoundError(DynamoDBRepositoryError):
    """Raised when an item is not found."""


def _convert_floats_to_decimals(obj: Any) -> Any:
    """Recursively convert float objects to Decimal for DynamoDB storage."""
    if isinstance(obj, float):
        # Rounding/converting to string representation avoids binary float imprecision
        return Decimal(str(round(obj, 6)))
    if isinstance(obj, dict):
        return {k: _convert_floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_floats_to_decimals(item) for item in obj]
    return obj


def _convert_decimals_to_native(obj: Any) -> Any:
    """Recursively convert Decimal objects to int or float for JSON serialization."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _convert_decimals_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_decimals_to_native(item) for item in obj]
    return obj


class DynamoDBRepository:
    """Encapsulates all DynamoDB operations for agent audit results."""

    def __init__(
        self,
        table_name: str | None = None,
        dynamodb_resource: Any | None = None,
    ) -> None:
        """Initialize repository with optional table name and injected resource.

        Args:
            table_name: DynamoDB table name (defaults to 'agent-audit-results' if unset).
            dynamodb_resource: boto3 DynamoDB resource.
        """
        self.table_name = table_name or "agent-audit-results"
        self._dynamodb = dynamodb_resource or boto3.resource("dynamodb")
        self._table = self._dynamodb.Table(self.table_name)

    def save_audit_result(
        self,
        audit_result: dict[str, Any],
        raw_trace_s3_uri: str | None = None,
    ) -> dict[str, Any]:
        """Save an audit result item idempotently into DynamoDB.

        Per specification, stores at least:
        - trace_id (Partition Key)
        - task_type
        - processed_at
        - risk_score
        - risk_tier
        - findings (scope, pii, groundedness)
        - counts
        - raw_trace_s3_uri

        Does NOT store the entire raw execution trace in DynamoDB.

        Args:
            audit_result: Validated AuditResult dictionary.
            raw_trace_s3_uri: Canonical S3 URI pointing to the raw trace JSON.

        Returns:
            The formatted item as persisted.

        Raises:
            DynamoDBRepositoryError: On persistence failure.
        """
        trace_id = audit_result.get("trace_id")
        if not trace_id:
            raise DynamoDBRepositoryError("Missing 'trace_id' in audit_result")

        # Determine raw trace pointer
        pointer_obj = audit_result.get("raw_trace_storage_pointer") or {}
        trace_uri = (
            raw_trace_s3_uri
            or pointer_obj.get("s3_uri")
            or f"s3://{pointer_obj.get('s3_bucket', 'unknown')}/{pointer_obj.get('s3_key', 'unknown')}"
        )

        # Structure findings map
        findings = {
            "scope": audit_result.get("scope_findings", []),
            "pii": audit_result.get("pii_findings", []),
            "groundedness": audit_result.get("groundedness_findings", []),
        }

        # Item payload conforming to Part 7 specification
        item: dict[str, Any] = {
            "trace_id": trace_id,
            "task_type": audit_result.get("task_type", "default"),
            "processed_at": audit_result.get("processed_at", ""),
            "risk_score": audit_result.get("risk_score", 0.0),
            "risk_tier": audit_result.get("risk_tier", "LOW"),
            "findings": findings,
            "counts": audit_result.get("counts", {}),
            "summary": audit_result.get("summary", ""),
            "raw_trace_s3_uri": trace_uri,
            "status": audit_result.get("status", "COMPLETED"),
        }

        if "engine_info" in audit_result:
            item["engine_info"] = audit_result["engine_info"]
        if "is_degraded" in audit_result:
            item["is_degraded"] = audit_result["is_degraded"]
        if "degraded_reasons" in audit_result:
            item["degraded_reasons"] = audit_result["degraded_reasons"]

        if audit_result.get("risk_result"):
            item["risk_result"] = audit_result["risk_result"]

        # Convert float to Decimal for DynamoDB
        ddb_item = _convert_floats_to_decimals(item)

        try:
            self._table.put_item(Item=ddb_item)
            return item
        except ClientError as exc:
            raise DynamoDBRepositoryError(f"Failed to save audit result for trace {trace_id}: {exc}") from exc
        except Exception as exc:
            raise DynamoDBRepositoryError(f"Unexpected error saving trace {trace_id}: {exc}") from exc

    def get_audit_result(self, trace_id: str) -> dict[str, Any] | None:
        """Retrieve audit result item by trace_id.

        Args:
            trace_id: Correlated trace identifier.

        Returns:
            Audit result dict with native Python types, or None if not found.
        """
        try:
            response = self._table.get_item(Key={"trace_id": trace_id})
            item = response.get("Item")
            if not item:
                return None
            return _convert_decimals_to_native(item)
        except ClientError as exc:
            raise DynamoDBRepositoryError(f"Failed to get trace {trace_id}: {exc}") from exc

    def list_audit_results(
        self,
        limit: int = 20,
        last_evaluated_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Scan table for audit result summaries with pagination.

        Does not return full findings/raw details in overview listing.

        Args:
            limit: Maximum items to return per page (default 20, max 100).
            last_evaluated_key: ExclusiveStartKey for pagination.

        Returns:
            Tuple of (list_of_summary_items, next_evaluated_key_or_none).
        """
        limit = min(max(1, limit), 100)
        scan_kwargs: dict[str, Any] = {
            "Limit": limit,
            "ProjectionExpression": "trace_id, task_type, risk_score, risk_tier, processed_at, counts, summary, is_degraded, engine_info",
        }
        if last_evaluated_key:
            scan_kwargs["ExclusiveStartKey"] = _convert_floats_to_decimals(last_evaluated_key)

        try:
            response = self._table.scan(**scan_kwargs)
            raw_items = response.get("Items", [])
            items = [_convert_decimals_to_native(item) for item in raw_items]
            next_key = response.get("LastEvaluatedKey")
            native_next_key = _convert_decimals_to_native(next_key) if next_key else None
            return items, native_next_key
        except ClientError as exc:
            raise DynamoDBRepositoryError(f"Failed to scan audit results: {exc}") from exc
