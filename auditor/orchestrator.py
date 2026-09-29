"""Audit Orchestrator for AI Agent Governance.

Coordinates the complete local audit evaluation pipeline across independent
controls:
1. Trace Ingestion & Validation
2. Task Policy Resolution
3. Scope & Permission Control Evaluation
4. Sensitive Data / PII / Credential Inspection
5. Groundedness, Retrieval, & NLI Verification
6. Composite Risk Scoring & Categorical Tier Assignment
7. AuditResult Construction & JSON Schema Validation
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel

from agent.validation import TraceValidator
from auditor.groundedness_detector import GroundednessDetector
from auditor.models import (
    AuditResult,
    CountsSummary,
    EngineInfo,
    RawTracePointer,
    RiskTier,
    StepType,
    Trace,
)
from auditor.pii_detector import PIIDetector
from auditor.policy_loader import PolicyLoader
from auditor.risk_engine import RiskBreakdown, RiskEngine
from auditor.scope_detector import ScopeDetector
from project.logging import get_logger

logger = get_logger(__name__, component="audit_orchestrator")


class AuditOrchestrationError(Exception):
    """Base exception for audit orchestration failures."""


class DegradedEngineError(AuditOrchestrationError):
    """Raised when an audit operates in degraded heuristic mode with fail_on_degraded=True."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        msg = (
            f"Audit execution refused because required ML engine(s) are degraded ({len(reasons)} reason(s)):\n"
            + "\n".join(f"- {r}" for r in reasons)
        )
        super().__init__(msg)


class TraceValidationError(AuditOrchestrationError):
    """Raised when an incoming trace violates the primary trace data contract."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        msg = f"Trace contract validation failed with {len(errors)} error(s):\n" + "\n".join(f"- {e}" for e in errors)
        super().__init__(msg)


class AuditResultValidationError(AuditOrchestrationError):
    """Raised when generated AuditResult fails schema conformance."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        msg = f"AuditResult schema validation failed with {len(errors)} error(s):\n" + "\n".join(f"- {e}" for e in errors)
        super().__init__(msg)


def _find_audit_result_schema_path() -> Path:
    """Locate schemas/audit_result.schema.json relative to repository root."""
    candidates = [
        Path.cwd() / "schemas" / "audit_result.schema.json",
        Path(__file__).resolve().parent.parent / "schemas" / "audit_result.schema.json",
        Path("schemas") / "audit_result.schema.json",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p.resolve()
    return candidates[0]


class AuditOrchestrator:
    """Coordinates independent audit controls into one deterministic local audit pipeline.

    TARGET FLOW:
    TRACE -> VALIDATE -> LOAD POLICY -> SCOPE -> PII -> GROUNDEDNESS -> RISK -> AUDIT RESULT -> VALIDATE SCHEMA
    """

    def __init__(
        self,
        policy_loader: PolicyLoader | None = None,
        scope_detector: ScopeDetector | None = None,
        pii_detector: PIIDetector | None = None,
        groundedness_detector: GroundednessDetector | None = None,
        risk_engine: RiskEngine | None = None,
        trace_validator: TraceValidator | None = None,
        audit_schema_path: Path | str | None = None,
        fail_on_degraded: bool = False,
    ) -> None:
        self.policy_loader = policy_loader or PolicyLoader()
        self.risk_config = self.policy_loader.load_risk_config()

        self.scope_detector = scope_detector or ScopeDetector(risk_config=self.risk_config)
        self.pii_detector = pii_detector or PIIDetector(risk_config=self.risk_config)
        self.groundedness_detector = groundedness_detector or GroundednessDetector(risk_config=self.risk_config)
        self.risk_engine = risk_engine or RiskEngine(risk_config=self.risk_config)
        self.trace_validator = trace_validator or TraceValidator()
        self.fail_on_degraded = fail_on_degraded or (os.environ.get("AUDIT_FAIL_ON_DEGRADED", "0") == "1")

        self.audit_schema_path = Path(audit_schema_path) if audit_schema_path else _find_audit_result_schema_path()
        self._audit_schema: dict[str, Any] | None = None
        self._audit_validator: jsonschema.Draft7Validator | None = None

    def _get_audit_validator(self) -> jsonschema.Draft7Validator:
        """Load and cache the jsonschema validator for audit_result.schema.json."""
        if self._audit_validator is None:
            if not self.audit_schema_path.exists():
                raise FileNotFoundError(f"Audit result schema not found at: {self.audit_schema_path}")
            with open(self.audit_schema_path, encoding="utf-8") as f:
                self._audit_schema = json.load(f)
            self._audit_validator = jsonschema.Draft7Validator(self._audit_schema)
        return self._audit_validator

    def validate_audit_result(self, audit_result: AuditResult | dict[str, Any]) -> None:
        """Validate an AuditResult instance or dict against schemas/audit_result.schema.json."""
        validator = self._get_audit_validator()
        data = audit_result.model_dump(mode="json") if isinstance(audit_result, BaseModel) else audit_result

        schema_errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        if schema_errors:
            error_msgs = []
            for err in schema_errors:
                path_str = " -> ".join(str(p) for p in err.path) if err.path else "root"
                error_msgs.append(f"[{path_str}] {err.message}")
            raise AuditResultValidationError(error_msgs)

    def audit(
        self,
        trace_input: Trace | dict[str, Any] | str | Path,
        raw_trace_uri: str | None = None,
        s3_bucket: str | None = None,
        s3_key: str | None = None,
        fail_on_degraded: bool | None = None,
    ) -> AuditResult:
        """Execute the end-to-end local audit pipeline on an agent execution trace.

        1. Accept a trace (Trace model, dict, or file path)
        2. Validate it against schemas/trace.schema.json
        3. Load the task policy
        4. Run scope detector
        5. Run PII detector
        6. Run groundedness detector
        7. Run risk engine
        8. Assemble AuditResult
        9. Validate AuditResult against schemas/audit_result.schema.json
        10. Return the result
        """
        # Step 1: Ingestion
        if isinstance(trace_input, (str, Path)):
            trace_path = Path(trace_input)
            if not trace_path.exists():
                raise FileNotFoundError(f"Trace file not found: {trace_path}")
            with open(trace_path, encoding="utf-8") as f:
                raw_dict = json.load(f)
        elif isinstance(trace_input, dict):
            raw_dict = trace_input
        elif isinstance(trace_input, Trace):
            raw_dict = trace_input.model_dump(mode="json")
        else:
            raise TypeError(f"Unsupported trace input type: {type(trace_input).__name__}")

        # Step 2: Validate trace
        val_result = self.trace_validator.validate_dict(raw_dict)
        if not val_result.is_valid:
            logger.error(f"Trace validation failed with {len(val_result.errors)} error(s)")
            raise TraceValidationError(val_result.errors)

        trace: Trace = val_result.trace or Trace.model_validate(raw_dict)
        logger.info_event(
            "audit_pipeline_start",
            trace_id=trace.trace_id,
            task_type=trace.task_type,
            status="running",
            message=f"Beginning audit pipeline for trace '{trace.trace_id}' ({trace.task_type})",
        )

        # Step 3: Load the task policy
        task_policy = self.policy_loader.load_policy_for_task(trace.task_type)

        # Step 4: Run Scope Detector
        scope_result = self.scope_detector.evaluate(trace, task_policy)

        # Step 5: Run PII Detector
        pii_result = self.pii_detector.evaluate(trace, task_policy)

        # Step 6: Run Groundedness Detector
        groundedness_result = self.groundedness_detector.evaluate(trace)

        # Step 7: Run Risk Engine
        risk_breakdown: RiskBreakdown = self.risk_engine.evaluate(
            scope_findings=scope_result.findings,
            pii_findings=pii_result.findings,
            groundedness_findings=groundedness_result.findings,
            total_claims=groundedness_result.total_claims,
        )

        # Step 8: Assemble AuditResult
        total_steps = len(trace.steps)
        tool_calls = sum(1 for s in trace.steps if (getattr(s, "type", "") == "tool_call" or getattr(s, "type", None) == StepType.TOOL_CALL))
        tool_results = sum(1 for s in trace.steps if (getattr(s, "type", "") == "tool_result" or getattr(s, "type", None) == StepType.TOOL_RESULT))
        errors = sum(
            1 for s in trace.steps
            if (
                getattr(s, "type", "") == "error"
                or getattr(s, "type", None) == StepType.ERROR
                or getattr(s, "error", None) is not None
            )
        )

        unsupported_claims_count = sum(
            1 for f in groundedness_result.findings
            if f.audit_verdict in ("UNSUPPORTED", "CONTRADICTED")
        )

        counts = CountsSummary(
            total_steps=total_steps,
            tool_calls=tool_calls,
            tool_results=tool_results,
            errors=errors,
            scope_violations=len(scope_result.findings),
            pii_entities_detected=len(pii_result.findings),
            unsupported_claims=unsupported_claims_count,
        )

        # S3 storage locator placeholder
        bucket = s3_bucket or os.environ.get("TRACES_S3_BUCKET", "ai-agent-audit-traces-local")
        key = s3_key or f"traces/{trace.trace_id}.json"
        uri = raw_trace_uri or f"s3://{bucket}/{key}"
        storage_pointer = RawTracePointer(s3_bucket=bucket, s3_key=key, s3_uri=uri)

        risk_res = self.risk_engine.to_risk_result(risk_breakdown)
        processed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Step 8: Assemble concrete engine identity and inspect degradation status
        is_degraded = (
            bool(groundedness_result.is_degraded)
            or bool(pii_result.is_degraded)
        )
        degraded_reasons = (
            list(groundedness_result.degraded_reasons)
            + list(pii_result.degraded_reasons)
        )
        engine_info = EngineInfo(
            nli_engine=groundedness_result.nli_engine or self.groundedness_detector.nli_engine_name,
            embedding_engine=groundedness_result.embedding_engine or self.groundedness_detector.embedding_engine_name,
            pii_engine=pii_result.pii_engine or self.pii_detector.engine_name,
            is_degraded=is_degraded,
            degraded_reasons=degraded_reasons,
        )

        should_fail_on_degraded = (
            self.fail_on_degraded
            if fail_on_degraded is None
            else fail_on_degraded
        ) or (os.environ.get("AUDIT_FAIL_ON_DEGRADED", "0") == "1")

        if should_fail_on_degraded and is_degraded:
            logger.error_event(
                event="audit_refused_degraded",
                status="refused",
                message="Audit execution refused because required ML engine(s) are degraded",
                trace_id=trace.trace_id,
                task_type=trace.task_type,
                extra_data={"reasons": degraded_reasons},
            )
            raise DegradedEngineError(degraded_reasons)

        if risk_breakdown.risk_tier in (RiskTier.HIGH, RiskTier.CRITICAL):
            status = "FLAGGED"
        elif is_degraded:
            status = "DEGRADED"
        else:
            status = "COMPLETED"

        audit_result = AuditResult(
            trace_id=trace.trace_id,
            task_type=trace.task_type,
            processed_at=processed_at,
            risk_score=risk_breakdown.overall_score,
            risk_tier=risk_breakdown.risk_tier,
            scope_findings=scope_result.findings,
            pii_findings=pii_result.findings,
            groundedness_findings=groundedness_result.findings,
            counts=counts,
            summary=risk_breakdown.summary,
            raw_trace_storage_pointer=storage_pointer,
            risk_result=risk_res,
            engine_info=engine_info,
            is_degraded=is_degraded,
            degraded_reasons=degraded_reasons,
            status=status,
        )

        # Step 9: Validate AuditResult against JSON schema
        self.validate_audit_result(audit_result)

        logger.info_event(
            "audit_pipeline_complete",
            trace_id=trace.trace_id,
            task_type=trace.task_type,
            status="completed",
            message=(
                f"Audit pipeline finished for trace '{trace.trace_id}': "
                f"risk_score={audit_result.risk_score} ({audit_result.risk_tier.value})"
            ),
            extra_data={
                "risk_score": audit_result.risk_score,
                "risk_tier": audit_result.risk_tier.value,
                "scope_violations": counts.scope_violations,
                "pii_entities_detected": counts.pii_entities_detected,
                "unsupported_claims": counts.unsupported_claims,
                "is_degraded": is_degraded,
                "engine_info": engine_info.model_dump(),
            },
        )

        # Step 10: Return the result
        return audit_result

    def run(
        self,
        trace_input: Trace | dict[str, Any] | str | Path,
        raw_trace_uri: str | None = None,
        s3_bucket: str | None = None,
        s3_key: str | None = None,
        fail_on_degraded: bool | None = None,
    ) -> dict[str, Any]:
        """Execute audit pipeline and return result as a dictionary."""
        result = self.audit(
            trace_input=trace_input,
            raw_trace_uri=raw_trace_uri,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            fail_on_degraded=fail_on_degraded,
        )
        return result.model_dump(mode="json")
