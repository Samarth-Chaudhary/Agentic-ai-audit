"""S3 Repository module for reading and writing audit traces and analytics results."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


class S3RepositoryError(Exception):
    """Base exception for S3 repository operations."""


class S3NotFoundError(S3RepositoryError):
    """Raised when an object or bucket is not found."""


class S3Repository:
    """Encapsulates all S3 operations for audit traces and analytics results."""

    def __init__(self, s3_client: Any | None = None) -> None:
        """Initialize S3 repository with optional injected client.

        Args:
            s3_client: Pre-configured boto3 S3 client (useful for testing/mocking).
        """
        self._s3 = s3_client or boto3.client("s3")

    @staticmethod
    def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
        """Parse s3://bucket/key into (bucket, key).

        Args:
            s3_uri: S3 URI string.

        Returns:
            Tuple of (bucket_name, object_key).

        Raises:
            ValueError: If URI does not use s3 scheme or lacks bucket/key.
        """
        parsed = urlparse(s3_uri)
        if parsed.scheme != "s3":
            raise ValueError(f"Invalid S3 URI scheme '{parsed.scheme}': expected 's3'")
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URI '{s3_uri}': missing bucket or key")
        return bucket, key

    def get_object_as_string(self, bucket: str, key: str) -> str:
        """Retrieve an object's contents as a UTF-8 string.

        Args:
            bucket: S3 bucket name.
            key: Object key.

        Returns:
            Decoded UTF-8 string content.

        Raises:
            S3NotFoundError: If object does not exist.
            S3RepositoryError: On S3 access or network error.
        """
        try:
            response = self._s3.get_object(Bucket=bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                raise S3NotFoundError(f"Object not found: s3://{bucket}/{key}") from exc
            raise S3RepositoryError(f"Failed to read s3://{bucket}/{key}: {exc}") from exc
        except Exception as exc:
            raise S3RepositoryError(f"Unexpected error reading s3://{bucket}/{key}: {exc}") from exc

    def get_json(self, bucket: str, key: str) -> dict[str, Any]:
        """Retrieve and parse JSON object from S3.

        Args:
            bucket: S3 bucket name.
            key: Object key.

        Returns:
            Parsed JSON dictionary.

        Raises:
            S3RepositoryError: If content is invalid JSON or S3 fails.
        """
        raw_text = self.get_object_as_string(bucket, key)
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise S3RepositoryError(f"Malformed JSON in s3://{bucket}/{key}: {exc}") from exc

    def put_json(
        self,
        bucket: str,
        key: str,
        data: dict[str, Any] | list[Any],
        indent: int | None = 2,
    ) -> str:
        """Serialize data to JSON and upload to S3 with deterministic formatting.

        Args:
            bucket: S3 bucket name.
            key: Object key.
            data: Data to serialize as JSON.
            indent: JSON indentation level (default 2).

        Returns:
            Canonical S3 URI string: s3://{bucket}/{key}.
        """
        content = json.dumps(data, indent=indent, default=str)
        return self.put_string(bucket=bucket, key=key, content=content, content_type="application/json")

    def put_string(
        self,
        bucket: str,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> str:
        """Upload raw string content to S3.

        Args:
            bucket: S3 bucket name.
            key: Object key.
            content: Raw string payload.
            content_type: MIME content type header.

        Returns:
            Canonical S3 URI string: s3://{bucket}/{key}.
        """
        try:
            self._s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType=content_type,
            )
            return f"s3://{bucket}/{key}"
        except ClientError as exc:
            raise S3RepositoryError(f"Failed to write to s3://{bucket}/{key}: {exc}") from exc

    def object_exists(self, bucket: str, key: str) -> bool:
        """Check whether an object exists in S3.

        Args:
            bucket: S3 bucket name.
            key: Object key.

        Returns:
            True if object exists, False otherwise.
        """
        try:
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise S3RepositoryError(f"Failed to check existence of s3://{bucket}/{key}: {exc}") from exc
