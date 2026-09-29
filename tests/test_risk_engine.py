"""Unit tests for the Risk Scoring Engine.

Covers:
- Scope score calculation (counts, severities, capping at 100)
- PII score calculation (contextual low severity vs critical secrets, capping at 100)
- Groundedness score calculation (zero claims, supported, unsupported, contradicted)
- Composite weighted risk score calculation & weight normalization
- Categorical risk tier thresholds and exact boundary conditions
- Deterministic human-readable summary generation
"""

from __future__ import annotations

import pytest

from auditor.models import (
    GroundednessFinding,
    PIIFinding,
    RiskTier,
    ScopeFinding,
)
from auditor.policy_loader import ControlWeights, RiskConfig, TierThresholds
from auditor.risk_engine import RiskEngine, build_deterministic_summary


@pytest.fixture
def standard_risk_config() -> RiskConfig:
    return RiskConfig(
        version="1.0.0",
        control_weights=ControlWeights(
            scope_violation=0.35,
            pii_leakage=0.35,
            groundedness=0.30,
        ),
        tier_thresholds=TierThresholds(
            low=20.0,
            medium=50.0,
            high=80.0,
            critical=100.0,
        ),
        groundedness_similarity_threshold=0.70,
        severity_mappings={},
    )


@pytest.fixture
def risk_engine(standard_risk_config: RiskConfig) -> RiskEngine:
    return RiskEngine(risk_config=standard_risk_config)


# ==========================================
# 1. SCOPE SCORE TESTS
# ==========================================


def test_scope_score_zero_findings(risk_engine: RiskEngine):
    """Ensure zero scope findings yield a score of 0.0."""
    score = risk_engine.calculate_scope_score([])
    assert score == 0.0


def test_scope_score_severity_weights(risk_engine: RiskEngine):
    """Ensure severities map deterministically: CRITICAL=50, HIGH=30, MEDIUM=15, LOW=5."""
    low_f = [ScopeFinding(tool_name="tool_a", rule_violated="rule_1", severity=RiskTier.LOW, detail="Minor notice")]
    assert risk_engine.calculate_scope_score(low_f) == 5.0

    med_f = [ScopeFinding(tool_name="tool_a", rule_violated="rule_2", severity=RiskTier.MEDIUM, detail="Call count")]
    assert risk_engine.calculate_scope_score(med_f) == 15.0

    high_f = [ScopeFinding(tool_name="tool_a", rule_violated="rule_3", severity=RiskTier.HIGH, detail="Unauthorized tool")]
    assert risk_engine.calculate_scope_score(high_f) == 30.0

    crit_f = [ScopeFinding(tool_name="tool_a", rule_violated="rule_4", severity=RiskTier.CRITICAL, detail="Business rule")]
    assert risk_engine.calculate_scope_score(crit_f) == 50.0


def test_scope_score_capping_at_100(risk_engine: RiskEngine):
    """Ensure scope score caps strictly at 100.0 when multiple severe violations occur."""
    findings = [
        ScopeFinding(tool_name="tool_1", rule_violated="r1", severity=RiskTier.CRITICAL, detail="d1"),
        ScopeFinding(tool_name="tool_2", rule_violated="r2", severity=RiskTier.CRITICAL, detail="d2"),
        ScopeFinding(tool_name="tool_3", rule_violated="r3", severity=RiskTier.HIGH, detail="d3"),
    ]
    # 50 + 50 + 30 = 130 -> capped at 100.0
    score = risk_engine.calculate_scope_score(findings)
    assert score == 100.0


# ==========================================
# 2. PII / SENSITIVE DATA SCORE TESTS
# ==========================================


def test_pii_score_zero_findings(risk_engine: RiskEngine):
    """Ensure zero PII findings yield 0.0."""
    score = risk_engine.calculate_pii_score([])
    assert score == 0.0


def test_pii_score_contextual_vs_secrets(risk_engine: RiskEngine):
    """Ensure secrets/credentials contribute differently from low-severity contextual detections."""
    # Low severity: e.g. Customer name or location in DB output
    low_findings = [
        PIIFinding(field_path="output.customer", pii_type="PERSON", severity=RiskTier.LOW, redacted_snippet="[PERSON]"),
        PIIFinding(field_path="output.city", pii_type="LOCATION", severity=RiskTier.LOW, redacted_snippet="[LOCATION]"),
    ]
    # 5.0 + 5.0 = 10.0
    assert risk_engine.calculate_pii_score(low_findings) == 10.0

    # Critical severity: e.g. Plaintext API key or password
    secret_findings = [
        PIIFinding(field_path="output.apiKey", pii_type="API_KEY", severity=RiskTier.CRITICAL, redacted_snippet="[SECRET]"),
        PIIFinding(field_path="output.password", pii_type="PASSWORD", severity=RiskTier.CRITICAL, redacted_snippet="[SECRET]"),
    ]
    # 50.0 + 50.0 = 100.0
    assert risk_engine.calculate_pii_score(secret_findings) == 100.0


def test_pii_score_capping_at_100(risk_engine: RiskEngine):
    """Ensure PII score caps strictly at 100.0."""
    many_findings = [
        PIIFinding(field_path=f"output.{i}", pii_type="EMAIL", severity=RiskTier.HIGH, redacted_snippet="[EMAIL]")
        for i in range(5)
    ]
    # 5 * 30.0 = 150.0 -> capped at 100.0
    assert risk_engine.calculate_pii_score(many_findings) == 100.0


# ==========================================
# 3. GROUNDEDNESS SCORE TESTS
# ==========================================


def test_groundedness_score_zero_factual_claims(risk_engine: RiskEngine):
    """Clearly define that when zero factual claims are checked, groundedness risk score is 0.0."""
    score_empty = risk_engine.calculate_groundedness_score([], total_claims=0)
    assert score_empty == 0.0

    score_explicit_zero = risk_engine.calculate_groundedness_score([], total_claims=0)
    assert score_explicit_zero == 0.0


def test_groundedness_score_all_supported(risk_engine: RiskEngine):
    """Ensure fully supported claims yield 0.0 risk score."""
    findings = [
        GroundednessFinding(
            claim="Claim 1",
            evidence_snippet="Evidence 1",
            similarity=0.9,
            nli_verdict="ENTAILMENT",
            audit_verdict="SUPPORTED",
            is_grounded=True,
            severity=RiskTier.LOW,
        ),
        GroundednessFinding(
            claim="Claim 2",
            evidence_snippet="Evidence 2",
            similarity=0.85,
            nli_verdict="ENTAILMENT",
            audit_verdict="SUPPORTED",
            is_grounded=True,
            severity=RiskTier.LOW,
        ),
    ]
    score = risk_engine.calculate_groundedness_score(findings, total_claims=2)
    assert score == 0.0


def test_groundedness_score_unsupported_and_contradicted_proportions(risk_engine: RiskEngine):
    """Ensure unsupported (0.7 weight) and contradicted (1.0 weight) contribute proportionally."""
    # 1 claim out of 1 unsupported -> 70.0%
    unsupp_finding = GroundednessFinding(
        claim="Unsupported claim",
        evidence_snippet="Irrelevant",
        similarity=0.2,
        audit_verdict="UNSUPPORTED",
        is_grounded=False,
        severity=RiskTier.HIGH,
    )
    assert risk_engine.calculate_groundedness_score([unsupp_finding], total_claims=1) == 70.0

    # 1 claim out of 1 contradicted -> 100.0%
    contra_finding = GroundednessFinding(
        claim="Contradicted claim",
        evidence_snippet="Opposite evidence",
        similarity=0.8,
        audit_verdict="CONTRADICTED",
        is_grounded=False,
        severity=RiskTier.CRITICAL,
    )
    assert risk_engine.calculate_groundedness_score([contra_finding], total_claims=1) == 100.0

    # 2 claims: 1 supported, 1 unsupported -> (0.0 + 0.7) / 2 * 100 = 35.0%
    supp_finding = GroundednessFinding(
        claim="Supported",
        evidence_snippet="Match",
        similarity=0.9,
        audit_verdict="SUPPORTED",
        is_grounded=True,
        severity=RiskTier.LOW,
    )
    score_mixed = risk_engine.calculate_groundedness_score([supp_finding, unsupp_finding], total_claims=2)
    assert score_mixed == 35.0

    # 2 claims: 1 supported, 1 contradicted -> (0.0 + 1.0) / 2 * 100 = 50.0%
    score_contra_mixed = risk_engine.calculate_groundedness_score([supp_finding, contra_finding], total_claims=2)
    assert score_contra_mixed == 50.0


# ==========================================
# 4. COMPOSITE WEIGHTED SCORE & NORMALIZATION
# ==========================================


def test_composite_score_formula(risk_engine: RiskEngine):
    """Test overall_risk = scope * w_scope + pii * w_pii + gnd * w_gnd."""
    # Scope: 1 HIGH finding = 30.0 pts. Weight: 0.35 -> 10.5
    scope_findings = [ScopeFinding(tool_name="t1", rule_violated="r1", severity=RiskTier.HIGH, detail="d")]
    # PII: 1 MEDIUM finding = 15.0 pts. Weight: 0.35 -> 5.25
    pii_findings = [PIIFinding(field_path="p", pii_type="EMAIL", severity=RiskTier.MEDIUM, redacted_snippet="e")]
    # GND: 1 unsupported out of 1 = 70.0 pts. Weight: 0.30 -> 21.0
    gnd_findings = [GroundednessFinding(claim="c", evidence_snippet="e", similarity=0.1, audit_verdict="UNSUPPORTED", severity=RiskTier.HIGH)]

    breakdown = risk_engine.evaluate(
        scope_findings=scope_findings,
        pii_findings=pii_findings,
        groundedness_findings=gnd_findings,
        total_claims=1,
    )

    expected_score = round((30.0 * 0.35) + (15.0 * 0.35) + (70.0 * 0.30), 2)
    assert breakdown.overall_score == expected_score  # 10.5 + 5.25 + 21.0 = 36.75
    assert breakdown.risk_tier == RiskTier.MEDIUM


def test_weight_normalization_if_sum_not_one():
    """Ensure weights sum is normalized if custom weights don't sum to 1.0."""
    unnormalized_config = RiskConfig(
        version="1.0.0",
        control_weights=ControlWeights(
            scope_violation=0.5,
            pii_leakage=0.5,
            groundedness=0.0,
        ),
        tier_thresholds=TierThresholds(low=20.0, medium=50.0, high=80.0, critical=100.0),
        groundedness_similarity_threshold=0.70,
    )
    # Manually bypass validator to simulate raw dict deviation
    unnormalized_config.control_weights.scope_violation = 1.0
    unnormalized_config.control_weights.pii_leakage = 1.0
    unnormalized_config.control_weights.groundedness = 2.0
    # Sum = 4.0 -> normalized: 0.25, 0.25, 0.50

    engine = RiskEngine(risk_config=unnormalized_config)
    breakdown = engine.evaluate(
        scope_findings=[ScopeFinding(tool_name="t", rule_violated="r", severity=RiskTier.CRITICAL, detail="d")],  # 50.0
        pii_findings=[],  # 0.0
        groundedness_findings=[],  # 0.0
    )

    # 50.0 * 0.25 = 12.5
    assert breakdown.overall_score == 12.5
    assert breakdown.scope_weight == 0.25
    assert breakdown.pii_weight == 0.25
    assert breakdown.groundedness_weight == 0.50


# ==========================================
# 5. TIER THRESHOLDS & BOUNDARY CONDITIONS
# ==========================================


@pytest.mark.parametrize(
    ("score", "expected_tier"),
    [
        (0.0, RiskTier.LOW),
        (10.0, RiskTier.LOW),
        (19.99, RiskTier.LOW),
        (20.0, RiskTier.MEDIUM),  # Low boundary
        (35.5, RiskTier.MEDIUM),
        (49.99, RiskTier.MEDIUM),
        (50.0, RiskTier.HIGH),    # Medium boundary
        (65.0, RiskTier.HIGH),
        (79.99, RiskTier.HIGH),
        (80.0, RiskTier.CRITICAL), # High boundary
        (95.0, RiskTier.CRITICAL),
        (100.0, RiskTier.CRITICAL),
    ],
)
def test_tier_boundary_mappings(risk_engine: RiskEngine, score: float, expected_tier: RiskTier):
    """Verify exact tier assignment across all threshold boundary conditions."""
    tier = risk_engine.assign_risk_tier(score)
    assert tier == expected_tier


# ==========================================
# 6. DETERMINISTIC HUMAN-READABLE SUMMARY
# ==========================================


def test_deterministic_summary_clean_trace():
    """Ensure clean trace summary is reassuring and factual."""
    summary = build_deterministic_summary(
        risk_tier=RiskTier.LOW,
        risk_score=0.0,
        scope_findings=[],
        pii_findings=[],
        groundedness_findings=[],
    )
    assert "evaluated as LOW risk" in summary
    assert "zero scope violations" in summary
    assert "zero sensitive data disclosures" in summary


def test_deterministic_summary_single_scope_and_unsupported_claims():
    """Verify narrative matches the exact specification:
    'Trace was flagged HIGH because it contained one unauthorized tool call and two unsupported final-answer claims.'
    """
    scope_findings = [
        ScopeFinding(
            tool_name="unauthorized_bash",
            violation_type="unauthorized_tool",
            rule_violated="tool_not_allowed",
            severity=RiskTier.HIGH,
            detail="Tool not allowed",
        )
    ]
    groundedness_findings = [
        GroundednessFinding(claim="Claim A", evidence_snippet="e1", similarity=0.1, audit_verdict="UNSUPPORTED", severity=RiskTier.HIGH),
        GroundednessFinding(claim="Claim B", evidence_snippet="e2", similarity=0.2, audit_verdict="UNSUPPORTED", severity=RiskTier.HIGH),
    ]

    summary = build_deterministic_summary(
        risk_tier=RiskTier.HIGH,
        risk_score=60.0,
        scope_findings=scope_findings,
        pii_findings=[],
        groundedness_findings=groundedness_findings,
    )

    assert "Trace was flagged HIGH because it contained one unauthorized tool call and two unsupported final-answer claims." in summary
