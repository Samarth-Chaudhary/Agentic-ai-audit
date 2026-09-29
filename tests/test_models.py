"""Foundation tests for data models, serialization/deserialization, and schema conformance."""

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from auditor.models import (
    AuditResult,
    GroundednessFinding,
    PIIFinding,
    RiskTier,
    ScopeFinding,
    StepType,
    Trace,
    TraceStep,
)


def test_trace_model_serialization_and_schema_conformance(valid_trace_dict: dict, schemas_dir: Path):
    """Ensure Trace deserializes from dict and serializes back to JSON conforming to trace.schema.json."""
    # 1. Parse into Pydantic model
    trace_obj = Trace.model_validate(valid_trace_dict)
    assert trace_obj.trace_id == valid_trace_dict["trace_id"]
    assert len(trace_obj.steps) == len(valid_trace_dict["steps"])

    # 2. Serialize to dict
    serialized_dict = trace_obj.model_dump(mode="json")

    # 3. Validate against primary JSON Schema
    with open(schemas_dir / "trace.schema.json", encoding="utf-8") as f:
        schema = json.load(f)

    # Should not raise
    jsonschema.validate(instance=serialized_dict, schema=schema)

    # 4. Serialize to JSON string and parse back
    json_str = trace_obj.model_dump_json()
    reloaded = Trace.model_validate_json(json_str)
    assert reloaded.trace_id == trace_obj.trace_id
    assert reloaded.final_answer == trace_obj.final_answer


def test_step_contract_validation():
    """Ensure TraceStep validates requirements for each step type."""
    # Tool call missing tool_name
    with pytest.raises(ValidationError) as exc:
        TraceStep(index=0, type=StepType.TOOL_CALL, input={"q": "test"})
    assert "tool_name" in str(exc.value)

    # Tool call missing input
    with pytest.raises(ValidationError) as exc:
        TraceStep(index=0, type=StepType.TOOL_CALL, tool_name="search")
    assert "input" in str(exc.value)

    # Tool result missing output
    with pytest.raises(ValidationError) as exc:
        TraceStep(index=0, type=StepType.TOOL_RESULT, tool_name="search")
    assert "output" in str(exc.value)

    # Assistant message missing content
    with pytest.raises(ValidationError) as exc:
        TraceStep(index=0, type=StepType.ASSISTANT_MESSAGE)
    assert "content" in str(exc.value)

    # Error step missing message
    with pytest.raises(ValidationError) as exc:
        TraceStep(index=0, type=StepType.ERROR)
    assert "message" in str(exc.value)


def test_audit_result_serialization_and_schema_conformance(valid_audit_result_dict: dict, schemas_dir: Path):
    """Ensure AuditResult model deserializes and serializes cleanly, matching audit_result.schema.json."""
    # 1. Deserialize
    audit_obj = AuditResult.model_validate(valid_audit_result_dict)
    assert audit_obj.trace_id == valid_audit_result_dict["trace_id"]
    assert audit_obj.risk_tier == RiskTier.LOW
    assert audit_obj.counts.total_steps == 4

    # 2. Serialize to JSON dict
    serialized_dict = audit_obj.model_dump(mode="json")

    # 3. Validate against audit_result.schema.json
    with open(schemas_dir / "audit_result.schema.json", encoding="utf-8") as f:
        schema = json.load(f)

    # Must pass schema validation
    jsonschema.validate(instance=serialized_dict, schema=schema)

    # 4. Round-trip through JSON string
    json_str = audit_obj.model_dump_json()
    reloaded = AuditResult.model_validate_json(json_str)
    assert reloaded.trace_id == audit_obj.trace_id
    assert reloaded.risk_score == audit_obj.risk_score


def test_findings_models_serialization():
    """Ensure individual findings instantiate, serialize, and validate."""
    scope = ScopeFinding(
        finding_id="sc-01",
        tool_name="unauthorized_bash",
        rule_violated="unauthorized_tool",
        violation_type="unauthorized_tool",
        severity=RiskTier.HIGH,
        detail="Attempted to call disallowed tool.",
        details="Attempted to call disallowed tool.",
        step_index=2,
    )
    assert scope.severity == RiskTier.HIGH
    dumped_scope = scope.model_dump()
    assert dumped_scope["tool_name"] == "unauthorized_bash"

    pii = PIIFinding(
        finding_id="pii-01",
        entity_type="EMAIL_ADDRESS",
        pii_type="EMAIL_ADDRESS",
        confidence_score=0.95,
        step_index=1,
        field_path="input",
        field_name="input",
        redacted_snippet="customer email: [REDACTED]",
        snippet_redacted="customer email: [REDACTED]",
        severity=RiskTier.MEDIUM,
    )
    assert pii.confidence_score == 0.95

    ground = GroundednessFinding(
        finding_id="gnd-01",
        claim="Order has arrived.",
        statement="Order has arrived.",
        is_grounded=False,
        similarity=0.25,
        similarity_score=0.25,
        evidence_snippet="Tool output stated order is still pending.",
        evidence_context="Tool output stated order is still pending.",
        severity=RiskTier.HIGH,
    )
    assert ground.is_grounded is False
