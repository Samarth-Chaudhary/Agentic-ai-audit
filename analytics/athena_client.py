"""Amazon Athena Client module for executing, polling, and retrieving SQL analytics queries."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AthenaClientError(Exception):
    """Base exception for Athena operations."""


class AthenaQueryTimeoutError(AthenaClientError):
    """Raised when query execution exceeds the bounded timeout."""


class AthenaQueryFailedError(AthenaClientError):
    """Raised when query execution enters FAILED state."""


class AthenaQueryCancelledError(AthenaClientError):
    """Raised when query execution is CANCELLED."""


def _cast_athena_value(val_str: str | None, col_type: str) -> Any:
    """Cast string value from Athena result set into appropriate Python native type."""
    if val_str is None:
        return None
    col_type = col_type.lower()
    if col_type in ("int", "integer", "bigint", "smallint", "tinyint"):
        try:
            return int(val_str)
        except (ValueError, TypeError):
            return val_str
    if col_type in ("double", "float", "decimal", "real"):
        try:
            return float(val_str)
        except (ValueError, TypeError):
            return val_str
    if col_type in ("boolean", "bool"):
        return val_str.lower() in ("true", "1", "t")
    if col_type.startswith("array") or col_type.startswith("json"):
        try:
            return json.loads(val_str)
        except (json.JSONDecodeError, TypeError):
            return val_str
    return val_str


class AthenaClient:
    """Manages starting, polling, and retrieving results for Athena queries."""

    def __init__(
        self,
        athena_client: Any | None = None,
        database: str | None = None,
        workgroup: str | None = None,
        output_location: str | None = None,
    ) -> None:
        """Initialize Athena client.

        Args:
            athena_client: Optional injected boto3 Athena client.
            database: Default Glue catalog database name.
            workgroup: Dedicated Athena workgroup name.
            output_location: S3 path for query results (required if workgroup doesn't enforce it).
        """
        self._athena = athena_client or boto3.client("athena")
        self.database = database or os.environ.get("GLUE_DATABASE", "agent_governance_db_dev")
        self.workgroup = workgroup or os.environ.get("ATHENA_WORKGROUP", "agent-audit-workgroup-dev")
        self.output_location = output_location or os.environ.get("ATHENA_OUTPUT_LOCATION")

    def start_query(
        self,
        query: str,
        database: str | None = None,
        workgroup: str | None = None,
        output_location: str | None = None,
    ) -> str:
        """Submit a query to Amazon Athena.

        Args:
            query: SQL query text.
            database: Target database name (overrides default).
            workgroup: Target workgroup (overrides default).
            output_location: Query results S3 location.

        Returns:
            QueryExecutionId string.

        Raises:
            AthenaClientError: On submission failure.
        """
        target_db = database or self.database
        target_wg = workgroup or self.workgroup
        target_output = output_location or self.output_location

        kwargs: dict[str, Any] = {
            "QueryString": query,
            "QueryExecutionContext": {"Database": target_db},
        }
        if target_wg:
            kwargs["WorkGroup"] = target_wg
        if target_output:
            kwargs["ResultConfiguration"] = {"OutputLocation": target_output}

        try:
            response = self._athena.start_query_execution(**kwargs)
            query_id = response.get("QueryExecutionId", "")
            logger.info("Submitted Athena query. QueryExecutionId: %s", query_id)
            return query_id
        except ClientError as exc:
            raise AthenaClientError(f"Failed to submit Athena query: {exc}") from exc

    def poll_query_state(self, query_execution_id: str) -> dict[str, Any]:
        """Check current status and execution metadata of a query.

        Args:
            query_execution_id: Correlated Athena query ID.

        Returns:
            Dict containing state ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')
            and execution details.
        """
        try:
            resp = self._athena.get_query_execution(QueryExecutionId=query_execution_id)
            execution = resp.get("QueryExecution", {})
            status_info = execution.get("Status", {})
            state = status_info.get("State", "UNKNOWN")
            reason = status_info.get("StateChangeReason")
            stats = execution.get("Statistics", {})

            return {
                "query_execution_id": query_execution_id,
                "state": state,
                "reason": reason,
                "data_scanned_bytes": stats.get("DataScannedInBytes", 0),
                "execution_time_ms": stats.get("EngineExecutionTimeInMillis", 0),
            }
        except ClientError as exc:
            raise AthenaClientError(f"Failed to get query execution for {query_execution_id}: {exc}") from exc

    def wait_for_query_completion(
        self,
        query_execution_id: str,
        poll_interval_seconds: float = 1.0,
        timeout_seconds: float = 60.0,
    ) -> str:
        """Poll query status until completion, cancellation, failure, or timeout.

        CRITICAL REQUIREMENT: Never poll forever. Bounded timeout enforced.

        Args:
            query_execution_id: Correlated Athena query ID.
            poll_interval_seconds: Polling sleep interval.
            timeout_seconds: Maximum wait duration.

        Returns:
            Final state ('SUCCEEDED').

        Raises:
            AthenaQueryFailedError: If query fails.
            AthenaQueryCancelledError: If query is cancelled.
            AthenaQueryTimeoutError: If timeout is reached.
        """
        start_time = time.monotonic()
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout_seconds:
                raise AthenaQueryTimeoutError(
                    f"Athena query {query_execution_id} timed out after {elapsed:.1f}s (limit: {timeout_seconds}s)"
                )

            status = self.poll_query_state(query_execution_id)
            state = status["state"]

            if state == "SUCCEEDED":
                logger.info("Athena query %s succeeded in %.2fs", query_execution_id, elapsed)
                return state

            if state == "FAILED":
                reason = status.get("reason", "Unknown failure reason")
                raise AthenaQueryFailedError(f"Athena query {query_execution_id} failed: {reason}")

            if state == "CANCELLED":
                raise AthenaQueryCancelledError(f"Athena query {query_execution_id} was cancelled")

            if state in ("QUEUED", "RUNNING"):
                time.sleep(poll_interval_seconds)
            else:
                raise AthenaClientError(f"Unknown Athena query state '{state}' for {query_execution_id}")

    def get_query_results(
        self,
        query_execution_id: str,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """Retrieve and parse Athena query results into Python dictionaries.

        Converts raw Athena row data into typed key-value records for visualization.

        Args:
            query_execution_id: Query ID in SUCCEEDED state.
            max_results: Max items per page.

        Returns:
            List of row dicts matching column headers.
        """
        try:
            paginator = self._athena.get_paginator("get_query_results")
            page_iterator = paginator.paginate(
                QueryExecutionId=query_execution_id,
                PaginationConfig={"MaxItems": max_results},
            )

            headers: list[tuple[str, str]] = []  # (col_name, col_type)
            rows: list[dict[str, Any]] = []
            is_first_page = True

            for page in page_iterator:
                result_set = page.get("ResultSet", {})
                column_infos = result_set.get("ResultSetMetadata", {}).get("ColumnInfo", [])

                if is_first_page:
                    headers = [(col.get("Name", f"col_{i}"), col.get("Type", "string")) for i, col in enumerate(column_infos)]

                raw_rows = result_set.get("Rows", [])
                start_row_idx = 0

                # On first page, the first row contains header labels; skip it
                if is_first_page and raw_rows:
                    start_row_idx = 1
                    is_first_page = False

                for row_data in raw_rows[start_row_idx:]:
                    cells = row_data.get("Data", [])
                    row_dict: dict[str, Any] = {}
                    for (col_name, col_type), cell in zip(headers, cells, strict=False):
                        val_str = cell.get("VarCharValue")
                        row_dict[col_name] = _cast_athena_value(val_str, col_type)
                    rows.append(row_dict)

            return rows

        except ClientError as exc:
            raise AthenaClientError(f"Failed to fetch results for {query_execution_id}: {exc}") from exc

    def execute_query(
        self,
        query: str,
        database: str | None = None,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Convenience method: start, wait, and retrieve query results.

        Args:
            query: SQL query text.
            database: Optional database override.
            timeout_seconds: Maximum query duration.
            poll_interval_seconds: State poll frequency.

        Returns:
            List of result row dictionaries.
        """
        query_id = self.start_query(query=query, database=database)
        self.wait_for_query_completion(query_id, poll_interval_seconds=poll_interval_seconds, timeout_seconds=timeout_seconds)
        return self.get_query_results(query_id)

    @staticmethod
    def load_sql_file(file_path: str | Path) -> str:
        """Load SQL query text from file.

        Args:
            file_path: Path to .sql file.

        Returns:
            SQL query string.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"SQL file not found: {file_path}")
        return path.read_text(encoding="utf-8").strip()
