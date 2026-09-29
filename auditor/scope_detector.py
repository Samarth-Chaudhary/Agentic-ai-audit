"""Main Scope & Business-Rule Detector for AI Agent Governance.

Orchestrates modular rules to audit tool permissions, data-source boundaries,
call frequency limits, and task-specific business logic.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from auditor.models import ScopeFinding, Trace
from auditor.policy_loader import PolicyLoader, RiskConfig, TaskPolicy
from auditor.rules.call_limit_rules import check_call_limits_and_repetition
from auditor.rules.refund_rules import check_refund_business_rules
from auditor.rules.tool_permission_rules import check_tool_permissions_and_data_sources
from project.logging import get_logger

logger = get_logger(__name__, component="scope_detector")


class ScopeAuditResult(BaseModel):
    """Structured audit result evaluating an agent trace against its task scope policy."""
    trace_id: str = Field(description="Audited trace identifier")
    task_type: str = Field(description="Task classification")
    passed: bool = Field(description="True if zero scope or business-rule violations occurred")
    findings: list[ScopeFinding] = Field(default_factory=list, description="List of scope violations detected")
    total_violations: int = Field(default=0, ge=0, description="Total count of findings")
    violations_by_severity: dict[str, int] = Field(default_factory=dict, description="Counts grouped by severity")
    summary: str = Field(description="Summary narrative explaining the scope audit outcome")


class ScopeDetector:
    """Evaluates agent execution traces against declarative task governance policies."""

    def __init__(self, risk_config: RiskConfig | None = None) -> None:
        self.risk_config: RiskConfig | None
        if risk_config is None:
            try:
                loader = PolicyLoader()
                self.risk_config = loader.get_risk_config()
            except Exception:
                self.risk_config = None
        else:
            self.risk_config = risk_config

    def evaluate(
        self,
        trace: Trace | dict[str, Any],
        task_policy: TaskPolicy,
    ) -> ScopeAuditResult:
        """Run modular scope audit rules against the validated trace.

        Consumes policy configuration dynamically; no hardcoded tool rules.
        """
        trace_obj = Trace.model_validate(trace) if isinstance(trace, dict) else trace
        findings: list[ScopeFinding] = []

        logger.info_event(
            event="scope_audit_start",
            status="evaluating",
            message=f"Starting scope evaluation for trace {trace_obj.trace_id} ({trace_obj.task_type})",
            trace_id=trace_obj.trace_id,
            task_type=trace_obj.task_type,
        )

        # 1. Modular Rule: Tool Permissions & Data Sources
        tool_findings = check_tool_permissions_and_data_sources(
            trace=trace_obj,
            task_policy=task_policy,
            risk_config=self.risk_config,
        )
        findings.extend(tool_findings)

        # 2. Modular Rule: Call Limits & Repetition
        call_limit_findings = check_call_limits_and_repetition(
            trace=trace_obj,
            task_policy=task_policy,
            risk_config=self.risk_config,
        )
        findings.extend(call_limit_findings)

        # 3. Modular Rule: Refund Business Rules
        refund_findings = check_refund_business_rules(
            trace=trace_obj,
            task_policy=task_policy,
            risk_config=self.risk_config,
        )
        findings.extend(refund_findings)

        # Aggregate counts by severity
        severity_counts: dict[str, int] = {
            "LOW": 0,
            "MEDIUM": 0,
            "HIGH": 0,
            "CRITICAL": 0,
        }
        for f in findings:
            sev_key = f.severity.value if hasattr(f.severity, "value") else str(f.severity).upper()
            severity_counts[sev_key] = severity_counts.get(sev_key, 0) + 1

        total = len(findings)
        passed = (total == 0)

        if passed:
            summary = (
                f"Scope audit PASSED for trace {trace_obj.trace_id}. "
                f"Execution strictly complied with declared policy for '{trace_obj.task_type}'."
            )
        else:
            summary = (
                f"Scope audit FAILED for trace {trace_obj.trace_id}: {total} violation(s) detected "
                f"(CRITICAL: {severity_counts.get('CRITICAL', 0)}, "
                f"HIGH: {severity_counts.get('HIGH', 0)}, "
                f"MEDIUM: {severity_counts.get('MEDIUM', 0)}, "
                f"LOW: {severity_counts.get('LOW', 0)})."
            )

        logger.info_event(
            event="scope_audit_complete",
            status="passed" if passed else "flagged",
            message=summary,
            trace_id=trace_obj.trace_id,
            task_type=trace_obj.task_type,
            extra_data={"total_violations": total, "severities": severity_counts},
        )

        for f in findings:
            if not f.engine:
                f.engine = "policy:task-scope-rules-v1"

        return ScopeAuditResult(
            trace_id=trace_obj.trace_id,
            task_type=trace_obj.task_type,
            passed=passed,
            findings=findings,
            total_violations=total,
            violations_by_severity=severity_counts,
            summary=summary,
        )
