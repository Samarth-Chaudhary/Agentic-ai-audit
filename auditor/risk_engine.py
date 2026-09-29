"""Risk Scoring Engine for AI Agent Governance.

Combines findings from independent audit controls (Scope, Sensitive Data/PII,
and Groundedness) into normalized sub-scores, a weighted composite risk score,
and a categorical risk tier.

MATHEMATICAL SPECIFICATION:
===========================

1. SCOPE SCORE (0 - 100):
   Evaluates tool permissions, call counts, and business rule conformance.
   Formula:
       scope_score = min(100.0, sum(W_scope(severity) for finding in scope_findings))
   where severity weights are:
       - CRITICAL: 50.0 pts (e.g. domain business rule violation)
       - HIGH:     30.0 pts (e.g. unauthorized tool or unauthorized data source)
       - MEDIUM:   15.0 pts (e.g. max tool calls limit exceeded)
       - LOW:       5.0 pts (e.g. minor operational notice)

2. PII / SENSITIVE DATA SCORE (0 - 100):
   Evaluates secrets, credentials, and sensitive disclosures.
   Formula:
       pii_score = min(100.0, sum(W_pii(severity) for finding in pii_findings))
   where severity weights are:
       - CRITICAL: 50.0 pts (e.g. passwords, API keys, private keys, SSN, credit cards)
       - HIGH:     30.0 pts (e.g. IBANs, bank routing numbers, external tool leaks)
       - MEDIUM:   15.0 pts (e.g. email addresses, phone numbers)
       - LOW:       5.0 pts (e.g. contextual person names, locations)

3. GROUNDEDNESS SCORE (0 - 100):
   Evaluates factual grounding of agent claims against verified tool outputs.
   Specification:
       - If zero factual claims checked (total_claims == 0):
             groundedness_score = 0.0 (no ungrounded assertions made).
       - If total_claims > 0:
             groundedness_score = min(100.0, round(
                 (1.0 * contradicted_count + 0.7 * unsupported_count) / total_claims * 100.0,
                 2
             ))
   where:
       - CONTRADICTED claims receive 1.0 (100% risk weight, critical factual conflict)
       - UNSUPPORTED claims receive 0.7 (70% risk weight, unevidenced assertion)
       - SUPPORTED claims contribute 0.0 risk.

4. COMPOSITE OVERALL RISK SCORE (0 - 100):
   Weights are loaded from configuration (config/risk_config.yaml):
       w_scope = risk_config.control_weights.scope_violation (default 0.35)
       w_pii   = risk_config.control_weights.pii_leakage      (default 0.35)
       w_gnd   = risk_config.control_weights.groundedness     (default 0.30)
   Formula:
       overall_risk = min(100.0, max(0.0, round(
           scope_score * w_scope + pii_score * w_pii + groundedness_score * w_gnd,
           2
       )))

5. CATEGORICAL RISK TIERS:
   Assigned based on configured monotonic thresholds (e.g. 20.0, 50.0, 80.0, 100.0):
       - score < low (20.0)             -> LOW
       - low (20.0) <= score < med (50.0) -> MEDIUM
       - med (50.0) <= score < high (80.0) -> HIGH
       - score >= high (80.0)           -> CRITICAL
"""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from auditor.models import (
    GroundednessFinding,
    PIIFinding,
    RiskResult,
    RiskTier,
    ScopeFinding,
)
from auditor.policy_loader import PolicyLoader, RiskConfig
from project.logging import get_logger

logger = get_logger(__name__, component="risk_engine")

# Severity point assignments for additive control evaluation
SCOPE_SEVERITY_POINTS: dict[str, float] = {
    "CRITICAL": 50.0,
    "HIGH": 30.0,
    "MEDIUM": 15.0,
    "LOW": 5.0,
}

PII_SEVERITY_POINTS: dict[str, float] = {
    "CRITICAL": 50.0,
    "HIGH": 30.0,
    "MEDIUM": 15.0,
    "LOW": 5.0,
}


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """Format human-readable number with word agreement."""
    word_map = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    num_str = word_map.get(count, str(count))
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{num_str} {word}"


def build_deterministic_summary(
    risk_tier: RiskTier,
    risk_score: float,
    scope_findings: Sequence[ScopeFinding],
    pii_findings: Sequence[PIIFinding],
    groundedness_findings: Sequence[GroundednessFinding],
) -> str:
    """Construct a strictly factual, deterministic narrative summary from findings.

    Never hallucinates or generates explanations not directly supported by actual findings.
    Example:
    'Trace was flagged HIGH because it contained one unauthorized tool call and two unsupported final-answer claims.'
    """
    reasons: list[str] = []

    # 1. Scope violations breakdown
    if scope_findings:
        unauth_tools = sum(1 for f in scope_findings if f.violation_type == "unauthorized_tool")
        unauth_sources = sum(1 for f in scope_findings if f.violation_type == "unauthorized_data_source")
        rule_violations = sum(1 for f in scope_findings if f.violation_type == "rule_violation")
        limit_violations = sum(1 for f in scope_findings if f.violation_type == "max_calls_exceeded")
        other_scope = len(scope_findings) - (unauth_tools + unauth_sources + rule_violations + limit_violations)

        if unauth_tools:
            reasons.append(f"{_plural(unauth_tools, 'unauthorized tool call')}")
        if unauth_sources:
            reasons.append(f"{_plural(unauth_sources, 'unauthorized data source access', 'unauthorized data source accesses')}")
        if rule_violations:
            reasons.append(f"{_plural(rule_violations, 'business rule violation')}")
        if limit_violations:
            reasons.append("tool call limit exceeded")
        if other_scope > 0:
            reasons.append(f"{_plural(other_scope, 'scope violation')}")

    # 2. PII / Sensitive data breakdown
    if pii_findings:
        crit_pii = sum(1 for f in pii_findings if (f.severity.value if hasattr(f.severity, "value") else str(f.severity)) == "CRITICAL")
        other_pii = len(pii_findings) - crit_pii
        pii_types = sorted({f.pii_type for f in pii_findings if f.pii_type})

        type_str = f" ({', '.join(pii_types)})" if pii_types else ""
        if crit_pii > 0 and other_pii == 0:
            reasons.append(f"{_plural(crit_pii, 'critical sensitive disclosure')}{type_str}")
        elif crit_pii > 0:
            reasons.append(f"{_plural(len(pii_findings), 'sensitive data disclosure')}{type_str} including {_plural(crit_pii, 'critical secret')}")
        else:
            reasons.append(f"{_plural(len(pii_findings), 'sensitive data disclosure')}{type_str}")

    # 3. Groundedness breakdown
    if groundedness_findings:
        contra_count = sum(1 for f in groundedness_findings if f.audit_verdict == "CONTRADICTED")
        unsupp_count = sum(1 for f in groundedness_findings if f.audit_verdict == "UNSUPPORTED")

        if contra_count:
            reasons.append(f"{_plural(contra_count, 'contradicted final-answer claim')}")
        if unsupp_count:
            reasons.append(f"{_plural(unsupp_count, 'unsupported final-answer claim')}")

    if not reasons:
        return (
            f"Trace was evaluated as {risk_tier.value} risk (risk score {risk_score:.1f}) "
            "with zero scope violations, zero sensitive data disclosures, and fully grounded claims."
        )

    joined_reasons = ", ".join(reasons[:-1]) + f" and {reasons[-1]}" if len(reasons) > 1 else reasons[0]
    return f"Trace was flagged {risk_tier.value} because it contained {joined_reasons}."


class RiskBreakdown(BaseModel):
    """Detailed risk scoring component breakdown with weights and thresholds."""
    scope_score: float = Field(ge=0.0, le=100.0, description="Normalized scope risk score")
    pii_score: float = Field(ge=0.0, le=100.0, description="Normalized PII risk score")
    groundedness_score: float = Field(ge=0.0, le=100.0, description="Normalized groundedness risk score")
    overall_score: float = Field(ge=0.0, le=100.0, description="Composite overall risk score")
    risk_tier: RiskTier = Field(description="Assigned categorical risk tier")
    scope_weight: float = Field(ge=0.0, le=1.0)
    pii_weight: float = Field(ge=0.0, le=1.0)
    groundedness_weight: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="Deterministic human-readable explanation")


class RiskEngine:
    """Configurable, deterministic risk engine for composite multi-control governance."""

    def __init__(self, risk_config: RiskConfig | None = None) -> None:
        if risk_config is None:
            loader = PolicyLoader()
            self.risk_config = loader.load_risk_config()
        else:
            self.risk_config = risk_config

    def calculate_scope_score(self, findings: Sequence[ScopeFinding]) -> float:
        """Calculate normalized scope risk score (0 - 100) from findings.

        Formula:
            score = min(100.0, sum(SCOPE_SEVERITY_POINTS[finding.severity]))
        """
        if not findings:
            return 0.0

        total = 0.0
        for f in findings:
            sev_str = f.severity.value if hasattr(f.severity, "value") else str(f.severity).upper()
            total += SCOPE_SEVERITY_POINTS.get(sev_str, 15.0)

        return min(100.0, round(total, 2))

    def calculate_pii_score(self, findings: Sequence[PIIFinding]) -> float:
        """Calculate normalized PII/Sensitive Data risk score (0 - 100) from findings.

        Formula:
            score = min(100.0, sum(PII_SEVERITY_POINTS[finding.severity]))
        """
        if not findings:
            return 0.0

        total = 0.0
        for f in findings:
            sev_str = f.severity.value if hasattr(f.severity, "value") else str(f.severity).upper()
            total += PII_SEVERITY_POINTS.get(sev_str, 15.0)

        return min(100.0, round(total, 2))

    def calculate_groundedness_score(
        self,
        findings: Sequence[GroundednessFinding],
        total_claims: int | None = None,
    ) -> float:
        """Calculate normalized groundedness risk score (0 - 100).

        Specification:
            - If total_claims == 0: returns 0.0 (no ungrounded assertions made).
            - If total_claims > 0:
                  score = min(100.0, ((1.0 * contra + 0.7 * unsupp) / total_claims) * 100.0)
        """
        claim_count = total_claims if total_claims is not None else len(findings)
        if claim_count <= 0 or not findings:
            return 0.0

        contra_count = sum(1 for f in findings if f.audit_verdict == "CONTRADICTED")
        unsupp_count = sum(1 for f in findings if f.audit_verdict == "UNSUPPORTED")

        weighted_penalty = (1.0 * contra_count) + (0.7 * unsupp_count)
        score = (weighted_penalty / max(1, claim_count)) * 100.0

        return min(100.0, round(score, 2))

    def assign_risk_tier(self, score: float) -> RiskTier:
        """Assign categorical RiskTier based on configured tier thresholds.

        Boundaries (from risk_config.yaml):
            score < low               -> LOW
            low <= score < medium     -> MEDIUM
            medium <= score < high    -> HIGH
            score >= high             -> CRITICAL
        """
        thresholds = self.risk_config.tier_thresholds
        if score < thresholds.low:
            return RiskTier.LOW
        elif score < thresholds.medium:
            return RiskTier.MEDIUM
        elif score < thresholds.high:
            return RiskTier.HIGH
        else:
            return RiskTier.CRITICAL

    def evaluate(
        self,
        scope_findings: Sequence[ScopeFinding] = (),
        pii_findings: Sequence[PIIFinding] = (),
        groundedness_findings: Sequence[GroundednessFinding] = (),
        total_claims: int | None = None,
    ) -> RiskBreakdown:
        """Compute all control sub-scores, composite weighted score, tier, and narrative."""
        scope_score = self.calculate_scope_score(scope_findings)
        pii_score = self.calculate_pii_score(pii_findings)
        groundedness_score = self.calculate_groundedness_score(groundedness_findings, total_claims=total_claims)

        # Retrieve control weights
        w_scope = self.risk_config.control_weights.scope_violation
        w_pii = self.risk_config.control_weights.pii_leakage
        w_gnd = self.risk_config.control_weights.groundedness

        # Normalize weights if sum deviates from 1.0
        total_weight = w_scope + w_pii + w_gnd
        if abs(total_weight - 1.0) > 1e-4 and total_weight > 0:
            w_scope /= total_weight
            w_pii /= total_weight
            w_gnd /= total_weight

        # Compute composite score
        overall_score = min(
            100.0,
            max(
                0.0,
                round(
                    (scope_score * w_scope) + (pii_score * w_pii) + (groundedness_score * w_gnd),
                    2,
                ),
            ),
        )

        risk_tier = self.assign_risk_tier(overall_score)
        summary = build_deterministic_summary(
            risk_tier=risk_tier,
            risk_score=overall_score,
            scope_findings=scope_findings,
            pii_findings=pii_findings,
            groundedness_findings=groundedness_findings,
        )

        logger.info(
            f"Risk evaluation complete: overall={overall_score:.2f} ({risk_tier.value}) "
            f"[scope={scope_score:.2f}, pii={pii_score:.2f}, gnd={groundedness_score:.2f}]"
        )

        return RiskBreakdown(
            scope_score=scope_score,
            pii_score=pii_score,
            groundedness_score=groundedness_score,
            overall_score=overall_score,
            risk_tier=risk_tier,
            scope_weight=round(w_scope, 4),
            pii_weight=round(w_pii, 4),
            groundedness_weight=round(w_gnd, 4),
            summary=summary,
        )

    def to_risk_result(self, breakdown: RiskBreakdown) -> RiskResult:
        """Convert RiskBreakdown to standard RiskResult model."""
        return RiskResult(
            scope_score=breakdown.scope_score,
            pii_score=breakdown.pii_score,
            groundedness_score=breakdown.groundedness_score,
            overall_score=breakdown.overall_score,
            risk_tier=breakdown.risk_tier,
        )

    calculate_risk = evaluate

