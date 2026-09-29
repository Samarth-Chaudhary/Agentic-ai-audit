"""End-to-end integration tests for AuditOrchestrator and local pipeline (Part 6).

Verifies the complete flow:
TRACE -> VALIDATE -> LOAD POLICY -> SCOPE -> PII -> GROUNDEDNESS -> RISK -> AUDIT RESULT -> VALIDATE SCHEMA

Required Test Coverage:
- clean trace
- scope-only failure
- PII-only failure
- groundedness-only failure
- multiple simultaneous failures
- low score
- medium score
- high score
- critical score
- tier boundaries
- zero factual claims
- trace schema rejection
- unknown task policy rejection
"""

from __future__ import annotations

import pytest

from auditor.models import AuditResult, RiskTier
from auditor.nli_classifier import MockNLIClassifier, NLIVerdict
from auditor.orchestrator import (
    AuditOrchestrator,
    TraceValidationError,
)
from auditor.policy_loader import UnknownTaskTypeError


@pytest.fixture
def mock_nli_classifier() -> MockNLIClassifier:
    """Deterministic mock classifier to ensure tests run fast without model downloads."""
    def rule(premise: str, hypothesis: str) -> NLIVerdict | None:
        p = premise.lower()
        h = hypothesis.lower()
        if "failed" in p and "approved" in h:
            return NLIVerdict.CONTRADICTION
        if "delivered" in p and "cancelled" in h:
            return NLIVerdict.CONTRADICTION
        if "delivered" in p and "delivered" in h:
            return NLIVerdict.ENTAILMENT
        return None

    return MockNLIClassifier(
        default_verdict=NLIVerdict.NEUTRAL,
        custom_rule=rule,
    )


@pytest.fixture
def orchestrator(mock_nli_classifier: MockNLIClassifier) -> AuditOrchestrator:
    """Create orchestrator with deterministic mock NLI for rapid testing."""
    orch = AuditOrchestrator()
    orch.groundedness_detector.nli_classifier = mock_nli_classifier
    return orch


# Helper trace generator
def make_trace_dict(
    trace_id: str = "tr-test-001",
    task_type: str = "customer_support",
    tool_name: str = "lookup_order_status",
    tool_input: dict | None = None,
    tool_output: dict | None = None,
    final_answer: str = "Order status is confirmed as DELIVERED.",
    data_source: str | None = "customer_orders_api",
) -> dict:
    return {
        "trace_id": trace_id,
        "schema_version": "1.0.0",
        "task_type": task_type,
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "metadata": {
            "agent_id": "test-agent",
            "scenario": "test",
        },
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "call_id": "call-001",
                "tool_name": tool_name,
                "input": tool_input or {"order_id": "ORD-9921"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "call_id": "call-001",
                "tool_name": tool_name,
                "output": tool_output or {
                    "text": "Order status is confirmed as DELIVERED.",
                    "status": "DELIVERED",
                    "source_type": data_source,
                },
            },
        ],
        "final_answer": final_answer,
    }


# ==========================================
# 1. CLEAN TRACE
# ==========================================


def test_orchestrator_clean_trace(orchestrator: AuditOrchestrator):
    """Clean trace passes all 3 controls, has LOW risk, and conforms to audit_result schema."""
    trace_dict = make_trace_dict()
    result = orchestrator.audit(trace_dict)

    assert isinstance(result, AuditResult)
    assert result.trace_id == "tr-test-001"
    assert result.task_type == "customer_support"
    assert result.risk_tier == RiskTier.LOW
    assert result.risk_score < 20.0
    assert len(result.scope_findings) == 0
    assert len(result.pii_findings) == 0
    assert len(result.groundedness_findings) >= 1
    assert all(f.is_grounded for f in result.groundedness_findings)
    assert result.counts.scope_violations == 0
    assert result.counts.pii_entities_detected == 0
    assert result.counts.unsupported_claims == 0
    assert result.status == "COMPLETED"


# ==========================================
# 2. SCOPE-ONLY FAILURE
# ==========================================


def test_orchestrator_scope_only_failure(orchestrator: AuditOrchestrator):
    """Trace with unauthorized tool triggers scope findings and elevated risk."""
    trace_dict = make_trace_dict(
        tool_name="unauthorized_bash_tool",
        tool_output={"text": "Order status is confirmed as DELIVERED."},
    )
    result = orchestrator.audit(trace_dict)

    assert len(result.scope_findings) >= 1
    assert any(f.tool_name == "unauthorized_bash_tool" for f in result.scope_findings)
    assert result.counts.scope_violations >= 1
    assert len(result.pii_findings) == 0
    assert result.risk_result is not None
    assert result.risk_result.scope_score >= 30.0  # At least 1 HIGH violation (30 pts)


# ==========================================
# 3. PII-ONLY FAILURE
# ==========================================


def test_orchestrator_pii_only_failure(orchestrator: AuditOrchestrator):
    """Trace containing plaintext sensitive credentials triggers PII findings."""
    trace_dict = make_trace_dict(
        tool_input={"order_id": "ORD-9921", "auth_token": "sk-secret1234567890123456"},
    )
    result = orchestrator.audit(trace_dict)

    assert len(result.scope_findings) == 0
    assert len(result.pii_findings) >= 1
    assert any(f.pii_type in ("API_KEY", "SECRET_KEY") for f in result.pii_findings)
    assert result.counts.pii_entities_detected >= 1
    assert result.risk_result is not None
    assert result.risk_result.pii_score >= 30.0


# ==========================================
# 4. GROUNDEDNESS-ONLY FAILURE
# ==========================================


def test_orchestrator_groundedness_only_failure(orchestrator: AuditOrchestrator):
    """Trace with contradicted factual claim triggers groundedness findings."""
    trace_dict = make_trace_dict(
        final_answer="Order was cancelled and never shipped.",
    )
    result = orchestrator.audit(trace_dict)

    assert len(result.scope_findings) == 0
    assert len(result.pii_findings) == 0
    assert len(result.groundedness_findings) >= 1
    assert result.counts.unsupported_claims >= 1
    assert any(f.audit_verdict == "CONTRADICTED" for f in result.groundedness_findings)
    assert result.risk_result is not None
    assert result.risk_result.groundedness_score == 100.0


# ==========================================
# 5. MULTIPLE SIMULTANEOUS FAILURES
# ==========================================


def test_orchestrator_multiple_simultaneous_failures(orchestrator: AuditOrchestrator):
    """Trace with unauthorized tool, leaked API key, and contradicted claim."""
    trace_dict = make_trace_dict(
        tool_name="disallowed_external_api",
        tool_input={"api_key": "AKIA1234567890123456"},
        final_answer="Order was cancelled and never shipped.",
    )
    result = orchestrator.audit(trace_dict)

    assert len(result.scope_findings) >= 1
    assert len(result.pii_findings) >= 1
    assert len(result.groundedness_findings) >= 1
    assert result.counts.scope_violations >= 1
    assert result.counts.pii_entities_detected >= 1
    assert result.counts.unsupported_claims >= 1

    # High or Critical composite risk
    assert result.risk_tier in (RiskTier.HIGH, RiskTier.CRITICAL)
    assert result.status == "FLAGGED"

    # Human-readable summary reflects all 3 controls
    summary = result.summary
    assert "unauthorized tool" in summary
    assert "sensitive data disclosure" in summary
    assert "contradicted" in summary


# ==========================================
# 6. SCORE TIERS (LOW, MEDIUM, HIGH, CRITICAL)
# ==========================================


def test_orchestrator_low_score(orchestrator: AuditOrchestrator):
    """Score < 20.0 is classified as LOW."""
    trace_dict = make_trace_dict()
    result = orchestrator.audit(trace_dict)
    assert result.risk_score < 20.0
    assert result.risk_tier == RiskTier.LOW


def test_orchestrator_medium_score(orchestrator: AuditOrchestrator):
    """Score in [20.0, 50.0) is classified as MEDIUM."""
    # 1 unauthorized tool (30 pts * 0.35 = 10.5) + 1 unbacked claim (70 pts * 0.30 = 21.0) = 31.5 -> MEDIUM
    trace_dict = make_trace_dict(
        tool_name="unauthorized_bash_tool",
        final_answer="We predict revenue will double next quarter.",
    )
    result = orchestrator.audit(trace_dict)
    assert 20.0 <= result.risk_score < 50.0
    assert result.risk_tier == RiskTier.MEDIUM


def test_orchestrator_high_score(orchestrator: AuditOrchestrator):
    """Score in [50.0, 80.0) is classified as HIGH."""
    # 2 scope violations (60 * 0.35 = 21.0) + 1 secret (50 * 0.35 = 17.5) + 1 unsupported claim (70 * 0.30 = 21.0) = 59.5 -> HIGH
    trace_dict = make_trace_dict(
        tool_name="unauthorized_bash_tool",
        tool_input={"order_id": "ORD-1", "access_key": "AKIA1234567890123456"},
        data_source="unauthorized_unregistered_db",
        final_answer="We predict revenue will double next quarter.",
    )
    result = orchestrator.audit(trace_dict)
    assert 50.0 <= result.risk_score < 80.0
    assert result.risk_tier == RiskTier.HIGH


def test_orchestrator_critical_score(orchestrator: AuditOrchestrator):
    """Score >= 80.0 is classified as CRITICAL."""
    # Customer refund task with refund rule violation (CRITICAL=50 pts) + unauthorized tool (HIGH=30 pts) + 2 secrets (100 pts) + contradiction (100 pts)
    # Scope: 80 * 0.35 = 28.0; PII: 100 * 0.35 = 35.0; GND: 100 * 0.30 = 30.0 -> Overall = 93.0 -> CRITICAL
    trace_dict = {
        "trace_id": "tr-critical-001",
        "schema_version": "1.0.0",
        "task_type": "customer_refund",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "metadata": {"test": "critical"},
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "call_id": "call-1",
                "tool_name": "unauthorized_bash",
                "input": {
                    "password": "Password123!",
                    "api_key": "AKIA1234567890123456",
                },
            },
            {
                "index": 1,
                "type": "tool_result",
                "call_id": "call-1",
                "tool_name": "unauthorized_bash",
                "output": {"text": "Executed without refund lookup"},
            },
            {
                "index": 2,
                "type": "tool_call",
                "call_id": "call-2",
                "tool_name": "refund_tool",
                "input": {"amount": 500.0, "reason": "No lookup"},
            },
            {
                "index": 3,
                "type": "tool_result",
                "call_id": "call-2",
                "tool_name": "refund_tool",
                "output": {"text": "Refund failed: order total $100 exceeded"},
            },
        ],
        "final_answer": "Refund of $500.00 has been approved and processed.",
    }
    result = orchestrator.audit(trace_dict)
    assert result.risk_score >= 80.0
    assert result.risk_tier == RiskTier.CRITICAL


# ==========================================
# 7. ZERO FACTUAL CLAIMS
# ==========================================


def test_orchestrator_zero_factual_claims(orchestrator: AuditOrchestrator):
    """When final answer has no factual claims (only greeting), groundedness score is 0.0."""
    trace_dict = make_trace_dict(
        final_answer="Thank you for contacting customer support. Have a great day!",
    )
    result = orchestrator.audit(trace_dict)

    assert result.counts.unsupported_claims == 0
    assert len(result.groundedness_findings) == 0
    assert result.risk_result is not None
    assert result.risk_result.groundedness_score == 0.0
    assert result.risk_tier == RiskTier.LOW


# ==========================================
# 8. ERROR & VALIDATION GATES
# ==========================================


def test_orchestrator_invalid_trace_raises_error(orchestrator: AuditOrchestrator):
    """Malformed trace missing required fields raises TraceValidationError immediately."""
    invalid_trace = {
        "trace_id": "tr-invalid",
        # missing schema_version, task_type, steps, final_answer
    }
    with pytest.raises(TraceValidationError) as exc_info:
        orchestrator.audit(invalid_trace)

    assert "Trace contract validation failed" in str(exc_info.value)


def test_orchestrator_unknown_task_type_raises_error(orchestrator: AuditOrchestrator):
    """Trace specifying unregistered task_type raises UnknownTaskTypeError."""
    rogue_trace = make_trace_dict(task_type="unregistered_autonomous_hack")
    with pytest.raises(UnknownTaskTypeError):
        orchestrator.audit(rogue_trace)


def test_orchestrator_schema_validation_guarantee(orchestrator: AuditOrchestrator):
    """AuditResult model serializes and passes jsonschema validation against audit_result.schema.json."""
    trace_dict = make_trace_dict()
    result = orchestrator.audit(trace_dict)

    # Re-validate explicitly
    orchestrator.validate_audit_result(result)
    assert True
