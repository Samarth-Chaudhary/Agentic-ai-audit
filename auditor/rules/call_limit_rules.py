"""Modular rule for tool call volume limits and policy-based repetition auditing."""

from __future__ import annotations

import json

from auditor.models import RiskTier, ScopeFinding, StepType, Trace
from auditor.policy_loader import RiskConfig, TaskPolicy


def check_call_limits_and_repetition(
    trace: Trace,
    task_policy: TaskPolicy,
    risk_config: RiskConfig | None = None,
) -> list[ScopeFinding]:
    """Audit tool execution counts against task_policy.max_calls and configured repetition limits."""
    findings: list[ScopeFinding] = []
    max_calls = task_policy.max_calls

    severity = RiskTier.MEDIUM
    if risk_config and "scope" in risk_config.severity_mappings:
        scope_map = risk_config.severity_mappings["scope"]
        if "max_calls_exceeded" in scope_map:
            severity = RiskTier(scope_map["max_calls_exceeded"].upper())

    call_count = 0
    seen_calls: dict[str, list[int]] = {}

    for step in trace.steps:
        if step.type == StepType.TOOL_CALL and step.tool_name:
            call_count += 1

            # 1. Total call limit audit
            if call_count > max_calls:
                detail_msg = (
                    f"Tool call #{call_count} ('{step.tool_name}' at step {step.index}) exceeded "
                    f"the maximum declared call limit of {max_calls} for task '{trace.task_type}'."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name=step.tool_name,
                        rule_violated="max_calls_exceeded",
                        violation_type="max_calls_exceeded",
                        severity=severity,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )

            # 2. Policy-driven repetition detection
            # Only flag repeated tool use when explicitly bounded by business rules
            if "no_duplicate_refunds" in task_policy.business_rules and step.tool_name == "refund_tool":
                call_sig = f"{step.tool_name}:{json.dumps(step.input, sort_keys=True)}"
                if call_sig in seen_calls:
                    prior_step = seen_calls[call_sig][0]
                    detail_msg = (
                        f"Duplicate refund tool call detected at step {step.index}. "
                        f"Identical refund invocation was already executed at step {prior_step}."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name=step.tool_name,
                            rule_violated="duplicate_refund_attempt",
                            violation_type="rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )
                seen_calls.setdefault(call_sig, []).append(step.index)

    return findings
