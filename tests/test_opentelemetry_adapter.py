"""Tests for OpenTelemetry GenAI external trace format adapter."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from auditor.adapters.opentelemetry_adapter import OpenTelemetryGenAIAdapter
from auditor.groundedness_detector import GroundednessDetector
from auditor.models import RiskTier, StepType, Trace
from auditor.nli_classifier import TransformerNLIClassifier
from auditor.pii_detector import PIIDetector
from auditor.policy_loader import PolicyLoader
from auditor.risk_engine import RiskEngine
from auditor.scope_detector import ScopeDetector

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "fixtures" / "external_traces" / "opentelemetry_genai_trace.json"
TRACE_SCHEMA_PATH = REPO_ROOT / "schemas" / "trace.schema.json"


class TestOpenTelemetryGenAIAdapter:
    """Verifies end-to-end ingestion and auditing of non-native OpenTelemetry traces."""

    def test_ingest_real_opentelemetry_fixture(self) -> None:
        """Verify parsing of official OpenTelemetry GenAI semantic conventions fixture."""
        assert FIXTURE_PATH.exists(), f"External fixture missing: {FIXTURE_PATH}"

        trace = OpenTelemetryGenAIAdapter.from_file(FIXTURE_PATH)

        # Core contract assertions
        assert isinstance(trace, Trace)
        assert trace.trace_id.startswith("tr-otel-4bf92f3577b34da6")
        assert trace.task_type == "customer_refund"
        assert trace.schema_version == "1.0.0"
        assert "Your refund of $20.00" in trace.final_answer

        # Steps validation
        assert len(trace.steps) == 4
        # Step 0: order_lookup call
        assert trace.steps[0].type == StepType.TOOL_CALL
        assert trace.steps[0].tool_name == "order_lookup"
        assert trace.steps[0].input == {"order_id": "ORD-1001"}
        assert trace.steps[0].call_id == "call_otel_lookup_001"

        # Step 1: order_lookup result
        assert trace.steps[1].type == StepType.TOOL_RESULT
        assert trace.steps[1].tool_name == "order_lookup"
        assert trace.steps[1].output["order_id"] == "ORD-1001"
        assert trace.steps[1].output["status"] == "DELIVERED"

        # Step 2: refund_tool call
        assert trace.steps[2].type == StepType.TOOL_CALL
        assert trace.steps[2].tool_name == "refund_tool"
        assert trace.steps[2].input["amount"] == 20.00

        # Step 3: refund_tool result
        assert trace.steps[3].type == StepType.TOOL_RESULT
        assert trace.steps[3].tool_name == "refund_tool"
        assert trace.steps[3].output["success"] is True

        # Metadata validation
        assert trace.metadata is not None
        assert trace.metadata["source_telemetry"] == "opentelemetry_genai"
        assert trace.metadata["semconv_version"] == "1.28.0"
        assert trace.metadata["model"] == "gpt-4o"

    def test_converted_trace_conforms_to_json_schema(self) -> None:
        """Ensure converted Trace validates against Draft 2020-12 trace schema."""
        trace = OpenTelemetryGenAIAdapter.from_file(FIXTURE_PATH)
        trace_dict = trace.model_dump(mode="json")

        with open(TRACE_SCHEMA_PATH, encoding="utf-8") as sf:
            schema = json.load(sf)

        jsonschema.Draft202012Validator.check_schema(schema)
        # Raises jsonschema.ValidationError if invalid
        jsonschema.validate(trace_dict, schema)

    def test_audit_pipeline_end_to_end_on_opentelemetry_trace(self) -> None:
        """Audit the converted OpenTelemetry trace through all governance detectors."""
        trace = OpenTelemetryGenAIAdapter.from_file(FIXTURE_PATH)

        # 1. Scope Evaluation
        policy_loader = PolicyLoader()
        task_policy = policy_loader.get_policy(trace.task_type)
        scope_detector = ScopeDetector()
        scope_res = scope_detector.evaluate(trace, task_policy)

        # Execution followed proper order (order_lookup -> refund_tool on DELIVERED order)
        assert scope_res.passed is True
        assert len(scope_res.findings) == 0

        # 2. PII Evaluation
        pii_detector = PIIDetector()
        pii_res = pii_detector.evaluate(trace)
        assert pii_res.passed is True
        assert len(pii_res.findings) == 0

        # 3. Groundedness Evaluation
        groundedness_detector = GroundednessDetector(
            nli_classifier=TransformerNLIClassifier(model_name="cross-encoder/nli-deberta-v3-small")
        )
        grd_res = groundedness_detector.evaluate(trace)
        assert grd_res.passed is True

        # 4. Composite Risk Scoring
        risk_engine = RiskEngine()
        breakdown = risk_engine.evaluate(
            scope_findings=scope_res.findings,
            pii_findings=pii_res.findings,
            groundedness_findings=grd_res.findings,
            total_claims=len(grd_res.findings) or 1,
        )

        assert breakdown.overall_score < 25.0
        assert breakdown.risk_tier == RiskTier.LOW
        assert "zero scope violations" in breakdown.summary.lower()

    def test_malformed_opentelemetry_payload_raises_error(self) -> None:
        """Ensure empty or invalid OpenTelemetry payloads fail fast with clear ValueError."""
        with pytest.raises(ValueError, match="No spans found"):
            OpenTelemetryGenAIAdapter.from_otlp_dict({"resourceSpans": []})
