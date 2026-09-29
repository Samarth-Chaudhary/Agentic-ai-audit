"""Regression tests for Groundedness Detector full-evidence search across trace tool results.

Ensures that claims substantiated by any tool result in a trace are correctly classified
as SUPPORTED, avoiding false positives caused by evaluating only the first or nearest
tool result by index or order. Also verifies that genuine hallucinations and contradictions
continue to be caught without suppression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auditor.groundedness_detector import GroundednessDetector
from auditor.models import RiskTier


@pytest.fixture
def detector() -> GroundednessDetector:
    return GroundednessDetector()


def test_clean_customer_refund_trace_no_false_positive(fixtures_dir: Path, detector: GroundednessDetector):
    """Regression test for known clean refund trace (fixtures/valid_customer_refund.json).

    Verifies that the clean refund trace produces ZERO UNSUPPORTED or CONTRADICTED claims
    and achieves a 100.0% groundedness score. The supporting evidence for the refund
    resides in Step 5 (refund_tool), NOT Step 2 (order_lookup).
    """
    refund_fixture_path = fixtures_dir / "valid_customer_refund.json"
    with open(refund_fixture_path, encoding="utf-8") as f:
        raw_trace = json.load(f)

    result = detector.evaluate(raw_trace)

    assert result.passed is True
    assert result.contradicted_claims == 0
    assert result.unsupported_claims == 0
    assert result.supported_claims == len(result.findings)
    assert result.groundedness_score == 100.0

    # Ensure no finding has elevated risk
    for finding in result.findings:
        assert finding.is_grounded is True
        assert finding.audit_verdict == "SUPPORTED"
        assert finding.severity == RiskTier.LOW

    # Verify that the refund claim was grounded in step 5 (refund_tool)
    refund_findings = [f for f in result.findings if "refund" in f.claim.lower()]
    assert len(refund_findings) >= 1
    assert refund_findings[0].evidence_step_index == 5
    assert refund_findings[0].tool_name == "refund_tool"


def test_grounded_evidence_in_downstream_tool_case_1(detector: GroundednessDetector):
    """Case 1: Multimodal e-commerce refund.

    Evidence is in Tool 4 (step 7, payment_gateway), not the nearest Tool 1 (step 1).
    """
    trace_data = {
        "trace_id": "tr-regression-multi-tool-1",
        "schema_version": "1.0.0",
        "task_type": "customer_support",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:10Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "order_lookup",
                "input": {"order_id": "ORD-5542"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "order_lookup",
                "output": {"order_id": "ORD-5542", "customer": "John Doe", "status": "DELIVERED"},
            },
            {
                "index": 2,
                "type": "tool_call",
                "tool_name": "inventory_status",
                "input": {"item_id": "ITEM-101"},
            },
            {
                "index": 3,
                "type": "tool_result",
                "tool_name": "inventory_status",
                "output": {"item_id": "ITEM-101", "in_stock": True, "warehouse": "West-1"},
            },
            {
                "index": 4,
                "type": "tool_call",
                "tool_name": "shipping_calculator",
                "input": {"origin": "94107", "dest": "10001"},
            },
            {
                "index": 5,
                "type": "tool_result",
                "tool_name": "shipping_calculator",
                "output": {"standard_cost": 15.0, "currency": "USD"},
            },
            {
                "index": 6,
                "type": "tool_call",
                "tool_name": "payment_gateway",
                "input": {"action": "refund", "amount": 85.50},
            },
            {
                "index": 7,
                "type": "tool_result",
                "tool_name": "payment_gateway",
                "output": {
                    "success": True,
                    "refunded_amount": 85.50,
                    "card_last4": "4022",
                    "auth_code": "AUTH-9921",
                },
            },
        ],
        "final_answer": "Your refund of $85.50 was returned to your card ending in 4022 with auth code AUTH-9921.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is True
    assert result.supported_claims == 1
    assert result.unsupported_claims == 0
    assert result.contradicted_claims == 0
    finding = result.findings[0]
    assert finding.is_grounded is True
    assert finding.evidence_step_index == 7
    assert finding.tool_name == "payment_gateway"


def test_grounded_evidence_in_downstream_tool_case_2(detector: GroundednessDetector):
    """Case 2: Flight rebooking.

    Evidence is in Tool 3 (step 5, flight_booker), preceded by weather and seat check.
    """
    trace_data = {
        "trace_id": "tr-regression-multi-tool-2",
        "schema_version": "1.0.0",
        "task_type": "flight_rebooking",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:08Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "airport_weather",
                "input": {"airport": "SFO"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "airport_weather",
                "output": {"airport": "SFO", "condition": "Rainy", "wind_mph": 12},
            },
            {
                "index": 2,
                "type": "tool_call",
                "tool_name": "seat_map",
                "input": {"flight": "UA-409"},
            },
            {
                "index": 3,
                "type": "tool_result",
                "tool_name": "seat_map",
                "output": {"flight": "UA-409", "available_seats": ["12B", "14A", "18C"]},
            },
            {
                "index": 4,
                "type": "tool_call",
                "tool_name": "flight_booker",
                "input": {"passenger": "Bob Smith", "seat": "12B"},
            },
            {
                "index": 5,
                "type": "tool_result",
                "tool_name": "flight_booker",
                "output": {
                    "confirmed": True,
                    "flight_number": "UA-409",
                    "assigned_seat": "12B",
                    "eticket_number": "ETK-88129",
                },
            },
        ],
        "final_answer": "You are confirmed in seat 12B on flight UA-409 with e-ticket ETK-88129.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is True
    assert result.supported_claims == 1
    assert result.unsupported_claims == 0
    finding = result.findings[0]
    assert finding.is_grounded is True
    assert finding.evidence_step_index == 5
    assert finding.tool_name == "flight_booker"


def test_grounded_evidence_in_downstream_tool_case_3(detector: GroundednessDetector):
    """Case 3: IT helpdesk ticket resolution.

    Evidence is in Tool 3 (step 5, ticket_resolver), preceded by user and LDAP checks.
    """
    trace_data = {
        "trace_id": "tr-regression-multi-tool-3",
        "schema_version": "1.0.0",
        "task_type": "it_support",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:06Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "user_directory",
                "input": {"username": "carol"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "user_directory",
                "output": {"username": "carol", "dept": "Engineering", "manager": "Dave"},
            },
            {
                "index": 2,
                "type": "tool_call",
                "tool_name": "ldap_groups",
                "input": {"username": "carol"},
            },
            {
                "index": 3,
                "type": "tool_result",
                "tool_name": "ldap_groups",
                "output": {"username": "carol", "groups": ["developers", "prod-deployers"]},
            },
            {
                "index": 4,
                "type": "tool_call",
                "tool_name": "ticket_resolver",
                "input": {"ticket_id": "INC-94812", "action": "resolve"},
            },
            {
                "index": 5,
                "type": "tool_result",
                "tool_name": "ticket_resolver",
                "output": {
                    "ticket_id": "INC-94812",
                    "status": "RESOLVED",
                    "resolution_notes": "Stale application cache cleared successfully.",
                },
            },
        ],
        "final_answer": "Incident INC-94812 has been resolved after clearing the stale cache.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is True
    assert result.supported_claims == 1
    finding = result.findings[0]
    assert finding.is_grounded is True
    assert finding.evidence_step_index == 5
    assert finding.tool_name == "ticket_resolver"


def test_grounded_evidence_in_downstream_tool_case_4(detector: GroundednessDetector):
    """Case 4: Banking dispute credit release.

    Evidence is in Tool 3 (step 5, dispute_credit_tool), preceded by KYC and statement queries.
    """
    trace_data = {
        "trace_id": "tr-regression-multi-tool-4",
        "schema_version": "1.0.0",
        "task_type": "dispute_handling",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:07Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "kyc_verification",
                "input": {"account_id": "ACC-7731"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "kyc_verification",
                "output": {"account_id": "ACC-7731", "verified": True, "tier": "Tier-2"},
            },
            {
                "index": 2,
                "type": "tool_call",
                "tool_name": "statement_query",
                "input": {"account_id": "ACC-7731", "days": 30},
            },
            {
                "index": 3,
                "type": "tool_result",
                "tool_name": "statement_query",
                "output": {"account_id": "ACC-7731", "transaction_count": 45},
            },
            {
                "index": 4,
                "type": "tool_call",
                "tool_name": "dispute_credit_tool",
                "input": {"account_id": "ACC-7731", "amount": 240.0},
            },
            {
                "index": 5,
                "type": "tool_result",
                "tool_name": "dispute_credit_tool",
                "output": {
                    "account_id": "ACC-7731",
                    "provisional_credit": 240.0,
                    "dispute_reference": "DISP-4401",
                    "status": "POSTED",
                },
            },
        ],
        "final_answer": "A provisional credit of $240.00 has been posted to account ACC-7731 under dispute reference DISP-4401.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is True
    assert result.supported_claims == 1
    finding = result.findings[0]
    assert finding.is_grounded is True
    assert finding.evidence_step_index == 5
    assert finding.tool_name == "dispute_credit_tool"


def test_grounded_evidence_in_downstream_tool_case_5(detector: GroundednessDetector):
    """Case 5: Cloud infrastructure autoscaling adjustment.

    Evidence is in Tool 3 (step 5, autoscale_controller), preceded by CPU and memory checks.
    """
    trace_data = {
        "trace_id": "tr-regression-multi-tool-5",
        "schema_version": "1.0.0",
        "task_type": "infrastructure_management",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:09Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "cpu_metrics",
                "input": {"cluster": "prod-west-2"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "cpu_metrics",
                "output": {"cluster": "prod-west-2", "cpu_avg_percent": 88.5},
            },
            {
                "index": 2,
                "type": "tool_call",
                "tool_name": "memory_metrics",
                "input": {"cluster": "prod-west-2"},
            },
            {
                "index": 3,
                "type": "tool_result",
                "tool_name": "memory_metrics",
                "output": {"cluster": "prod-west-2", "memory_used_gb": 64.0},
            },
            {
                "index": 4,
                "type": "tool_call",
                "tool_name": "autoscale_controller",
                "input": {"group": "asg-prod-west-2", "desired_capacity": 8},
            },
            {
                "index": 5,
                "type": "tool_result",
                "tool_name": "autoscale_controller",
                "output": {
                    "group_name": "asg-prod-west-2",
                    "new_capacity": 8,
                    "task_id": "task-7719",
                    "status": "SCALING_INITIATED",
                },
            },
        ],
        "final_answer": "Autoscale group asg-prod-west-2 capacity was increased to 8 instances with task ID task-7719.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is True
    assert result.supported_claims == 1
    finding = result.findings[0]
    assert finding.is_grounded is True
    assert finding.evidence_step_index == 5
    assert finding.tool_name == "autoscale_controller"


def test_real_hallucination_remains_unsupported(detector: GroundednessDetector):
    """Negative check: Unsubstantiated claims are NOT masked by full-evidence search."""
    trace_data = {
        "trace_id": "tr-regression-hallucination",
        "schema_version": "1.0.0",
        "task_type": "customer_support",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "order_lookup",
                "input": {"order_id": "ORD-101"},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "order_lookup",
                "output": {"order_id": "ORD-101", "total": 50.0},
            },
        ],
        "final_answer": "You have been credited an additional $500 VIP executive courtesy credit.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is False
    assert result.unsupported_claims == 1
    finding = result.findings[0]
    assert finding.is_grounded is False
    assert finding.audit_verdict == "UNSUPPORTED"
    assert finding.severity == RiskTier.HIGH


def test_real_numeric_contradiction_remains_critical(detector: GroundednessDetector):
    """Negative check: Contradicted numeric facts are flagged as CRITICAL."""
    trace_data = {
        "trace_id": "tr-regression-contradiction",
        "schema_version": "1.0.0",
        "task_type": "customer_refund",
        "started_at": "2026-09-27T10:00:00Z",
        "ended_at": "2026-09-27T10:00:05Z",
        "steps": [
            {
                "index": 0,
                "type": "tool_call",
                "tool_name": "refund_tool",
                "input": {"order_id": "ORD-101", "amount": 120.0},
            },
            {
                "index": 1,
                "type": "tool_result",
                "tool_name": "refund_tool",
                "output": {"order_id": "ORD-101", "refunded_amount": 120.0, "status": "COMPLETED"},
            },
        ],
        "final_answer": "Your refund of $999.00 was processed successfully.",
    }

    result = detector.evaluate(trace_data)
    assert result.passed is False
    assert result.contradicted_claims == 1
    finding = result.findings[0]
    assert finding.is_grounded is False
    assert finding.audit_verdict == "CONTRADICTED"
    assert finding.severity == RiskTier.CRITICAL
