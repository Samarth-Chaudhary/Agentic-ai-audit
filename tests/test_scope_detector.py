"""Unit and integration tests for Scope Detector and modular governance rules."""

import json
from pathlib import Path

import pytest

from auditor.models import RiskTier
from auditor.policy_loader import PolicyLoader, TaskPolicy
from auditor.scope_detector import ScopeDetector


@pytest.fixture
def policy_loader(config_dir: Path) -> PolicyLoader:
    return PolicyLoader(
        task_policy_path=config_dir / "task_policies.yaml",
        risk_config_path=config_dir / "risk_config.yaml",
    )


@pytest.fixture
def customer_refund_policy(policy_loader: PolicyLoader) -> TaskPolicy:
    return policy_loader.get_policy("customer_refund")


@pytest.fixture
def detector(policy_loader: PolicyLoader) -> ScopeDetector:
    return ScopeDetector(risk_config=policy_loader.get_risk_config())


# ---------------------------------------------------------------------------
# 1. Tool Permission Tests
# ---------------------------------------------------------------------------

def test_allowed_tool_no_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure compliant trace using allowed tools yields zero tool_not_allowed violations."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is True
    assert len(result.findings) == 0
    assert not any(f.rule_violated == "tool_not_allowed" for f in result.findings)


def test_unauthorized_tool_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure unauthorized tool (e.g. web_search in customer_refund) is detected."""
    with open(fixtures_dir / "bad" / "bad_scope_violation.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False
    assert result.total_violations >= 1

    tool_findings = [f for f in result.findings if f.rule_violated == "tool_not_allowed"]
    assert len(tool_findings) >= 1
    finding = tool_findings[0]
    assert finding.tool_name == "web_search"
    assert finding.step_index == 4
    assert finding.severity == RiskTier.HIGH
    assert "web_search" in finding.detail


# ---------------------------------------------------------------------------
# 2. Data Source Scope Tests
# ---------------------------------------------------------------------------

def test_allowed_data_source_no_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure permitted data sources produce no unauthorized_data_source findings."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert not any(f.rule_violated == "unauthorized_data_source" for f in result.findings)


def test_forbidden_source_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure forbidden data source is flagged with step and source name."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    # Inject unauthorized data source into tool output
    trace_data["steps"][2]["output"]["data_source"] = "unauthorized_internal_hr_ldap"

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False
    source_findings = [f for f in result.findings if f.rule_violated == "unauthorized_data_source"]
    assert len(source_findings) >= 1
    assert "unauthorized_internal_hr_ldap" in source_findings[0].detail
    assert source_findings[0].step_index == 2


# ---------------------------------------------------------------------------
# 3. Call Limit & Repetition Tests
# ---------------------------------------------------------------------------

def test_call_limit_exceeded_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure exceeding policy max_calls flags the exact offending steps."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    # Temporarily set policy max_calls to 1
    strict_policy = TaskPolicy(
        allowed_tools=customer_refund_policy.allowed_tools,
        allowed_data_sources=customer_refund_policy.allowed_data_sources,
        max_calls=1,
        business_rules=customer_refund_policy.business_rules,
    )

    result = detector.evaluate(trace_data, strict_policy)
    assert result.passed is False
    limit_findings = [f for f in result.findings if f.rule_violated == "max_calls_exceeded"]
    assert len(limit_findings) == 1
    # Step 4 was the 2nd tool call
    assert limit_findings[0].step_index == 4
    assert limit_findings[0].tool_name == "refund_tool"


# ---------------------------------------------------------------------------
# 4. Refund Business Rule Tests
# ---------------------------------------------------------------------------

def test_refund_exceeds_total_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure refund > order total is detected as CRITICAL violation."""
    with open(fixtures_dir / "bad" / "bad_refund_rule_violation.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False
    total_findings = [f for f in result.findings if f.rule_violated == "refund_exceeds_order_total"]
    assert len(total_findings) == 1
    assert total_findings[0].severity == RiskTier.CRITICAL
    assert total_findings[0].step_index == 4
    assert "exceeds total invoice amount" in total_findings[0].detail


def test_refund_exceeds_refundable_amount_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure refund > refundable_amount is detected as CRITICAL violation."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    # Order has $120 total, but adjust refundable_amount in lookup result to $50
    trace_data["steps"][2]["output"]["refundable_amount"] = 50.00
    # Refund requested is $120
    trace_data["steps"][4]["input"]["amount"] = 120.00

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False
    refundable_findings = [f for f in result.findings if f.rule_violated == "refund_exceeds_refundable_amount"]
    assert len(refundable_findings) == 1
    assert refundable_findings[0].severity == RiskTier.CRITICAL
    assert "exceeds maximum available refundable amount" in refundable_findings[0].detail


def test_refund_not_eligible_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure attempting refund on ineligible order (e.g. status SHIPPED) is detected."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    trace_data["steps"][2]["output"]["refund_eligible"] = False
    trace_data["steps"][2]["output"]["status"] = "SHIPPED"

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False
    ineligible_findings = [f for f in result.findings if f.rule_violated == "refund_ineligible_order"]
    assert len(ineligible_findings) == 1
    assert ineligible_findings[0].severity == RiskTier.CRITICAL
    assert "ineligible for refund" in ineligible_findings[0].detail


def test_duplicate_refund_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure multiple refund tool calls for the same order in a trace are flagged as duplicate."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    # Append a duplicate refund step
    dup_step = {
        "index": 7,
        "type": "tool_call",
        "timestamp": "2026-09-27T16:10:08Z",
        "call_id": "call-v3",
        "tool_name": "refund_tool",
        "input": {"order_id": "ORD-1001", "amount": 120.0},
    }
    trace_data["steps"].append(dup_step)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False
    dup_findings = [f for f in result.findings if f.rule_violated == "duplicate_refund_attempt"]
    assert len(dup_findings) >= 1
    assert dup_findings[0].step_index == 7


def test_valid_refund_no_high_severity_violation(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Ensure completely valid refund trace produces 0 high/critical violations and passes."""
    with open(fixtures_dir / "valid_customer_refund.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is True
    assert result.violations_by_severity.get("HIGH", 0) == 0
    assert result.violations_by_severity.get("CRITICAL", 0) == 0


def test_validation_gate_bad_scope_fixture(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Validation Gate: Ensure fixtures/bad/bad_scope_violation.json is deterministically detected."""
    with open(fixtures_dir / "bad" / "bad_scope_violation.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False

    # Must identify the exact offending step 4 and rule 'tool_not_allowed'
    step4_violations = [f for f in result.findings if f.step_index == 4]
    assert len(step4_violations) >= 1
    assert step4_violations[0].rule_violated == "tool_not_allowed"
    assert step4_violations[0].tool_name == "web_search"
    assert "web_search is not permitted" in step4_violations[0].detail.lower() or "not permitted" in step4_violations[0].detail.lower()


def test_validation_gate_bad_refund_fixture(fixtures_dir: Path, customer_refund_policy: TaskPolicy, detector: ScopeDetector):
    """Validation Gate: Ensure fixtures/bad/bad_refund_rule_violation.json is deterministically detected."""
    with open(fixtures_dir / "bad" / "bad_refund_rule_violation.json", encoding="utf-8") as f:
        trace_data = json.load(f)

    result = detector.evaluate(trace_data, customer_refund_policy)
    assert result.passed is False

    # Must identify step 4 and rule 'refund_exceeds_order_total'
    step4_violations = [f for f in result.findings if f.step_index == 4]
    assert len(step4_violations) >= 1
    rules = [f.rule_violated for f in step4_violations]
    assert "refund_exceeds_order_total" in rules
    assert any("exceeds total invoice amount" in f.detail for f in step4_violations)

