"""Tests for dashboard demo data consistency with the real pipeline (Task 6).

Verifies:
1. Every tool name in dashboard demo data exists in the active agent tool registry.
2. Every task type in dashboard demo data matches task governance policies.
3. Every demo trace and audit record validates against the canonical JSON schemas.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from agent.tools import get_default_tools
from dashboard.api_client import DEMO_TRACES
from dashboard.athena_client import DEMO_ANALYTICS

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def audit_result_schema() -> dict:
    schema_path = REPO_ROOT / "schemas" / "audit_result.schema.json"
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def valid_task_types() -> set[str]:
    policies_path = REPO_ROOT / "config" / "task_policies.yaml"
    with open(policies_path, encoding="utf-8") as f:
        policies = yaml.safe_load(f)
    return set(policies.get("policies", {}).keys())


@pytest.fixture
def registered_tool_names() -> set[str]:
    return set(get_default_tools().keys())


def test_demo_traces_tool_names_match_registry(registered_tool_names: set[str]):
    """Verify tool names appearing in demo traces strictly match real tool registry."""
    assert len(DEMO_TRACES) > 0, "DEMO_TRACES must not be empty"

    for trace in DEMO_TRACES:
        timeline = trace.get("execution_timeline", [])
        for step in timeline:
            if step.get("type") in ("TOOL_CALL", "TOOL_RESULT"):
                tool_name = step.get("tool_name")
                assert tool_name is not None, f"Tool step missing tool_name in trace {trace.get('trace_id')}"
                assert tool_name in registered_tool_names, (
                    f"Tool '{tool_name}' in demo trace {trace.get('trace_id')} "
                    f"does not exist in active tool registry: {registered_tool_names}"
                )


def test_demo_traces_task_types_match_policies(valid_task_types: set[str]):
    """Verify task types in demo traces match configured task policies."""
    for trace in DEMO_TRACES:
        task_type = trace.get("task_type")
        assert task_type in valid_task_types, (
            f"Task type '{task_type}' in demo trace {trace.get('trace_id')} "
            f"not found in task_policies.yaml: {valid_task_types}"
        )


def test_demo_analytics_tool_names_match_registry(registered_tool_names: set[str]):
    """Verify tool names in Athena demo charts match real tool registry."""
    tool_violations = DEMO_ANALYTICS.get("10_tool_violation_analysis", [])
    assert len(tool_violations) > 0

    for item in tool_violations:
        tool_name = item.get("tool_name")
        assert tool_name in registered_tool_names, (
            f"Tool '{tool_name}' in Athena demo analytics does not exist in tool registry: {registered_tool_names}"
        )


def test_demo_traces_schema_validation(audit_result_schema: dict):
    """Verify every demo trace structure conforms to the AuditResult JSON schema."""
    for trace in DEMO_TRACES:
        status_val = "DEGRADED" if trace.get("is_degraded") else ("FLAGGED" if trace.get("risk_tier") in ("HIGH", "CRITICAL") else "COMPLETED")
        trace_record = {
            "trace_id": trace["trace_id"],
            "task_type": trace["task_type"],
            "processed_at": trace["processed_at"],
            "risk_score": float(trace["risk_score"]),
            "risk_tier": trace["risk_tier"],
            "summary": trace["summary"],
            "status": status_val,
            "counts": trace["counts"],
            "raw_trace_storage_pointer": {
                "s3_bucket": "agent-audit-raw-traces",
                "s3_key": f"traces/{trace['trace_id']}.json",
                "s3_uri": f"s3://agent-audit-raw-traces/traces/{trace['trace_id']}.json",
            },
            "scope_findings": [
                {
                    "finding_id": f.get("finding_id", "sc-001"),
                    "rule_violated": f.get("rule_violated", "ALLOWED_TOOLS_RULE"),
                    "tool_name": f.get("tool_name", "order_lookup"),
                    "severity": f.get("severity", "HIGH"),
                    "detail": f.get("detail", "Scope violation detected"),
                    "step_index": f.get("step_index", 1),
                }
                for f in trace.get("findings", {}).get("scope", [])
            ],
            "pii_findings": [
                {
                    "finding_id": f.get("finding_id", "pii-001"),
                    "entity_type": f.get("pii_type", "US_SSN"),
                    "severity": f.get("severity", "CRITICAL"),
                    "step_index": f.get("step_index", 0),
                    "field_path": f.get("field_path", "steps[0].content"),
                    "confidence_score": float(f.get("confidence_score", 0.95)),
                    "redacted_snippet": f.get("redacted_snippet", "[REDACTED]"),
                }
                for f in trace.get("findings", {}).get("pii", [])
            ],
            "groundedness_findings": [
                {
                    "finding_id": f.get("finding_id", "gr-001"),
                    "claim": f.get("claim", ""),
                    "audit_verdict": f.get("audit_verdict", "UNSUPPORTED"),
                    "nli_verdict": f.get("nli_verdict", "NEUTRAL"),
                    "severity": f.get("severity", "HIGH"),
                    "evidence_snippet": f.get("evidence_snippet", ""),
                    "similarity": float(f.get("similarity", 0.7)),
                }
                for f in trace.get("findings", {}).get("groundedness", [])
            ],
        }
        jsonschema.validate(instance=trace_record, schema=audit_result_schema)
