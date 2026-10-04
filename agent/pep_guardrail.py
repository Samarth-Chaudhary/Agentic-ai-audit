"""Synchronous Inline Policy Enforcement Point (PEP) for Autonomous AI Agents.

Implements runtime preventative guardrails (NIST SP 800-207 Zero Trust Architecture).
Intercepts tool calls *before* backend invocation, evaluates parameter safety,
enforces tool allowlists, verifies prerequisites, and blocks policy violations.
"""

from __future__ import annotations

import re
from typing import Any

from auditor.models import RiskTier
from auditor.policy_loader import TaskPolicy
from auditor.redaction import REGEX_PATTERNS
from project.logging import get_logger

logger = get_logger(__name__, component="pep_guardrail")


class PolicyViolationError(Exception):
    """Raised when an agent's proposed action violates a runtime preventative policy."""

    def __init__(
        self,
        message: str,
        rule_violated: str,
        severity: RiskTier = RiskTier.HIGH,
        tool_name: str | None = None,
        blocked_parameter: str | None = None,
    ) -> None:
        super().__init__(message)
        self.rule_violated = rule_violated
        self.severity = severity
        self.tool_name = tool_name
        self.blocked_parameter = blocked_parameter


# Dangerous SQL injection patterns
SQL_INJECTION_PATTERN = re.compile(
    r"(?:;\s*(?:DROP|DELETE|TRUNCATE|ALTER|UPDATE|INSERT|GRANT|REVOKE)\b)|"
    r"(?:\bUNION\s+(?:ALL\s+)?SELECT\b)|"
    r"(?:--\s*$)|"
    r"(?:/\*.*?\*/)|"
    r"(?:'\s*OR\s+'?\d+'?\s*=\s*'?\d+)",
    re.IGNORECASE,
)

# Dangerous shell command injection patterns
SHELL_INJECTION_PATTERN = re.compile(
    r"[;&|`$]|\b(?:rm\s+-rf|curl\s+|wget\s+|chmod\s+|bash\s+|sh\s+)\b",
    re.IGNORECASE,
)

EXTERNAL_TOOLS = {"web_search", "external_api", "unauthorized_bash"}


class PolicyEnforcementPoint:
    """Synchronous runtime interceptor enforcing preventative governance controls."""

    def __init__(
        self,
        policy: TaskPolicy,
        tool_call_limits: dict[str, int] | None = None,
    ) -> None:
        self.policy = policy
        self.tool_call_limits = tool_call_limits or getattr(policy, "tool_call_limits", None) or {}
        self.tool_call_counts: dict[str, int] = {}
        self.executed_tools: list[tuple[str, dict[str, Any]]] = []

    def reset(self) -> None:
        """Reset session state counters."""
        self.tool_call_counts.clear()
        self.executed_tools.clear()

    def intercept_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | Any,
    ) -> None:
        """Evaluate a proposed tool invocation before execution.

        Raises PolicyViolationError immediately if any policy constraint is violated.
        """
        # 1. Preventative Tool Allowlist Enforcement
        task_name = getattr(self.policy, "task_type", "task")
        if tool_name not in self.policy.allowed_tools:
            msg = f"Security block: Tool '{tool_name}' is not authorized for task '{task_name}'."
            logger.warning(msg)
            raise PolicyViolationError(
                message=msg,
                rule_violated="unauthorized_tool_invocation",
                severity=RiskTier.CRITICAL,
                tool_name=tool_name,
            )

        # 2. Preventative Call Limit Enforcement
        current_calls = self.tool_call_counts.get(tool_name, 0)
        max_allowed = self.tool_call_limits.get(tool_name, getattr(self.policy, "max_calls", 10))
        total_calls = sum(self.tool_call_counts.values())
        max_total = getattr(self.policy, "max_calls", 10)

        if current_calls >= max_allowed or total_calls >= max_total:
            msg = (
                f"Rate limit block: Tool '{tool_name}' has exceeded its execution limit "
                f"({current_calls}/{max_allowed}, total {total_calls}/{max_total}) for task '{task_name}'."
            )
            logger.warning(msg)
            raise PolicyViolationError(
                message=msg,
                rule_violated="tool_call_limit_exceeded",
                severity=RiskTier.HIGH,
                tool_name=tool_name,
            )

        # 3. Preventative Parameter Security Checks (SQL Injection, Shell Escapes)
        if isinstance(tool_input, dict):
            self._scan_parameters(tool_name, tool_input)

        # 4. Preventative Business Precondition Verification (e.g. refund requires prior lookup)
        if tool_name == "refund_tool":
            has_prior_lookup = any(t[0] == "order_lookup" for t in self.executed_tools)
            if not has_prior_lookup:
                msg = "Business rule block: 'refund_tool' cannot be executed without prior 'order_lookup' verification."
                raise PolicyViolationError(
                    message=msg,
                    rule_violated="missing_prerequisite_lookup",
                    severity=RiskTier.HIGH,
                    tool_name=tool_name,
                )

        # 5. Preventative DLP: Block secrets/credentials from being sent to external tools
        if tool_name in EXTERNAL_TOOLS and isinstance(tool_input, dict):
            self._scan_exfiltration(tool_name, tool_input)

    def record_successful_execution(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | Any,
    ) -> None:
        """Record successful execution of tool to track invocation history."""
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1
        safe_input = tool_input if isinstance(tool_input, dict) else {"raw": str(tool_input)}
        self.executed_tools.append((tool_name, safe_input))

    def _scan_parameters(self, tool_name: str, params: dict[str, Any]) -> None:
        """Scan string parameters for injection attempts (SQL, shell command)."""
        for param_name, param_value in params.items():
            if isinstance(param_value, str):
                # SQL injection detection
                if SQL_INJECTION_PATTERN.search(param_value):
                    msg = (
                        f"Security block: SQL injection payload detected in argument '{param_name}' "
                        f"for tool '{tool_name}' ('{param_value}')."
                    )
                    raise PolicyViolationError(
                        message=msg,
                        rule_violated="sql_injection_detected",
                        severity=RiskTier.CRITICAL,
                        tool_name=tool_name,
                        blocked_parameter=param_name,
                    )

                # Shell command injection detection
                if SHELL_INJECTION_PATTERN.search(param_value) and any(
                    k in param_name.lower() for k in ("cmd", "exec", "query", "id", "file", "path")
                ):
                    msg = (
                        f"Security block: Command injection characters detected in argument '{param_name}' "
                        f"for tool '{tool_name}'."
                    )
                    raise PolicyViolationError(
                        message=msg,
                        rule_violated="command_injection_detected",
                        severity=RiskTier.CRITICAL,
                        tool_name=tool_name,
                        blocked_parameter=param_name,
                    )

    def _scan_exfiltration(self, tool_name: str, params: dict[str, Any]) -> None:
        """Check for PII and high-entropy credentials destined for external endpoints."""
        for param_name, param_value in params.items():
            text = str(param_value)
            if REGEX_PATTERNS["AWS_ACCESS_KEY"].search(text) or REGEX_PATTERNS["API_KEY"].search(text):
                msg = f"DLP block: High-entropy secret detected in outbound '{tool_name}' parameter '{param_name}'."
                raise PolicyViolationError(
                    message=msg,
                    rule_violated="credential_exfiltration_blocked",
                    severity=RiskTier.CRITICAL,
                    tool_name=tool_name,
                    blocked_parameter=param_name,
                )
