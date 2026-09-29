"""Modular rule for independent audit of refund business rules.

Independently validates:
- refund amount <= order total
- refund amount <= refundable amount
- refund only if eligible
- refund not already completed
- no duplicate refund executions
Does not rely on the refund tool's internal checks; cross-examines trace evidence.
"""

from __future__ import annotations

from typing import Any

from auditor.models import RiskTier, ScopeFinding, StepType, Trace
from auditor.policy_loader import RiskConfig, TaskPolicy


def check_refund_business_rules(
    trace: Trace,
    task_policy: TaskPolicy,
    risk_config: RiskConfig | None = None,
) -> list[ScopeFinding]:
    """Independently audit refund steps against ground-truth order data extracted from the trace."""
    findings: list[ScopeFinding] = []

    # 1. Harvest ground-truth order lookup records from the trace
    observed_orders: dict[str, dict[str, Any]] = {}
    for step in trace.steps:
        if step.type == StepType.TOOL_RESULT and step.tool_name == "order_lookup":
            if isinstance(step.output, dict) and step.output.get("found"):
                oid = str(step.output.get("order_id", "")).strip().upper()
                if oid:
                    observed_orders[oid] = step.output

    # 2. Inspect refund tool calls
    seen_refund_orders: dict[str, list[int]] = {}

    for step in trace.steps:
        if step.type == StepType.TOOL_CALL and step.tool_name == "refund_tool":
            raw_input = step.input if isinstance(step.input, dict) else {}
            order_id = str(raw_input.get("order_id", "")).strip().upper()
            amount_val = raw_input.get("amount")

            try:
                refund_amount = float(amount_val) if amount_val is not None else 0.0
            except (ValueError, TypeError):
                refund_amount = 0.0

            # Rule: Prior order verification check
            if order_id not in observed_orders:
                detail_msg = (
                    f"Refund tool was invoked for order '{order_id}' at step {step.index} "
                    "without prior order verification via order_lookup."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name="refund_tool",
                        rule_violated="missing_order_lookup_before_refund",
                        violation_type="rule_violation",
                        severity=RiskTier.HIGH,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )
            else:
                order_data = observed_orders[order_id]
                order_total = float(order_data.get("order_total", 0.0))
                refundable_amount = float(order_data.get("refundable_amount", 0.0))
                refund_eligible = bool(order_data.get("refund_eligible", False))
                already_refunded = bool(order_data.get("already_refunded", False))
                status = order_data.get("status", "UNKNOWN")

                # Rule: Refund amount <= order total
                if refund_amount > order_total:
                    detail_msg = (
                        f"Refund amount ${refund_amount:.2f} at step {step.index} exceeds "
                        f"total invoice amount ${order_total:.2f} for order '{order_id}'."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name="refund_tool",
                            rule_violated="refund_exceeds_order_total",
                            violation_type="rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

                # Rule: Refund amount <= refundable amount
                if refund_amount > refundable_amount:
                    detail_msg = (
                        f"Refund amount ${refund_amount:.2f} at step {step.index} exceeds "
                        f"maximum available refundable amount ${refundable_amount:.2f} for order '{order_id}'."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name="refund_tool",
                            rule_violated="refund_exceeds_refundable_amount",
                            violation_type="rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

                # Rule: Refund only if eligible
                if not refund_eligible:
                    detail_msg = (
                        f"Refund attempted on order '{order_id}' at step {step.index}, but order is "
                        f"ineligible for refund (status: '{status}')."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name="refund_tool",
                            rule_violated="refund_ineligible_order",
                            violation_type="rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

                # Rule: Refund not already completed
                if already_refunded:
                    detail_msg = (
                        f"Refund attempted on order '{order_id}' at step {step.index}, but order records "
                        "indicate that a refund has already been completed."
                    )
                    findings.append(
                        ScopeFinding(
                            step_index=step.index,
                            tool_name="refund_tool",
                            rule_violated="already_refunded_order",
                            violation_type="rule_violation",
                            severity=RiskTier.CRITICAL,
                            detail=detail_msg,
                            details=detail_msg,
                        )
                    )

            # Rule: Duplicate refund tool calls for same order in single trace
            if order_id in seen_refund_orders:
                prev_steps = seen_refund_orders[order_id]
                detail_msg = (
                    f"Duplicate refund attempted for order '{order_id}' at step {step.index}. "
                    f"Prior refund call occurred at step {prev_steps[0]}."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name="refund_tool",
                        rule_violated="duplicate_refund_attempt",
                        violation_type="rule_violation",
                        severity=RiskTier.CRITICAL,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )

            seen_refund_orders.setdefault(order_id, []).append(step.index)

    return findings
