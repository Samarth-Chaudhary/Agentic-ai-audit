"""Unit and integration tests for Groundedness, Claim Evidence, Embeddings, and NLI."""

import json
from pathlib import Path

from auditor.claim_extractor import extract_claims, score_claim_salience
from auditor.evidence import build_evidence_pool, normalize_structured_output
from auditor.groundedness_detector import GroundednessDetector
from auditor.models import RiskTier
from auditor.nli_classifier import (
    AuditVerdict,
    MockNLIClassifier,
    NLIVerdict,
    heuristic_nli_classify,
    map_nli_to_audit_verdict,
)

# ---------------------------------------------------------------------------
# 1. Evidence Extraction & Output Normalization Tests
# ---------------------------------------------------------------------------

def test_normalize_structured_json_dict_evidence():
    """Ensure structured dict outputs (revenue, growth) are converted into readable evidence sentences."""
    output = {
        "report": "Q3_Summary",
        "financials": {
            "revenue": 1200000,
            "growth": -0.20,
        },
    }
    normalized = normalize_structured_output(output)

    assert len(normalized) >= 2
    # Combined summary or individual fact assertions
    combined = " ".join(normalized)
    assert "revenue is 1200000" in combined or "revenue: 1200000" in combined
    assert "growth is -0.2" in combined or "growth: -0.2" in combined


def test_normalize_list_and_string_outputs():
    """Ensure array and scalar outputs are cleanly formatted."""
    list_out = ["Item Alpha", "Item Beta", 42]
    normalized = normalize_structured_output(list_out)
    assert "Item Alpha" in normalized
    assert "Item Beta" in normalized
    assert "42" in normalized

    str_json = '{"status": "DELIVERED", "order_id": 999}'
    norm_json = normalize_structured_output(str_json)
    combined = " ".join(norm_json)
    assert "DELIVERED" in combined


def test_build_evidence_pool_strict_tool_result_contract():
    """Ensure only tool_result steps contribute to the evidence pool."""
    trace_data = {
        "trace_id": "tr-test-pool",
        "schema_version": "1.0.0",
        "task_type": "customer_support",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "steps": [
            {
                "index": 0,
                "type": "assistant_message",
                "content": "Looking up shipment details in system.",
            },
            {
                "index": 1,
                "type": "tool_call",
                "call_id": "call-1",
                "tool_name": "order_lookup",
                "input": {"order_id": "123"},
            },
            {
                "index": 2,
                "type": "tool_result",
                "call_id": "call-1",
                "tool_name": "order_lookup",
                "output": {"status": "SHIPPED", "tracking_number": "TRK9876"},
                "details": {"data_source": "tool:order_db"},
            },
        ],
        "final_answer": "Your order has shipped with tracking number TRK9876.",
    }

    pool = build_evidence_pool(trace_data)
    assert len(pool) >= 1
    for ev in pool:
        assert ev.step_index == 2
        assert ev.tool_name == "order_lookup"
        assert ev.data_source == "tool:order_db"


# ---------------------------------------------------------------------------
# 2. Claim Extraction Tests
# ---------------------------------------------------------------------------

def test_extract_claims_filters_greetings_and_boilerplates():
    """Ensure greetings and trivial conversational fillers are removed."""
    answer = (
        "Hello! Thank you for reaching out to customer support. "
        "Revenue was $12 million in FY2025. "
        "Hope this helps! Have a great day."
    )
    claims = extract_claims(answer)

    assert len(claims) == 1
    assert "Revenue was $12 million in FY2025." in claims
    assert "Hello!" not in claims
    assert "Have a great day." not in claims


def test_extract_claims_prioritizes_factual_salience():
    """Ensure claims containing monetary figures, dates, and percentages score higher."""
    claim_financial = "The company reported $500,000 in net profit on January 15."
    claim_generic = "The system is functioning normally."

    score_fin = score_claim_salience(claim_financial)
    score_gen = score_claim_salience(claim_generic)

    assert score_fin > score_gen


def test_extract_claims_handles_empty_or_whitespace():
    """Ensure graceful handling of empty or blank text."""
    assert extract_claims("") == []
    assert extract_claims("   \n\t  ") == []


# ---------------------------------------------------------------------------
# 3. NLI Classification & Verdict Logic Tests
# ---------------------------------------------------------------------------

def test_verdict_mapping_logic():
    """Verify standard mapping from NLI verdict and evidence availability to audit verdict."""
    assert map_nli_to_audit_verdict(NLIVerdict.ENTAILMENT, True) == AuditVerdict.SUPPORTED
    assert map_nli_to_audit_verdict(NLIVerdict.CONTRADICTION, True) == AuditVerdict.CONTRADICTED
    assert map_nli_to_audit_verdict(NLIVerdict.NEUTRAL, True) == AuditVerdict.UNSUPPORTED
    assert map_nli_to_audit_verdict(NLIVerdict.ENTAILMENT, False) == AuditVerdict.UNSUPPORTED


def test_heuristic_nli_minimum_cases():
    """Verify heuristic NLI correctly handles the required minimum evaluation cases."""
    # Contradiction: decreased vs increased
    v_contra = heuristic_nli_classify("Revenue decreased 20%.", "Revenue increased 20%.")
    assert v_contra == NLIVerdict.CONTRADICTION

    # Supported: identical claim
    v_supp = heuristic_nli_classify("Revenue was $12 million.", "Revenue was $12 million.")
    assert v_supp == NLIVerdict.ENTAILMENT

    # Unsupported: forecast prediction not present in evidence
    v_unsupp = heuristic_nli_classify("Revenue was $12 million.", "Revenue will double next year.")
    assert v_unsupp == NLIVerdict.NEUTRAL


def test_mock_nli_classifier_deterministic():
    """Verify MockNLIClassifier can be used for deterministic test injection."""
    mock = MockNLIClassifier(
        overrides={
            ("premise_a", "hypothesis_a"): NLIVerdict.CONTRADICTION,
            ("premise_b", "hypothesis_b"): NLIVerdict.ENTAILMENT,
        }
    )
    assert mock.classify("premise_a", "hypothesis_a") == NLIVerdict.CONTRADICTION
    assert mock.classify("premise_b", "hypothesis_b") == NLIVerdict.ENTAILMENT
    assert mock.classify("unseen_premise", "unseen_hypo") == NLIVerdict.NEUTRAL


# ---------------------------------------------------------------------------
# 4. Validation Gate: Fixture-Level Outcomes
# ---------------------------------------------------------------------------

def test_validation_gate_supported_claim_fixture(fixtures_dir: Path):
    """Validation Gate: Verify supported fixture returns SUPPORTED with preserved provenance."""
    fixture_path = fixtures_dir / "groundedness" / "supported_claim.json"
    with open(fixture_path, encoding="utf-8") as f:
        trace = json.load(f)

    detector = GroundednessDetector()
    result = detector.evaluate(trace)

    assert result.passed is True
    assert result.supported_claims == 1
    assert result.contradicted_claims == 0
    assert result.unsupported_claims == 0

    finding = result.findings[0]
    assert finding.audit_verdict == "SUPPORTED"
    assert finding.nli_verdict == "ENTAILMENT"
    assert finding.is_grounded is True
    assert finding.evidence_step_index == 1
    assert finding.tool_name == "lookup_financial_metrics"
    assert finding.similarity >= 0.50
    assert "Revenue was $12 million." in finding.evidence_snippet


def test_validation_gate_contradiction_fixture(fixtures_dir: Path):
    """Validation Gate: Verify contradiction fixture returns CONTRADICTED with CRITICAL severity."""
    fixture_path = fixtures_dir / "groundedness" / "contradiction_claim.json"
    with open(fixture_path, encoding="utf-8") as f:
        trace = json.load(f)

    detector = GroundednessDetector()
    result = detector.evaluate(trace)

    assert result.passed is False
    assert result.contradicted_claims == 1
    assert result.supported_claims == 0

    finding = result.findings[0]
    assert finding.audit_verdict == "CONTRADICTED"
    assert finding.nli_verdict == "CONTRADICTION"
    assert finding.is_grounded is False
    assert finding.severity == RiskTier.CRITICAL
    assert finding.evidence_step_index == 1
    assert finding.tool_name == "lookup_financial_metrics"
    assert finding.similarity >= 0.50
    assert "Revenue decreased 20%." in finding.evidence_snippet


def test_validation_gate_unsupported_fixture(fixtures_dir: Path):
    """Validation Gate: Verify unsupported fixture returns UNSUPPORTED with preserved provenance."""
    fixture_path = fixtures_dir / "groundedness" / "unsupported_claim.json"
    with open(fixture_path, encoding="utf-8") as f:
        trace = json.load(f)

    detector = GroundednessDetector()
    result = detector.evaluate(trace)

    assert result.passed is False
    assert result.unsupported_claims == 1
    assert result.supported_claims == 0

    finding = result.findings[0]
    assert finding.audit_verdict == "UNSUPPORTED"
    assert finding.is_grounded is False
    assert finding.evidence_step_index == 1
    assert finding.tool_name == "lookup_financial_metrics"


def test_groundedness_finding_contract_fields():
    """Verify each claim record contains all mandatory fields specified in Section 9."""
    detector = GroundednessDetector()
    trace = {
        "trace_id": "tr-contract-fields",
        "schema_version": "1.0.0",
        "task_type": "test",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_result",
                "tool_name": "calc",
                "output": "42",
            }
        ],
        "final_answer": "The answer is 42.",
    }
    result = detector.evaluate(trace)
    assert len(result.findings) >= 1
    f = result.findings[0]

    # Required Section 9 fields
    assert hasattr(f, "claim") and f.claim
    assert hasattr(f, "evidence_snippet") and f.evidence_snippet
    assert hasattr(f, "evidence_step_index") and f.evidence_step_index == 0
    assert hasattr(f, "tool_name") and f.tool_name == "calc"
    assert hasattr(f, "similarity") and isinstance(f.similarity, float)
    assert hasattr(f, "nli_verdict") and f.nli_verdict
    assert hasattr(f, "audit_verdict") and f.audit_verdict
