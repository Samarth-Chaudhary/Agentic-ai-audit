"""Modular rule for tool permissions and data source scope verification.

Evaluates whether any tool invocation or accessed data source violates
the declared TaskPolicy.
"""

from __future__ import annotations

from auditor.models import RiskTier, ScopeFinding, StepType, Trace
from auditor.policy_loader import RiskConfig, TaskPolicy


def check_tool_permissions_and_data_sources(
    trace: Trace,
    task_policy: TaskPolicy,
    risk_config: RiskConfig | None = None,
) -> list[ScopeFinding]:
    """Inspect trace steps for unauthorized tools or forbidden data sources."""
    findings: list[ScopeFinding] = []
    allowed_tools = set(task_policy.allowed_tools)
    allowed_sources = set(task_policy.allowed_data_sources)

    # Determine severity mappings from risk config if available
    tool_severity = RiskTier.HIGH
    source_severity = RiskTier.HIGH
    if risk_config and "scope" in risk_config.severity_mappings:
        scope_map = risk_config.severity_mappings["scope"]
        if "unauthorized_tool" in scope_map:
            tool_severity = RiskTier(scope_map["unauthorized_tool"].upper())
        if "unauthorized_data_source" in scope_map:
            source_severity = RiskTier(scope_map["unauthorized_data_source"].upper())

    for step in trace.steps:
        # 1. Tool permission check on tool_call steps
        if step.type == StepType.TOOL_CALL and step.tool_name:
            if step.tool_name not in allowed_tools:
                detail_msg = (
                    f"Tool '{step.tool_name}' is not permitted for task_type '{trace.task_type}'. "
                    f"Declared permitted tools: {sorted(allowed_tools)}."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name=step.tool_name,
                        rule_violated="tool_not_allowed",
                        violation_type="unauthorized_tool",
                        severity=tool_severity,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )

        # 2. Data source verification on tool_call or tool_result payloads
        data_source_candidate: str | None = None
        tool_name = step.tool_name or "unknown"

        # Check in step details
        if step.details and isinstance(step.details, dict) and "data_source" in step.details:
            data_source_candidate = str(step.details["data_source"])

        # Check in input payload
        if step.input and isinstance(step.input, dict) and "data_source" in step.input:
            data_source_candidate = str(step.input["data_source"])

        # Check in output payload
        if step.output and isinstance(step.output, dict):
            if "data_source" in step.output:
                data_source_candidate = str(step.output["data_source"])
            elif "source_type" in step.output:
                data_source_candidate = str(step.output["source_type"])

        if data_source_candidate and allowed_sources:
            if data_source_candidate not in allowed_sources:
                detail_msg = (
                    f"Data source '{data_source_candidate}' accessed at step {step.index} "
                    f"is not permitted for task_type '{trace.task_type}'. "
                    f"Declared permitted data sources: {sorted(allowed_sources)}."
                )
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name=tool_name,
                        rule_violated="unauthorized_data_source",
                        violation_type="unauthorized_data_source",
                        severity=source_severity,
                        detail=detail_msg,
                        details=detail_msg,
                    )
                )

        # 3. Policy Business Rules (no_destructive_ddl, read_only_queries, no_direct_refunds, disallow_payment_authorizations)
        if step.type == StepType.TOOL_CALL:
            business_rules = set(task_policy.business_rules)
            if "no_destructive_ddl" in business_rules or "read_only_queries" in business_rules:
                if step.tool_name == "execute_sql_query" and isinstance(step.input, dict):
                    q = str(step.input.get("query", "")).upper()
                    if "no_destructive_ddl" in business_rules and any(kw in q for kw in ["DROP ", "TRUNCATE ", "ALTER "]):
                        findings.append(
                            ScopeFinding(
                                step_index=step.index,
                                tool_name=step.tool_name,
                                rule_violated="no_destructive_ddl",
                                violation_type="policy_violation",
                                severity=RiskTier.CRITICAL,
                                detail=f"Destructive DDL detected in query at step {step.index}: {step.input.get('query')}",
                            )
                        )
                    elif "read_only_queries" in business_rules and any(kw in q for kw in ["INSERT ", "UPDATE ", "DELETE "]):
                        findings.append(
                            ScopeFinding(
                                step_index=step.index,
                                tool_name=step.tool_name,
                                rule_violated="read_only_queries",
                                violation_type="policy_violation",
                                severity=RiskTier.HIGH,
                                detail=f"Write query detected in read-only policy at step {step.index}: {step.input.get('query')}",
                            )
                        )
            if "no_direct_refunds" in business_rules and step.tool_name in ("refund_tool", "issue_refund"):
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name=step.tool_name,
                        rule_violated="no_direct_refunds",
                        violation_type="policy_violation",
                        severity=RiskTier.HIGH,
                        detail=f"Direct refund tool '{step.tool_name}' invoked under policy prohibiting direct refunds.",
                    )
                )
            if "disallow_payment_authorizations" in business_rules and step.tool_name in ("authorize_payment", "execute_payment"):
                findings.append(
                    ScopeFinding(
                        step_index=step.index,
                        tool_name=step.tool_name,
                        rule_violated="disallow_payment_authorizations",
                        violation_type="policy_violation",
                        severity=RiskTier.CRITICAL,
                        detail=f"Payment authorization tool '{step.tool_name}' invoked under policy prohibiting payments.",
                    )
                )

    return findings
