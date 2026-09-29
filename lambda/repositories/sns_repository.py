"""SNS Repository module for publishing high-risk alerts safely."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError


class SNSRepositoryError(Exception):
    """Base exception for SNS repository operations."""


class SNSRepository:
    """Encapsulates SNS publishing for agent governance risk alerts."""

    def __init__(
        self,
        topic_arn: str | None = None,
        sns_client: Any | None = None,
    ) -> None:
        """Initialize SNS repository with optional topic ARN and injected client.

        Args:
            topic_arn: ARN of the target SNS topic.
            sns_client: boto3 SNS client.
        """
        self.topic_arn = topic_arn
        self._sns = sns_client or boto3.client("sns")

    def publish_risk_alert(
        self,
        trace_id: str,
        task_type: str,
        risk_score: float,
        risk_tier: str,
        short_explanation: str,
    ) -> str:
        """Publish a safe alert summary to the configured SNS topic.

        CRITICAL REQUIREMENT:
        Never include raw PII, sensitive credentials, or unredacted secrets in alerts.
        Only metadata and sanitized explanations are transmitted.

        Args:
            trace_id: Correlated trace identifier.
            task_type: Task classification type.
            risk_score: Composite risk score (0.0 - 100.0).
            risk_tier: Risk level string (HIGH or CRITICAL).
            short_explanation: Deterministic summary explanation.

        Returns:
            Published SNS MessageId.

        Raises:
            SNSRepositoryError: If publishing fails or topic ARN is unset.
        """
        if not self.topic_arn:
            raise SNSRepositoryError("Cannot publish SNS alert: topic_arn is not configured")

        if risk_tier not in ("HIGH", "CRITICAL"):
            raise ValueError(f"SNS alerts are only published for HIGH or CRITICAL tiers, got: '{risk_tier}'")

        alert_payload = {
            "alert_type": "AI_AGENT_GOVERNANCE_RISK_VIOLATION",
            "trace_id": trace_id,
            "task_type": task_type,
            "risk_score": round(float(risk_score), 2),
            "risk_tier": risk_tier,
            "short_explanation": short_explanation,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

        subject = f"[GOVERNANCE ALERT - {risk_tier}] Trace {trace_id} ({task_type}) Risk: {risk_score:.1f}"

        message_attributes = {
            "RiskTier": {
                "DataType": "String",
                "StringValue": risk_tier,
            },
            "TaskType": {
                "DataType": "String",
                "StringValue": task_type,
            },
        }

        try:
            response = self._sns.publish(
                TopicArn=self.topic_arn,
                Subject=subject[:100],  # SNS Subject max 100 chars
                Message=json.dumps(alert_payload, indent=2),
                MessageAttributes=message_attributes,
            )
            return response.get("MessageId", "")
        except ClientError as exc:
            raise SNSRepositoryError(f"Failed to publish SNS alert for trace {trace_id}: {exc}") from exc
        except Exception as exc:
            raise SNSRepositoryError(f"Unexpected error publishing alert for trace {trace_id}: {exc}") from exc
