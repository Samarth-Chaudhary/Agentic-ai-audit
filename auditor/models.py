"""Data models for AI Agent Governance & Audit Trail Analyzer.

Strictly aligned with schemas/trace.schema.json and schemas/audit_result.schema.json.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def compute_step_hash(
    prev_step_hash: str | None,
    index: int,
    step_type: str,
    payload: Any,
    timestamp: str | None,
) -> str:
    """Compute SHA-256 cryptographic hash sealing an execution step and binding to preceding hash."""
    prev = prev_step_hash or ("0" * 64)
    normalized_payload = json.dumps(payload, sort_keys=True, default=str) if payload is not None else ""
    raw = f"{prev}|{index}|{step_type}|{normalized_payload}|{timestamp or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class StepType(str, Enum):
    """Observable agent step execution types."""
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"


class RiskTier(str, Enum):
    """Categorical risk tiers."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TraceStep(BaseModel):
    """A single observable step in an agent execution trace.

    Contains observable content only. Private chain-of-thought is excluded by contract.
    """
    index: int = Field(ge=0, description="0-based step index")
    type: StepType = Field(description="Step type discriminator")
    timestamp: str | None = Field(default=None, description="Optional ISO 8601 timestamp")
    call_id: str | None = Field(default=None, description="Correlation identifier for tool call & result")
    content: str | None = Field(default=None, description="Content of assistant message")
    tool_name: str | None = Field(default=None, description="Tool name for tool_call and tool_result")
    input: Any | None = Field(default=None, description="Input payload for tool_call")
    output: Any | None = Field(default=None, description="Output payload for tool_result")
    message: str | None = Field(default=None, description="Error message for error step")
    error_code: str | None = Field(default=None, description="Optional error classification")
    details: dict[str, Any] | None = Field(default=None, description="Optional metadata details")
    prev_step_hash: str | None = Field(default=None, description="Cryptographic SHA-256 hash of preceding step")
    step_hash: str | None = Field(default=None, description="Cryptographic SHA-256 hash sealing this step")

    @model_validator(mode="before")
    @classmethod
    def normalize_step_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_type = data.get("type")
            if isinstance(raw_type, str):
                t_lower = raw_type.lower()
                if t_lower in ("user_input", "user", "human", "prompt", "input", "system"):
                    data["type"] = StepType.ASSISTANT_MESSAGE.value
                    if not data.get("content"):
                        data["content"] = str(data.get("input") or data.get("message") or data.get("text") or "User request")
                elif t_lower in ("assistant_message", "tool_call", "tool_result", "error"):
                    data["type"] = t_lower
        return data

    @model_validator(mode="after")
    def validate_step_contract(self) -> TraceStep:
        if self.type == StepType.TOOL_CALL:
            if not self.tool_name:
                raise ValueError("Step of type 'tool_call' requires 'tool_name'")
            if self.input is None:
                raise ValueError("Step of type 'tool_call' requires 'input'")
        elif self.type == StepType.TOOL_RESULT:
            if not self.tool_name:
                raise ValueError("Step of type 'tool_result' requires 'tool_name'")
            if self.output is None:
                raise ValueError("Step of type 'tool_result' requires 'output'")
        elif self.type == StepType.ASSISTANT_MESSAGE:
            if self.content is None:
                raise ValueError("Step of type 'assistant_message' requires 'content'")
        elif self.type == StepType.ERROR:
            if self.message is None:
                raise ValueError("Step of type 'error' requires 'message'")
        return self


class Trace(BaseModel):
    """Primary data contract model for agent execution traces."""
    trace_id: str = Field(min_length=1, description="Unique trace identifier")
    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="Schema semantic version")
    task_type: str = Field(min_length=1, description="Task category identifying policy")
    started_at: str = Field(description="Trace start ISO date-time string")
    ended_at: str = Field(description="Trace end ISO date-time string")
    metadata: dict[str, Any] | None = Field(default=None, description="Contextual execution metadata")
    steps: list[TraceStep] = Field(min_length=1, description="Observable step list")
    final_answer: str = Field(description="Final answer delivered to caller")
    merkle_root_hash: str | None = Field(default=None, description="Cryptographic root sealing execution chain")

    def verify_integrity(self) -> tuple[bool, str | None]:
        """Verify cryptographic chain of custody and tamper-evidence across all steps."""
        if not self.steps:
            return True, None

        if not self.steps[0].step_hash:
            return True, None

        expected_prev = "0" * 64
        for step in self.steps:
            if step.prev_step_hash and step.prev_step_hash != expected_prev:
                return False, f"Broken chain link at step {step.index}: expected prev {expected_prev}, got {step.prev_step_hash}"

            payload = step.input if step.type == StepType.TOOL_CALL else (step.output if step.type == StepType.TOOL_RESULT else (step.content if step.type == StepType.ASSISTANT_MESSAGE else step.message))
            recomputed = compute_step_hash(step.prev_step_hash, step.index, step.type.value, payload, step.timestamp)
            if step.step_hash and step.step_hash != recomputed:
                return False, f"Cryptographic integrity violation at step {step.index}: step payload tampered with (expected {recomputed}, recorded {step.step_hash})"

            expected_prev = step.step_hash or recomputed

        if self.merkle_root_hash and self.merkle_root_hash != expected_prev:
            return False, f"Merkle root mismatch: expected {expected_prev}, recorded {self.merkle_root_hash}"

        return True, None


class ScopeFinding(BaseModel):
    """Audit finding for tool/data-source permission, business rules, and call limits."""
    finding_id: str = Field(default_factory=lambda: f"sc-{uuid.uuid4().hex[:8]}", description="Unique finding identifier")
    step_index: int | None = Field(default=None, ge=0, description="Step index where violation occurred")
    tool_name: str = Field(description="Name of tool involved in violation")
    rule_violated: str = Field(description="Specific rule or condition violated (e.g. tool_not_allowed)")
    severity: RiskTier = Field(default=RiskTier.HIGH, description="Severity rating (LOW, MEDIUM, HIGH, CRITICAL)")
    detail: str = Field(description="Explanatory narrative detailing why the violation occurred")
    violation_type: str | None = Field(default=None, description="Category classification")
    details: str | None = Field(default=None, description="Detailed description alias")

    engine: str | None = Field(default=None, description="Concrete engine that evaluated the finding")

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync rule_violated and violation_type
            if "rule_violated" not in data and "violation_type" in data:
                data["rule_violated"] = data["violation_type"]
            elif "violation_type" not in data and "rule_violated" in data:
                data["violation_type"] = data["rule_violated"]

            # Sync detail and details
            if "detail" not in data and "details" in data:
                data["detail"] = data["details"]
            elif "details" not in data and "detail" in data:
                data["details"] = data["detail"]

            # Normalize severity to uppercase string for RiskTier enum
            if "severity" in data and isinstance(data["severity"], str):
                data["severity"] = data["severity"].upper()

            # Ensure finding_id is populated
            if "finding_id" not in data or not data["finding_id"]:
                data["finding_id"] = f"sc-{uuid.uuid4().hex[:8]}"

        return data


class PIIFinding(BaseModel):
    """Audit finding for sensitive data, PII, and secret detection."""
    finding_id: str = Field(default_factory=lambda: f"pii-{uuid.uuid4().hex[:8]}", description="Unique finding identifier")
    step_index: int | None = Field(default=None, ge=0, description="Step index containing PII, or None if in final_answer")
    field_path: str = Field(description="Hierarchical field path (e.g. 'steps[2].output.customer.email')")
    field_name: str | None = Field(default=None, description="Field name alias")
    pii_type: str = Field(description="Detected sensitive type (e.g. EMAIL, PHONE, CARD_NUMBER, API_KEY)")
    entity_type: str | None = Field(default=None, description="Entity type alias")
    severity: RiskTier = Field(description="Severity rating")
    redacted_snippet: str = Field(description="Redacted snippet showing context")
    snippet_redacted: str | None = Field(default=None, description="Redacted snippet alias")
    detection_method: str = Field(default="regex", description="Detection method (regex, regex+luhn, presidio)")
    context: str | None = Field(default=None, description="Contextual classification for audit interpretation")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Detection confidence score")
    engine: str | None = Field(default=None, description="Concrete PII/regex engine that detected the entity")

    @model_validator(mode="before")
    @classmethod
    def normalize_pii_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync field_path and field_name
            if "field_path" not in data and "field_name" in data:
                data["field_path"] = data["field_name"]
            elif "field_name" not in data and "field_path" in data:
                data["field_name"] = data["field_path"]

            # Sync pii_type and entity_type
            if "pii_type" not in data and "entity_type" in data:
                data["pii_type"] = data["entity_type"]
            elif "entity_type" not in data and "pii_type" in data:
                data["entity_type"] = data["pii_type"]

            # Sync redacted_snippet and snippet_redacted
            if "redacted_snippet" not in data and "snippet_redacted" in data:
                data["redacted_snippet"] = data["snippet_redacted"]
            elif "snippet_redacted" not in data and "redacted_snippet" in data:
                data["snippet_redacted"] = data["redacted_snippet"]

            # Normalize severity string to uppercase for RiskTier
            if "severity" in data and isinstance(data["severity"], str):
                data["severity"] = data["severity"].upper()

            if "finding_id" not in data or not data["finding_id"]:
                data["finding_id"] = f"pii-{uuid.uuid4().hex[:8]}"

        return data


class GroundednessFinding(BaseModel):
    """Audit finding for hallucination and grounding analysis against tool outputs."""
    finding_id: str = Field(default_factory=lambda: f"gr-{uuid.uuid4().hex[:8]}", description="Unique finding identifier")
    claim: str = Field(description="Extracted claim or statement evaluated")
    statement: str | None = Field(default=None, description="Statement alias for claim")
    evidence_snippet: str = Field(description="Evidence text snippet matched")
    evidence_context: str | None = Field(default=None, description="Context alias for evidence snippet")
    evidence_step_index: int | None = Field(default=None, ge=0, description="Step index of evidence tool result")
    tool_name: str | None = Field(default=None, description="Tool name that produced evidence")
    similarity: float = Field(ge=-1.0, le=1.0, description="Embedding cosine similarity score")
    similarity_score: float | None = Field(default=None, ge=-1.0, le=1.0, description="Similarity score alias")
    nli_verdict: str | None = Field(default=None, description="NLI classification: ENTAILMENT, CONTRADICTION, NEUTRAL")
    audit_verdict: str | None = Field(default=None, description="Final audit verdict: SUPPORTED, CONTRADICTED, UNSUPPORTED")
    is_grounded: bool = Field(default=True, description="True if claim is supported by tool evidence")
    severity: RiskTier = Field(default=RiskTier.LOW, description="Severity rating")
    engine: str | None = Field(default=None, description="Concrete NLI/heuristic engine that evaluated the claim")

    @model_validator(mode="before")
    @classmethod
    def normalize_groundedness_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync claim and statement
            if "claim" not in data and "statement" in data:
                data["claim"] = data["statement"]
            elif "statement" not in data and "claim" in data:
                data["statement"] = data["claim"]

            # Sync evidence_snippet and evidence_context
            if "evidence_snippet" not in data and "evidence_context" in data:
                data["evidence_snippet"] = data["evidence_context"]
            elif "evidence_context" not in data and "evidence_snippet" in data:
                data["evidence_context"] = data["evidence_snippet"]

            # Sync similarity and similarity_score
            if "similarity" not in data and "similarity_score" in data:
                data["similarity"] = data["similarity_score"]
            elif "similarity_score" not in data and "similarity" in data:
                data["similarity_score"] = data["similarity"]

            # Sync is_grounded and audit_verdict
            if "audit_verdict" in data and "is_grounded" not in data:
                data["is_grounded"] = (data["audit_verdict"] == "SUPPORTED")
            elif "is_grounded" in data and "audit_verdict" not in data:
                data["audit_verdict"] = "SUPPORTED" if data["is_grounded"] else "UNSUPPORTED"

            # Sync severity
            if "severity" in data and isinstance(data["severity"], str):
                data["severity"] = data["severity"].upper()
            elif "audit_verdict" in data and "severity" not in data:
                verdict = data["audit_verdict"]
                if verdict == "CONTRADICTED":
                    data["severity"] = RiskTier.CRITICAL
                elif verdict == "UNSUPPORTED":
                    data["severity"] = RiskTier.HIGH
                else:
                    data["severity"] = RiskTier.LOW

            if "finding_id" not in data or not data["finding_id"]:
                data["finding_id"] = f"gr-{uuid.uuid4().hex[:8]}"

        return data


class CountsSummary(BaseModel):
    """Aggregated counters for execution steps and audit findings."""
    total_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_results: int = Field(ge=0)
    errors: int = Field(ge=0)
    scope_violations: int = Field(ge=0)
    pii_entities_detected: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)


class RawTracePointer(BaseModel):
    """S3 storage locator for the raw trace file."""
    s3_bucket: str = Field(description="S3 bucket name")
    s3_key: str = Field(description="S3 object key")
    s3_uri: str = Field(description="Full S3 URI (s3://bucket/key)")


class RiskResult(BaseModel):
    """Detailed risk scoring component breakdown."""
    scope_score: float = Field(ge=0.0, le=100.0)
    pii_score: float = Field(ge=0.0, le=100.0)
    groundedness_score: float = Field(ge=0.0, le=100.0)
    overall_score: float = Field(ge=0.0, le=100.0)
    risk_tier: RiskTier


class EngineInfo(BaseModel):
    """Concrete engine identity and degradation status for governance audit."""
    nli_engine: str = Field(description="Concrete NLI model identifier and version")
    embedding_engine: str = Field(description="Concrete embedding model identifier and version")
    pii_engine: str = Field(description="Concrete PII detection engine")
    is_degraded: bool = Field(default=False, description="Whether any engine operated in degraded fallback mode")
    degraded_reasons: list[str] = Field(default_factory=list, description="Explanations for degraded operation")


class AuditResult(BaseModel):
    """Complete audit engine output for both DynamoDB operational storage and S3 analytics."""
    trace_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    processed_at: str = Field(description="Audit completion ISO timestamp")
    risk_score: float = Field(ge=0.0, le=100.0, description="Overall risk score")
    risk_tier: RiskTier = Field(description="Overall risk tier")
    scope_findings: list[ScopeFinding] = Field(default_factory=list)
    pii_findings: list[PIIFinding] = Field(default_factory=list)
    groundedness_findings: list[GroundednessFinding] = Field(default_factory=list)
    counts: CountsSummary
    summary: str
    raw_trace_storage_pointer: RawTracePointer
    risk_result: RiskResult | None = None
    engine_info: EngineInfo | None = None
    is_degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    status: str | None = "COMPLETED"
