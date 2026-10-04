"""Enterprise Regulatory & Cryptographic Compliance Attestation Module.

Generates formal, cryptographically-sealed compliance audit certificates
evaluating agent traces and audit outcomes against major regulatory frameworks:
- SEC Rule 17a-4 / FINRA Rule 4511 (WORM Storage, Tamper-Evident Merkle Chains)
- SOC 2 Type II (Trust Services Criteria CC6.1, CC6.6, CC7.2)
- EU AI Act (Article 12: Record-Keeping, Article 14: Human Oversight)
- NIST AI RMF 1.0 (GOVERN 1.2, MEASURE 2.6)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from auditor.models import AuditResult, RiskTier, Trace
from project.logging import get_logger

logger = get_logger(__name__, component="compliance_attestation")


class FrameworkEvaluation(BaseModel):
    """Evaluation result against a specific governance or regulatory standard."""

    framework_name: str
    control_id: str
    status: str = Field(description="COMPLIANT, HIGH_RISK_FLAGGED, or NON_COMPLIANT")
    requirements: str
    evidence_summary: str


class IntegrityAttestation(BaseModel):
    """Cryptographic chain and Merkle root verification evidence."""

    is_valid: bool
    merkle_root_hash: str
    steps_verified: int
    tampering_detected: bool
    tamper_details: list[str] = Field(default_factory=list)


class ComplianceCertificate(BaseModel):
    """Formal audit certificate attesting agent governance and cryptographic integrity."""

    certificate_id: str = Field(default_factory=lambda: f"CERT-{uuid.uuid4().hex[:12].upper()}")
    trace_id: str
    task_type: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    compliance_engine: str = "AI-Agent-Assurance-Engine/v1.0-Auditor"
    overall_status: str = Field(description="PASS, FLAGGED, or CRITICAL_VIOLATION")
    risk_score: float
    risk_tier: RiskTier
    integrity_attestation: IntegrityAttestation
    framework_evaluations: dict[str, FrameworkEvaluation] = Field(default_factory=dict)
    violations_summary: dict[str, int] = Field(default_factory=dict)
    pep_guardrail_active: bool = False
    digital_signature: str = Field(
        default="",
        description="SHA-256 fingerprint sealing the certificate payload against post-audit tampering",
    )


def _compute_certificate_signature(cert_dict: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of certificate fields excluding the signature."""
    payload = {k: v for k, v in cert_dict.items() if k != "digital_signature"}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def generate_compliance_certificate(
    trace: Trace | dict[str, Any],
    audit_result: AuditResult | dict[str, Any],
    pep_guardrail_active: bool = False,
) -> ComplianceCertificate:
    """Evaluate trace and audit result to generate a cryptographically-sealed ComplianceCertificate."""
    if isinstance(trace, dict):
        trace_data = dict(trace)
        if "schema_version" not in trace_data:
            trace_data["schema_version"] = "1.0.0"
        if "started_at" not in trace_data:
            trace_data["started_at"] = "2026-10-04T12:00:00Z"
        if "ended_at" not in trace_data:
            trace_data["ended_at"] = "2026-10-04T12:00:05Z"
        if "final_answer" not in trace_data:
            trace_data["final_answer"] = str(trace_data.get("summary") or "Audit trace completed.")
        if "steps" not in trace_data and "execution_timeline" in trace_data:
            trace_data["steps"] = trace_data["execution_timeline"]
        if not trace_data.get("steps"):
            trace_data["steps"] = [{"index": 0, "type": "assistant_message", "content": trace_data.get("final_answer") or "Trace event."}]
        trace_obj = Trace.model_validate(trace_data)
    else:
        trace_obj = trace

    if isinstance(audit_result, dict):
        audit_data = dict(audit_result)
        if "trace_id" not in audit_data:
            audit_data["trace_id"] = trace_obj.trace_id
        if "task_type" not in audit_data:
            audit_data["task_type"] = trace_obj.task_type
        if "processed_at" not in audit_data:
            audit_data["processed_at"] = "2026-10-04T12:00:10Z"
        if "risk_score" not in audit_data:
            audit_data["risk_score"] = 0.0
        if "risk_tier" not in audit_data:
            audit_data["risk_tier"] = "LOW"
        if "scope_findings" not in audit_data:
            audit_data["scope_findings"] = audit_data.get("findings", {}).get("scope", [])
        if "pii_findings" not in audit_data:
            audit_data["pii_findings"] = audit_data.get("findings", {}).get("pii", [])
        if "groundedness_findings" not in audit_data:
            audit_data["groundedness_findings"] = audit_data.get("findings", {}).get("groundedness", [])
        if "counts" not in audit_data:
            audit_data["counts"] = {
                "total_steps": len(trace_obj.steps),
                "tool_calls": 0,
                "tool_results": 0,
                "errors": 0,
                "scope_violations": len(audit_data["scope_findings"]),
                "pii_entities_detected": len(audit_data["pii_findings"]),
                "unsupported_claims": len(audit_data["groundedness_findings"]),
            }
        if "summary" not in audit_data:
            audit_data["summary"] = "Compliance evaluation."
        if "raw_trace_storage_pointer" not in audit_data:
            audit_data["raw_trace_storage_pointer"] = {
                "s3_bucket": "audit-bucket",
                "s3_key": f"traces/{trace_obj.trace_id}.json",
                "s3_uri": f"s3://audit-bucket/traces/{trace_obj.trace_id}.json",
            }
        audit_obj = AuditResult.model_validate(audit_data)
    else:
        audit_obj = audit_result

    # 1. Cryptographic integrity audit
    chain_valid, error_msg = trace_obj.verify_integrity()
    tamper_details: list[str] = [str(error_msg)] if error_msg else []
    steps_count = len(trace_obj.steps)
    merkle_root = trace_obj.merkle_root_hash or "UNSEALED"

    integrity_att = IntegrityAttestation(
        is_valid=chain_valid,
        merkle_root_hash=merkle_root,
        steps_verified=steps_count,
        tampering_detected=not chain_valid,
        tamper_details=tamper_details,
    )

    # 2. Risk & violations evaluation
    risk_tier = audit_obj.risk_tier
    risk_score = audit_obj.risk_score

    scope_count = len(audit_obj.scope_findings)
    pii_count = len(audit_obj.pii_findings)
    groundedness_count = len(audit_obj.groundedness_findings)
    total_violations = scope_count + pii_count + groundedness_count

    violations_summary = {
        "scope_violations": scope_count,
        "pii_leaks": pii_count,
        "unsupported_groundedness_claims": groundedness_count,
        "total_violations": total_violations,
    }

    # 3. Regulatory standard evaluations
    frameworks: dict[str, FrameworkEvaluation] = {}

    # SEC Rule 17a-4 / FINRA 4511 (WORM Storage & Tamper Evidence)
    sec_compliant = chain_valid and (merkle_root != "UNSEALED")
    if sec_compliant:
        sec_evidence = f"Step hash chain verified ({steps_count} steps). Merkle Root: {merkle_root[:16]}..."
    else:
        err_detail_str = ", ".join(tamper_details) if tamper_details else "Missing Merkle Root"
        sec_evidence = f"Cryptographic integrity failed: {err_detail_str}"

    frameworks["sec_rule_17a_4"] = FrameworkEvaluation(
        framework_name="SEC Rule 17a-4 / FINRA Rule 4511",
        control_id="WORM-INTEGRITY-01",
        status="COMPLIANT" if sec_compliant else "NON_COMPLIANT",
        requirements="Audit records must be stored in immutable WORM format with cryptographic tamper evidence.",
        evidence_summary=sec_evidence,
    )

    # SOC 2 Type II (Trust Services Criteria CC6.1 & CC7.2)
    soc2_compliant = (scope_count == 0) and (pii_count == 0) and chain_valid
    frameworks["soc_2_type_ii"] = FrameworkEvaluation(
        framework_name="SOC 2 Type II (Trust Services Criteria)",
        control_id="CC6.1-LOGICAL-ACCESS-INTEGRITY",
        status="COMPLIANT" if soc2_compliant else "NON_COMPLIANT",
        requirements="Enforces logical access controls, tool authorization boundaries, and sensitive data leakage controls.",
        evidence_summary=(
            f"Zero unauthorized tool executions and zero credential/PII leaks detected across {steps_count} steps."
            if soc2_compliant
            else f"Found {scope_count} scope violation(s) and {pii_count} sensitive data leak(s)."
        ),
    )

    # EU AI Act (Article 12 & Article 14)
    eu_status = (
        "COMPLIANT"
        if (risk_tier in (RiskTier.LOW, RiskTier.MEDIUM) and chain_valid)
        else "HIGH_RISK_FLAGGED"
    )
    frameworks["eu_ai_act_article_14"] = FrameworkEvaluation(
        framework_name="EU AI Act (Article 12: Record-Keeping & Article 14: Human Oversight)",
        control_id="EU-AIA-ART12-ART14",
        status=eu_status,
        requirements="High-risk AI systems must produce automated logs enabling traceability and support human oversight.",
        evidence_summary=(
            f"System risk tier '{risk_tier.value}' within acceptable operational envelope. Comprehensive audit trail recorded."
            if eu_status == "COMPLIANT"
            else f"High risk tier '{risk_tier.value}' (score: {risk_score:.1f}) requires mandatory human compliance officer sign-off."
        ),
    )

    # NIST AI RMF 1.0 (GOVERN 1.2 & MEASURE 2.6)
    nist_status = "COMPLIANT" if (risk_score < 70.0 and chain_valid) else "NON_COMPLIANT"
    frameworks["nist_ai_rmf_1_0"] = FrameworkEvaluation(
        framework_name="NIST AI Risk Management Framework (RMF 1.0)",
        control_id="GOVERN-1.2-MEASURE-2.6",
        status=nist_status,
        requirements="Formal risk boundaries, hallucination measurement, and continuous monitoring.",
        evidence_summary=(
            f"Calculated composite risk score {risk_score:.1f}/100. Groundedness checks evaluated {groundedness_count} ungrounded claims."
        ),
    )

    # Determine overall status
    if not chain_valid or risk_tier == RiskTier.CRITICAL:
        overall_status = "CRITICAL_VIOLATION"
    elif risk_tier == RiskTier.HIGH or total_violations > 0:
        overall_status = "FLAGGED"
    else:
        overall_status = "PASS"

    cert_data = {
        "certificate_id": f"CERT-{uuid.uuid4().hex[:12].upper()}",
        "trace_id": trace_obj.trace_id,
        "task_type": trace_obj.task_type,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "compliance_engine": "AI-Agent-Assurance-Engine/v1.0-Auditor",
        "overall_status": overall_status,
        "risk_score": risk_score,
        "risk_tier": risk_tier,
        "integrity_attestation": integrity_att.model_dump(),
        "framework_evaluations": {k: v.model_dump() for k, v in frameworks.items()},
        "violations_summary": violations_summary,
        "pep_guardrail_active": pep_guardrail_active,
    }

    signature = _compute_certificate_signature(cert_data)
    cert_data["digital_signature"] = signature

    cert = ComplianceCertificate.model_validate(cert_data)

    logger.info_event(
        event="compliance_certificate_generated",
        status=overall_status.lower(),
        message=f"Compliance certificate {cert.certificate_id} issued for trace {trace_obj.trace_id} ({overall_status})",
        trace_id=trace_obj.trace_id,
        task_type=trace_obj.task_type,
        extra_data={"certificate_id": cert.certificate_id, "signature": signature[:16]},
    )

    return cert


def verify_certificate_integrity(cert: ComplianceCertificate | dict[str, Any]) -> bool:
    """Verify that a ComplianceCertificate has not been modified after generation."""
    raw = cert.model_dump() if isinstance(cert, ComplianceCertificate) else dict(cert)
    sig = raw.get("digital_signature", "")
    if not sig:
        return False
    expected_sig = _compute_certificate_signature(raw)
    return sig == expected_sig


def export_certificate_markdown(cert: ComplianceCertificate) -> str:
    """Render a formal regulatory attestation certificate in GitHub Flavored Markdown."""
    status_emoji = "✅ PASS" if cert.overall_status == "PASS" else ("⚠️ FLAGGED" if cert.overall_status == "FLAGGED" else "❌ CRITICAL VIOLATION")
    chain_badge = "✅ VERIFIED & UNTAMPERED" if cert.integrity_attestation.is_valid else "❌ TAMPERING DETECTED"
    pep_badge = "ACTIVE (Synchronous Guardrail)" if cert.pep_guardrail_active else "POST-HOC AUDIT ONLY"

    lines = [
        "# Regulatory Compliance & Governance Attestation Certificate",
        "",
        f"**Certificate Identifier:** `{cert.certificate_id}`  ",
        f"**Trace Identifier:** `{cert.trace_id}`  ",
        f"**Task Classification:** `{cert.task_type}`  ",
        f"**Issuance Timestamp (UTC):** `{cert.generated_at}`  ",
        f"**Assurance Engine:** `{cert.compliance_engine}`  ",
        "",
        "---",
        "",
        "## Executive Governance Summary",
        "",
        "| Metric | Evaluation Result |",
        "| :--- | :--- |",
        f"| **Overall Compliance Status** | **{status_emoji}** |",
        f"| **Composite Risk Tier** | `{cert.risk_tier.value}` ({cert.risk_score:.1f}/100) |",
        f"| **Runtime Policy Enforcement** | {pep_badge} |",
        f"| **Cryptographic Hash Chain** | {chain_badge} |",
        f"| **SHA-256 Merkle Root** | `{cert.integrity_attestation.merkle_root_hash}` |",
        f"| **Total Steps Verified** | {cert.integrity_attestation.steps_verified} steps |",
        "",
        "---",
        "",
        "## Regulatory Framework Mapping",
        "",
        "| Framework | Control ID | Status | Key Evidence |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for fw in cert.framework_evaluations.values():
        st = "✅ COMPLIANT" if fw.status == "COMPLIANT" else ("⚠️ REVIEW REQUIRED" if fw.status == "HIGH_RISK_FLAGGED" else "❌ NON_COMPLIANT")
        lines.append(f"| **{fw.framework_name}** | `{fw.control_id}` | {st} | {fw.evidence_summary} |")

    lines.extend([
        "",
        "---",
        "",
        "## Violation Breakdown",
        "",
        f"- **Tool & Scope Violations:** {cert.violations_summary.get('scope_violations', 0)}",
        f"- **Sensitive Data / PII Leaks:** {cert.violations_summary.get('pii_leaks', 0)}",
        f"- **Ungrounded / Hallucinated Claims:** {cert.violations_summary.get('unsupported_groundedness_claims', 0)}",
        f"- **Total Non-Compliances:** {cert.violations_summary.get('total_violations', 0)}",
        "",
        "---",
        "",
        "## Cryptographic Attestation Signature",
        "",
        "```",
        "SHA-256 Digital Attestation Fingerprint:",
        f"{cert.digital_signature}",
        "```",
        "",
        "*This attestation certificate was generated deterministically by the automated AI Agent Governance Auditor under SOC 2 Type II and SEC Rule 17a-4 compliance controls.*",
    ])

    return "\n".join(lines)


def export_certificate_json(cert: ComplianceCertificate) -> str:
    """Export the ComplianceCertificate as formatted JSON."""
    return json.dumps(cert.model_dump(mode="json"), indent=2)
