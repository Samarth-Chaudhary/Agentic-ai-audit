"""Decoupled Declarative Business Rule Engine for AI Agent Governance.

Provides a pluggable, extensible architecture for task-specific business invariants,
ensuring domain constraints (e.g. refund bounds, SQL safety, payment boundaries, PCI-DSS)
are audited independently of tool logic.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from auditor.luhn import is_luhn_valid, normalize_card_number
from auditor.models import RiskTier, ScopeFinding, StepType, Trace
from auditor.policy_loader import RiskConfig, TaskPolicy
from auditor.rules.refund_rules import check_refund_business_rules
from project.logging import get_logger

logger = get_logger(__name__, component="business_rule_evaluator")


class BaseBusinessRule(ABC):
    """Abstract base class for all declarative business invariant rules."""

    rule_id: str
    description: str

    @abstractmethod
    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        """Evaluate the rule against the trace and return any findings."""
        raise NotImplementedError


class RefundLifecycleRule(BaseBusinessRule):
    """Audits customer refund invariants (order lookup, amounts, eligibility, idempotency)."""

    rule_id = "refund_lifecycle_checks"
    description = "Enforces order verification, non-negative amounts, refund ceilings, and idempotency"

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        return check_refund_business_rules(trace, task_policy, risk_config)


class DisallowManualCreditCardEntryRule(BaseBusinessRule):
    """Enforces PCI-DSS invariant: disallow manual raw payment card numbers in tool inputs."""

    rule_id = "disallow_manual_credit_card_entry"
    description = "Detects raw credit card Primary Account Numbers (PAN) in agent tool invocations"

    # Regex candidate matching potential card numbers (13-19 digits, optional dashes/spaces)
    _CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        findings: list[ScopeFinding] = []

        for step in trace.steps:
            if step.type == StepType.TOOL_CALL and isinstance(step.input, dict):
                input_str = str(step.input)
                candidates = self._CARD_PATTERN.findall(input_str)
                for cand in candidates:
                    norm = normalize_card_number(cand)
                    if is_luhn_valid(norm):
                        detail_msg = (
                            f"Manual credit card PAN entry detected in tool '{step.tool_name}' "
                            f"input at step {step.index} (ending in {norm[-4:]}). "
                            "Direct card entry violates PCI-DSS tokenization invariants."
                        )
                        findings.append(
                            ScopeFinding(
                                step_index=step.index,
                                tool_name=step.tool_name or "unknown_tool",
                                rule_violated="disallow_manual_credit_card_entry",
                                violation_type="business_rule_violation",
                                severity=RiskTier.CRITICAL,
                                detail=detail_msg,
                                details=detail_msg,
                            )
                        )
                        break  # One finding per step is sufficient

        return findings


class NoDestructiveDDLRule(BaseBusinessRule):
    """Audits SQL operations to ensure no destructive DDL commands are executed."""

    rule_id = "no_destructive_ddl"
    description = "Flags destructive DDL statements (DROP, TRUNCATE, ALTER TABLE) in SQL tool calls"

    _DDL_PATTERN = re.compile(
        r"\b(DROP\s+(TABLE|DATABASE|SCHEMA|VIEW)|TRUNCATE\s+TABLE|ALTER\s+TABLE)\b",
        re.IGNORECASE,
    )

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        findings: list[ScopeFinding] = []

        for step in trace.steps:
            if step.type == StepType.TOOL_CALL:
                raw_input = step.input if isinstance(step.input, dict) else {}
                query = str(raw_input.get("query", raw_input.get("sql", "")))
                match = self._DDL_PATTERN.search(query)
                if match:
                    ddl_command = match.group(0).upper()
                    detail_msg = (
                        f"Destructive DDL command '{ddl_command}' detected at step {step.index} "
                        f"in tool '{step.tool_name}'. Policy strictly prohibits schema destruction."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name=step.tool_name or "execute_sql_query",
                            rule_violated="no_destructive_ddl",
                            violation_type="business_rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

        return findings


class ReadOnlyQueriesRule(BaseBusinessRule):
    """Audits SQL queries to enforce read-only semantics (no INSERT, UPDATE, DELETE)."""

    rule_id = "read_only_queries"
    description = "Enforces read-only query semantics in analytics and retrieval tasks"

    _WRITE_PATTERN = re.compile(
        r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b",
        re.IGNORECASE,
    )

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        findings: list[ScopeFinding] = []

        for step in trace.steps:
            if step.type == StepType.TOOL_CALL:
                raw_input = step.input if isinstance(step.input, dict) else {}
                query = str(raw_input.get("query", raw_input.get("sql", "")))
                match = self._WRITE_PATTERN.search(query)
                if match:
                    write_command = match.group(0).upper()
                    detail_msg = (
                        f"State-modifying SQL command '{write_command}' detected at step {step.index} "
                        f"in tool '{step.tool_name}'. Policy enforces read-only query operations."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name=step.tool_name or "execute_sql_query",
                            rule_violated="read_only_queries",
                            violation_type="business_rule_violation",
                            severity=RiskTier.HIGH,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

        return findings


class NoDirectRefundsRule(BaseBusinessRule):
    """Audits non-refund tasks to ensure direct refund tools are not executed."""

    rule_id = "no_direct_refunds"
    description = "Disallows direct refund tool execution for non-refund tasks (e.g. customer support)"

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        findings: list[ScopeFinding] = []

        for step in trace.steps:
            if step.type == StepType.TOOL_CALL and step.tool_name == "refund_tool":
                detail_msg = (
                    f"Direct refund execution via 'refund_tool' attempted at step {step.index}. "
                    f"Task '{trace.task_type}' requires ticket escalation and forbids direct refund processing."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name="refund_tool",
                        rule_violated="no_direct_refunds",
                        violation_type="business_rule_violation",
                        severity=RiskTier.CRITICAL,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )

        return findings


class DisallowPaymentAuthorizationsRule(BaseBusinessRule):
    """Audits financial analysis tasks to ensure payment authorization tools are not called."""

    rule_id = "disallow_payment_authorizations"
    description = "Prevents payment authorization or fund transfers in advisory/reporting workflows"

    _PAYMENT_TOOLS = {"authorize_payment", "transfer_funds", "wire_transfer", "execute_payment"}

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        findings: list[ScopeFinding] = []

        for step in trace.steps:
            if step.type == StepType.TOOL_CALL and step.tool_name in self._PAYMENT_TOOLS:
                detail_msg = (
                    f"Payment authorization tool '{step.tool_name}' invoked at step {step.index}. "
                    f"Task '{trace.task_type}' is strictly analytical and disallows transaction authorization."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name=step.tool_name,
                        rule_violated="disallow_payment_authorizations",
                        violation_type="business_rule_violation",
                        severity=RiskTier.CRITICAL,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )

        return findings


class DisallowCredentialModificationsRule(BaseBusinessRule):
    """Audits support/retrieval tasks to prevent password, token, or credential modifications."""

    rule_id = "disallow_credential_modifications"
    description = "Disallows credential, password, or security token modification operations"

    _CREDENTIAL_KEYWORDS = {"reset_password", "change_password", "rotate_api_key", "update_credentials"}

    def evaluate(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        findings: list[ScopeFinding] = []

        for step in trace.steps:
            if step.type == StepType.TOOL_CALL:
                tool_name_lower = (step.tool_name or "").lower()
                raw_input = step.input if isinstance(step.input, dict) else {}
                input_keys = [str(k).lower() for k in raw_input.keys()]

                if (
                    tool_name_lower in self._CREDENTIAL_KEYWORDS
                    or any(k in ("password", "credential", "api_key", "secret") for k in input_keys)
                ):
                    detail_msg = (
                        f"Credential modification attempt detected in tool '{step.tool_name}' at step {step.index}. "
                        "Policy forbids autonomous credential updates without secondary MFA authorization."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name=step.tool_name or "unknown_tool",
                            rule_violated="disallow_credential_modifications",
                            violation_type="business_rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

        return findings


class BusinessRuleRegistry:
    """Central registry and dispatch engine for task-specific business invariants."""

    def __init__(self) -> None:
        self._rules: dict[str, BaseBusinessRule] = {}
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        # Standard rules
        rules = [
            RefundLifecycleRule(),
            DisallowManualCreditCardEntryRule(),
            NoDestructiveDDLRule(),
            ReadOnlyQueriesRule(),
            NoDirectRefundsRule(),
            DisallowPaymentAuthorizationsRule(),
            DisallowCredentialModificationsRule(),
        ]
        for r in rules:
            self.register(r)

    def register(self, rule: BaseBusinessRule) -> None:
        """Register a new business rule evaluator."""
        self._rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> BaseBusinessRule | None:
        """Retrieve a registered rule evaluator by ID."""
        return self._rules.get(rule_id)

    def evaluate_rules(
        self,
        trace: Trace,
        task_policy: TaskPolicy,
        risk_config: RiskConfig | None = None,
    ) -> list[ScopeFinding]:
        """Dispatch and evaluate all applicable business rules for the given task policy."""
        findings: list[ScopeFinding] = []
        executed_rules: set[str] = set()

        policy_rules = task_policy.business_rules or []

        # 1. Refund lifecycle special handling for customer_refund task or refund rules
        refund_related_rules = {
            "require_order_lookup_before_refund",
            "verify_refund_eligibility",
            "refund_amount_must_not_exceed_order_total",
        }
        has_refund_policy = any(r in refund_related_rules for r in policy_rules)
        has_refund_steps = any(
            s.type == StepType.TOOL_CALL and s.tool_name == "refund_tool"
            for s in trace.steps
        )

        if (has_refund_policy or has_refund_steps or trace.task_type == "customer_refund") and "refund_lifecycle_checks" not in executed_rules:
            rule_impl = self._rules.get("refund_lifecycle_checks")
            if rule_impl:
                findings.extend(rule_impl.evaluate(trace, task_policy, risk_config))
                executed_rules.add("refund_lifecycle_checks")

        # 2. Evaluate rules declared in policy.business_rules
        for rule_name in policy_rules:
            if rule_name in refund_related_rules:
                continue  # Handled above by RefundLifecycleRule
            rule_impl = self._rules.get(rule_name)
            if rule_impl and rule_impl.rule_id not in executed_rules:
                findings.extend(rule_impl.evaluate(trace, task_policy, risk_config))
                executed_rules.add(rule_impl.rule_id)

        return findings


# Singleton registry instance
default_business_rule_registry = BusinessRuleRegistry()


def evaluate_business_rules(
    trace: Trace,
    task_policy: TaskPolicy,
    risk_config: RiskConfig | None = None,
    registry: BusinessRuleRegistry | None = None,
) -> list[ScopeFinding]:
    """Convenience function to evaluate business rules using the global or custom registry."""
    reg = registry or default_business_rule_registry
    return reg.evaluate_rules(trace, task_policy, risk_config)
