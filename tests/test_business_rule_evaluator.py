"""Unit tests for the Decoupled Declarative Business Rule Engine."""


from auditor.models import RiskTier, StepType, Trace, TraceStep
from auditor.policy_loader import TaskPolicy
from auditor.rules.business_rule_evaluator import (
    BaseBusinessRule,
    BusinessRuleRegistry,
    DisallowManualCreditCardEntryRule,
    DisallowPaymentAuthorizationsRule,
    NoDestructiveDDLRule,
    NoDirectRefundsRule,
    ReadOnlyQueriesRule,
)


def _make_sample_trace(steps: list[dict], task_type: str = "customer_refund") -> Trace:
    return Trace(
        schema_version="1.0.0",
        trace_id="test-trace-rules-001",
        session_id="sess-001",
        task_type=task_type,
        started_at="2026-10-04T12:00:00Z",
        ended_at="2026-10-04T12:00:05Z",
        final_answer="The requested operation has concluded.",
        steps=[TraceStep.model_validate(s) for s in steps],
    )


def test_disallow_manual_credit_card_entry():
    """Ensure raw credit card number passing Luhn checksum in tool input is flagged."""
    rule = DisallowManualCreditCardEntryRule()
    policy = TaskPolicy(
        allowed_tools=["payment_gateway"],
        max_calls=5,
        business_rules=["disallow_manual_credit_card_entry"],
    )

    # Valid Visa card number that passes Luhn: 4532015112830366
    trace = _make_sample_trace([
        {
            "index": 1,
            "type": "tool_call",
            "tool_name": "payment_gateway",
            "timestamp": "2026-10-04T12:00:01Z",
            "input": {"account": "user123", "card_number": "4532-0151-1283-0366"},
        }
    ])

    findings = rule.evaluate(trace, policy)
    assert len(findings) == 1
    assert findings[0].rule_violated == "disallow_manual_credit_card_entry"
    assert findings[0].severity == RiskTier.CRITICAL
    assert "PCI-DSS" in findings[0].detail


def test_no_destructive_ddl_rule():
    """Ensure SQL commands containing DROP or TRUNCATE are flagged."""
    rule = NoDestructiveDDLRule()
    policy = TaskPolicy(
        allowed_tools=["execute_sql_query"],
        max_calls=5,
        business_rules=["no_destructive_ddl"],
    )

    trace = _make_sample_trace([
        {
            "index": 1,
            "type": "tool_call",
            "tool_name": "execute_sql_query",
            "timestamp": "2026-10-04T12:00:01Z",
            "input": {"query": "DROP TABLE customer_audit_log;"},
        }
    ], task_type="data_retrieval")

    findings = rule.evaluate(trace, policy)
    assert len(findings) == 1
    assert findings[0].rule_violated == "no_destructive_ddl"
    assert findings[0].severity == RiskTier.CRITICAL
    assert "DROP TABLE" in findings[0].detail


def test_read_only_queries_rule():
    """Ensure state-modifying SQL statements (INSERT/UPDATE/DELETE) are flagged."""
    rule = ReadOnlyQueriesRule()
    policy = TaskPolicy(
        allowed_tools=["execute_sql_query"],
        max_calls=5,
        business_rules=["read_only_queries"],
    )

    trace = _make_sample_trace([
        {
            "index": 1,
            "type": "tool_call",
            "tool_name": "execute_sql_query",
            "timestamp": "2026-10-04T12:00:01Z",
            "input": {"query": "UPDATE accounts SET balance = balance + 500 WHERE id = 12;"},
        }
    ], task_type="data_retrieval")

    findings = rule.evaluate(trace, policy)
    assert len(findings) == 1
    assert findings[0].rule_violated == "read_only_queries"
    assert findings[0].severity == RiskTier.HIGH


def test_no_direct_refunds_in_customer_support():
    """Ensure customer support tasks flag direct refund tool execution."""
    rule = NoDirectRefundsRule()
    policy = TaskPolicy(
        allowed_tools=["lookup_order_status", "create_support_ticket"],
        max_calls=5,
        business_rules=["no_direct_refunds"],
    )

    trace = _make_sample_trace([
        {
            "index": 1,
            "type": "tool_call",
            "tool_name": "refund_tool",
            "timestamp": "2026-10-04T12:00:01Z",
            "input": {"order_id": "ORD-999", "amount": 25.0},
        }
    ], task_type="customer_support")

    findings = rule.evaluate(trace, policy)
    assert len(findings) == 1
    assert findings[0].rule_violated == "no_direct_refunds"
    assert findings[0].severity == RiskTier.CRITICAL


def test_disallow_payment_authorizations():
    """Ensure advisory/financial reporting tasks flag payment transactions."""
    rule = DisallowPaymentAuthorizationsRule()
    policy = TaskPolicy(
        allowed_tools=["lookup_financial_metrics"],
        max_calls=5,
        business_rules=["disallow_payment_authorizations"],
    )

    trace = _make_sample_trace([
        {
            "index": 1,
            "type": "tool_call",
            "tool_name": "transfer_funds",
            "timestamp": "2026-10-04T12:00:01Z",
            "input": {"amount": 10000.0, "to_account": "ACC-789"},
        }
    ], task_type="financial_reporting")

    findings = rule.evaluate(trace, policy)
    assert len(findings) == 1
    assert findings[0].rule_violated == "disallow_payment_authorizations"


def test_custom_rule_registration():
    """Ensure dynamic registration of custom business rules works seamlessly."""
    class CustomDataResidencyRule(BaseBusinessRule):
        rule_id = "enforce_eu_data_residency"
        description = "Ensures data sources reside in EU regions"

        def evaluate(self, trace, task_policy, risk_config=None):
            from auditor.models import ScopeFinding
            findings = []
            for s in trace.steps:
                if s.type == StepType.TOOL_RESULT and isinstance(s.output, dict):
                    region = s.output.get("region", "")
                    if region and not region.startswith("eu-"):
                        findings.append(
                            ScopeFinding(
                                step_index=s.index,
                                tool_name=s.tool_name or "tool",
                                rule_violated="enforce_eu_data_residency",
                                violation_type="business_rule_violation",
                                severity=RiskTier.HIGH,
                                detail=f"Data from non-EU region '{region}' accessed",
                            )
                        )
            return findings

    registry = BusinessRuleRegistry()
    registry.register(CustomDataResidencyRule())

    policy = TaskPolicy(
        allowed_tools=["s3_store"],
        max_calls=5,
        business_rules=["enforce_eu_data_residency"],
    )

    trace = _make_sample_trace([
        {
            "index": 1,
            "type": "tool_result",
            "tool_name": "s3_store",
            "timestamp": "2026-10-04T12:00:01Z",
            "output": {"bucket": "corp-data", "region": "us-east-1"},
        }
    ])

    findings = registry.evaluate_rules(trace, policy)
    assert len(findings) == 1
    assert findings[0].rule_violated == "enforce_eu_data_residency"
    assert "us-east-1" in findings[0].detail
