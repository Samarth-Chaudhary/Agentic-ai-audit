"""Unit tests for the synchronous Policy Enforcement Point (PEP) runtime guardrail."""

import pytest

from agent.pep_guardrail import PolicyEnforcementPoint, PolicyViolationError
from auditor.policy_loader import TaskPolicy


@pytest.fixture
def sample_policy():
    return TaskPolicy(
        description="Customer refund governance policy",
        allowed_tools=["order_lookup", "refund_tool", "web_search"],
        allowed_data_sources=["order_db"],
        max_calls=5,
        business_rules=["require_order_lookup_before_refund"],
    )


def test_pep_allows_authorized_tool(sample_policy):
    pep = PolicyEnforcementPoint(sample_policy)
    # Should not raise
    pep.intercept_tool_call("order_lookup", {"order_id": "ord-101"})
    pep.record_successful_execution("order_lookup", {"order_id": "ord-101"})


def test_pep_blocks_unauthorized_tool(sample_policy):
    pep = PolicyEnforcementPoint(sample_policy)
    with pytest.raises(PolicyViolationError) as exc_info:
        pep.intercept_tool_call("database_cli", {"query": "SELECT * FROM users"})
    assert "Tool 'database_cli' is not authorized" in str(exc_info.value)
    assert exc_info.value.rule_violated == "unauthorized_tool_invocation"


def test_pep_blocks_rate_limit_exceeded(sample_policy):
    pep = PolicyEnforcementPoint(sample_policy, tool_call_limits={"order_lookup": 2})
    # First execution allowed
    pep.intercept_tool_call("order_lookup", {"order_id": "ord-101"})
    pep.record_successful_execution("order_lookup", {"order_id": "ord-101"})

    # Second execution allowed (limit is 2)
    pep.intercept_tool_call("order_lookup", {"order_id": "ord-102"})
    pep.record_successful_execution("order_lookup", {"order_id": "ord-102"})

    # Third execution blocked
    with pytest.raises(PolicyViolationError) as exc_info:
        pep.intercept_tool_call("order_lookup", {"order_id": "ord-103"})
    assert "exceeded its execution limit" in str(exc_info.value)
    assert exc_info.value.rule_violated == "tool_call_limit_exceeded"


def test_pep_blocks_sql_injection(sample_policy):
    pep = PolicyEnforcementPoint(sample_policy)
    with pytest.raises(PolicyViolationError) as exc_info:
        pep.intercept_tool_call("order_lookup", {"order_id": "101; DROP TABLE orders;--"})
    assert "SQL injection payload detected" in str(exc_info.value)
    assert exc_info.value.rule_violated == "sql_injection_detected"


def test_pep_blocks_missing_prerequisite(sample_policy):
    pep = PolicyEnforcementPoint(sample_policy)
    # Attempting refund without prior order_lookup
    with pytest.raises(PolicyViolationError) as exc_info:
        pep.intercept_tool_call("refund_tool", {"order_id": "ord-101", "amount": 25.0})
    assert "cannot be executed without prior 'order_lookup'" in str(exc_info.value)
    assert exc_info.value.rule_violated == "missing_prerequisite_lookup"


def test_pep_blocks_credential_exfiltration(sample_policy):
    pep = PolicyEnforcementPoint(sample_policy)
    # Attempting to send OpenAI API key to web_search
    with pytest.raises(PolicyViolationError) as exc_info:
        pep.intercept_tool_call("web_search", {"query": "Check balance for sk-proj-1234567890abcdef1234567890"})
    assert "High-entropy secret detected" in str(exc_info.value)
    assert exc_info.value.rule_violated == "credential_exfiltration_blocked"
