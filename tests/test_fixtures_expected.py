"""Tests for good and bad trace fixtures against explicit expected audit results.

Verifies Part 10 Section 2 requirements:
Bad fixtures:
- unauthorized tool (fixtures/bad/bad_scope_violation.json)
- PII/secret exposure (fixtures/bad/bad_pii_exposure.json)
- contradicted final answer (fixtures/bad/bad_contradicted_final_answer.json)
- refund rule violation (fixtures/bad/bad_refund_rule_violation.json)
Good fixtures:
- valid customer refund (fixtures/valid_customer_refund.json)
- valid research summary (fixtures/valid_research_summary.json)
Every fixture is checked against explicit expected results.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auditor.groundedness_detector import GroundednessDetector
from auditor.models import RiskTier, Trace
from auditor.nli_classifier import MockNLIClassifier, NLIVerdict
from auditor.pii_detector import PIIDetector
from auditor.policy_loader import PolicyLoader
from auditor.risk_engine import RiskEngine
from auditor.scope_detector import ScopeDetector

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="module")
def expected_results() -> dict:
    expected_path = FIXTURES_DIR / "expected_results.json"
    with open(expected_path, encoding="utf-8") as f:
        return json.load(f)["fixtures"]


@pytest.fixture(scope="module")
def policy_loader() -> PolicyLoader:
    return PolicyLoader()


@pytest.fixture(scope="module")
def scope_detector(policy_loader: PolicyLoader) -> ScopeDetector:
    return ScopeDetector(risk_config=policy_loader.get_risk_config())


@pytest.fixture(scope="module")
def pii_detector(policy_loader: PolicyLoader) -> PIIDetector:
    return PIIDetector(risk_config=policy_loader.get_risk_config())


@pytest.fixture(scope="module")
def risk_engine(policy_loader: PolicyLoader) -> RiskEngine:
    return RiskEngine(risk_config=policy_loader.get_risk_config())


# =============================================================================
# Good Fixture 1: Valid Customer Refund
# =============================================================================
def test_fixture_valid_customer_refund(expected_results, policy_loader, scope_detector, pii_detector, risk_engine):
    exp = expected_results["valid_customer_refund.json"]
    trace_path = FIXTURES_DIR / "valid_customer_refund.json"
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)

    trace = Trace.model_validate(data)
    policy = policy_loader.get_policy(trace.task_type)

    scope_res = scope_detector.evaluate(trace, policy)
    assert scope_res.passed is True
    assert len(scope_res.findings) == exp["expected_scope_violations"]

    pii_res = pii_detector.evaluate(trace)
    assert pii_res.passed is True
    critical_or_high_leaks = [f for f in pii_res.findings if f.severity in (RiskTier.CRITICAL, RiskTier.HIGH)]
    assert len(critical_or_high_leaks) == exp["expected_pii_violations"]

    # Groundedness with entailed mock
    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.ENTAILMENT)
    ground_detector = GroundednessDetector(nli_classifier=mock_nli)
    ground_res = ground_detector.evaluate(trace)
    assert ground_res.contradicted_claims == exp["expected_groundedness_contradictions"]

    # Calculate overall risk
    risk = risk_engine.calculate_risk(
        scope_findings=scope_res.findings,
        pii_findings=pii_res.findings,
        groundedness_findings=ground_res.findings,
    )
    assert risk.risk_tier.value == exp["expected_risk_tier"]
    assert risk.overall_score <= exp["expected_max_risk_score"]


# =============================================================================
# Good Fixture 2: Valid Research Summary
# =============================================================================
def test_fixture_valid_research_summary(expected_results, policy_loader, scope_detector, pii_detector, risk_engine):
    exp = expected_results["valid_research_summary.json"]
    trace_path = FIXTURES_DIR / "valid_research_summary.json"
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)

    trace = Trace.model_validate(data)
    policy = policy_loader.get_policy(trace.task_type)

    scope_res = scope_detector.evaluate(trace, policy)
    assert scope_res.passed is True
    assert len(scope_res.findings) == exp["expected_scope_violations"]

    pii_res = pii_detector.evaluate(trace)
    assert pii_res.passed is True
    assert len(pii_res.findings) == exp["expected_pii_findings"]

    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.ENTAILMENT)
    ground_detector = GroundednessDetector(nli_classifier=mock_nli)
    ground_res = ground_detector.evaluate(trace)
    assert ground_res.contradicted_claims == exp["expected_groundedness_contradictions"]

    risk = risk_engine.calculate_risk(
        scope_findings=scope_res.findings,
        pii_findings=pii_res.findings,
        groundedness_findings=ground_res.findings,
    )
    assert risk.risk_tier.value == exp["expected_risk_tier"]
    assert risk.overall_score <= exp["expected_max_risk_score"]


# =============================================================================
# Bad Fixture 1: Unauthorized Tool (Scope Violation)
# =============================================================================
def test_fixture_bad_unauthorized_tool(expected_results, policy_loader, scope_detector, risk_engine):
    exp = expected_results["bad_scope_violation.json"]
    trace_path = FIXTURES_DIR / "bad" / "bad_scope_violation.json"
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)

    trace = Trace.model_validate(data)
    policy = policy_loader.get_policy(trace.task_type)

    scope_res = scope_detector.evaluate(trace, policy)
    assert scope_res.passed is False
    assert len(scope_res.findings) >= exp["expected_scope_violations"]

    unauth_findings = [f for f in scope_res.findings if f.tool_name == exp["expected_unauthorized_tool"]]
    assert len(unauth_findings) >= 1
    assert unauth_findings[0].rule_violated == "tool_not_allowed"

    risk = risk_engine.evaluate(scope_findings=scope_res.findings)
    assert risk.scope_score >= exp["expected_min_scope_score"]


# =============================================================================
# Bad Fixture 2: Refund Rule Violation (Excessive Refund)
# =============================================================================
def test_fixture_bad_refund_rule_violation(expected_results, policy_loader, scope_detector, risk_engine):
    exp = expected_results["bad_refund_rule_violation.json"]
    trace_path = FIXTURES_DIR / "bad" / "bad_refund_rule_violation.json"
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)

    trace = Trace.model_validate(data)
    policy = policy_loader.get_policy(trace.task_type)

    scope_res = scope_detector.evaluate(trace, policy)
    assert scope_res.passed is False
    assert any(f.rule_violated == "refund_exceeds_order_total" for f in scope_res.findings)

    risk = risk_engine.evaluate(scope_findings=scope_res.findings)
    assert risk.scope_score >= exp["expected_min_scope_score"]


# =============================================================================
# Bad Fixture 3: PII / Secret Exposure
# =============================================================================
def test_fixture_bad_pii_exposure(expected_results, pii_detector, risk_engine):
    exp = expected_results["bad_pii_exposure.json"]
    trace_path = FIXTURES_DIR / "bad" / "bad_pii_exposure.json"
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)

    trace = Trace.model_validate(data)
    pii_res = pii_detector.evaluate(trace)

    assert pii_res.passed is False
    assert len(pii_res.findings) >= exp["expected_pii_findings_min"]

    detected_types = {f.pii_type for f in pii_res.findings}
    for expected_type in exp["expected_detected_entities"]:
        assert expected_type in detected_types or any(expected_type in t for t in detected_types)

    risk = risk_engine.evaluate(pii_findings=pii_res.findings)
    assert risk.pii_score >= exp["expected_min_pii_score"]


# =============================================================================
# Bad Fixture 4: Contradicted Final Answer
# =============================================================================
def test_fixture_bad_contradicted_final_answer(expected_results, risk_engine):
    exp = expected_results["bad_contradicted_final_answer.json"]
    trace_path = FIXTURES_DIR / "bad" / "bad_contradicted_final_answer.json"
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)

    trace = Trace.model_validate(data)

    # NLI rule mapping return rejection vs approval to contradiction
    def nli_rule(premise: str, hypothesis: str) -> NLIVerdict | None:
        p = premise.lower()
        h = hypothesis.lower()
        if "rejected" in p and ("approved" in h or "accepted" in h):
            return NLIVerdict.CONTRADICTION
        return None

    mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.NEUTRAL, custom_rule=nli_rule)
    ground_detector = GroundednessDetector(similarity_threshold=0.0, nli_classifier=mock_nli)
    ground_res = ground_detector.evaluate(trace)

    assert ground_res.passed is False
    assert ground_res.contradicted_claims >= exp["expected_groundedness_contradictions_min"]

    risk = risk_engine.evaluate(groundedness_findings=ground_res.findings, total_claims=len(ground_res.findings))
    assert risk.groundedness_score >= exp["expected_min_groundedness_score"]

