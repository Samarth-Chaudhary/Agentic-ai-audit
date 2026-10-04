"""Unit tests for the Enterprise Regulatory Compliance Attestation Module."""

import json
from pathlib import Path

import jsonschema
import pytest

from agent.trace_builder import TraceBuilder
from auditor.compliance import (
    export_certificate_json,
    export_certificate_markdown,
    generate_compliance_certificate,
    verify_certificate_integrity,
)
from auditor.models import AuditResult, CountsSummary, RawTracePointer, RiskTier


@pytest.fixture
def sample_trace():
    builder = TraceBuilder(task_type="customer_refund")
    builder.add_assistant_message("Checking order details for refund request.")
    builder.add_tool_call("order_lookup", {"order_id": "ORD-12345"})
    builder.add_tool_result("order_lookup", {"found": True, "order_total": 45.0, "refundable_amount": 45.0, "refund_eligible": True})
    builder.add_tool_call("refund_tool", {"order_id": "ORD-12345", "amount": 45.0})
    builder.add_tool_result("refund_tool", {"refund_id": "REF-999", "status": "COMPLETED"})
    builder.set_final_answer("Refund of $45.00 has been processed successfully.")
    return builder.build()


@pytest.fixture
def sample_audit_result(sample_trace):
    return AuditResult(
        trace_id=sample_trace.trace_id,
        task_type=sample_trace.task_type,
        processed_at="2026-10-04T12:00:10Z",
        risk_score=15.0,
        risk_tier=RiskTier.LOW,
        scope_findings=[],
        pii_findings=[],
        groundedness_findings=[],
        counts=CountsSummary(
            total_steps=len(sample_trace.steps),
            tool_calls=2,
            tool_results=2,
            errors=0,
            scope_violations=0,
            pii_entities_detected=0,
            unsupported_claims=0,
        ),
        summary="Compliant execution adhering strictly to customer_refund policy.",
        raw_trace_storage_pointer=RawTracePointer(
            s3_bucket="audit-bucket",
            s3_key="traces/test.json",
            s3_uri="s3://audit-bucket/traces/test.json",
        ),
    )


def test_generate_compliance_certificate_compliant(sample_trace, sample_audit_result):
    """Ensure compliant trace generates a valid PASS certificate with cryptographic seal."""
    cert = generate_compliance_certificate(sample_trace, sample_audit_result, pep_guardrail_active=True)

    assert cert.overall_status == "PASS"
    assert cert.risk_tier == RiskTier.LOW
    assert cert.integrity_attestation.is_valid is True
    assert cert.integrity_attestation.tampering_detected is False
    assert len(cert.integrity_attestation.merkle_root_hash) == 64
    assert cert.pep_guardrail_active is True

    # Framework statuses
    assert cert.framework_evaluations["sec_rule_17a_4"].status == "COMPLIANT"
    assert cert.framework_evaluations["soc_2_type_ii"].status == "COMPLIANT"
    assert cert.framework_evaluations["eu_ai_act_article_14"].status == "COMPLIANT"

    # Signature verification
    assert verify_certificate_integrity(cert) is True


def test_tamper_detection_in_compliance_certificate(sample_trace, sample_audit_result):
    """Ensure tampering in step payload fails cryptographic attestation and flags CRITICAL."""
    # Tamper with step 2 output
    sample_trace.steps[2].output["order_total"] = 99999.0

    cert = generate_compliance_certificate(sample_trace, sample_audit_result)

    assert cert.overall_status == "CRITICAL_VIOLATION"
    assert cert.integrity_attestation.is_valid is False
    assert cert.integrity_attestation.tampering_detected is True
    assert len(cert.integrity_attestation.tamper_details) >= 1
    assert cert.framework_evaluations["sec_rule_17a_4"].status == "NON_COMPLIANT"


def test_certificate_signature_modification_detection(sample_trace, sample_audit_result):
    """Ensure modifying certificate content invalidates digital signature."""
    cert = generate_compliance_certificate(sample_trace, sample_audit_result)
    assert verify_certificate_integrity(cert) is True

    # Modify certificate score
    tampered_data = cert.model_dump()
    tampered_data["risk_score"] = 99.9

    assert verify_certificate_integrity(tampered_data) is False


def test_certificate_exports_and_schema_validation(sample_trace, sample_audit_result):
    """Ensure Markdown and JSON exports render correctly and conform to JSON Schema."""
    cert = generate_compliance_certificate(sample_trace, sample_audit_result)

    # Markdown export check
    md = export_certificate_markdown(cert)
    assert "# Regulatory Compliance & Governance Attestation Certificate" in md
    assert cert.certificate_id in md
    assert "SEC Rule 17a-4" in md
    assert cert.digital_signature in md

    # JSON export check
    cert_json_str = export_certificate_json(cert)
    cert_dict = json.loads(cert_json_str)

    schema_path = Path("schemas/compliance_certificate.schema.json")
    if not schema_path.exists():
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "compliance_certificate.schema.json"

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    # Schema validation must pass cleanly without raising ValidationError
    jsonschema.validate(instance=cert_dict, schema=schema)
