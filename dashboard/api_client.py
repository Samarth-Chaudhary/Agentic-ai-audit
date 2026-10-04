"""API client for the Audit Explorer tab in the Streamlit Dashboard.

Interacts with the operational API Gateway / Read Lambdas (DynamoDB & S3):
- GET /traces (paginated summaries)
- GET /traces/{trace_id} (trace details with redacted execution timeline)

Supports seamless Local/Demo mode fallback when live AWS API Gateway is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Curated Demo Dataset for Offline / Reviewer Demonstrations
# -----------------------------------------------------------------------------
DEMO_TRACES: list[dict[str, Any]] = [
    {
        "trace_id": "tr-clean-001",
        "task_type": "customer_refund",
        "processed_at": "2026-09-27T10:15:00Z",
        "risk_score": 0.0,
        "risk_tier": "LOW",
        "pii_count": 0,
        "scope_violations": 0,
        "groundedness_failures": 0,
        "summary": "Trace passed audit with no policy violations detected (LOW risk).",
        "counts": {
            "total_steps": 3,
            "tool_calls": 1,
            "tool_results": 1,
            "errors": 0,
            "scope_violations": 0,
            "pii_entities_detected": 0,
            "unsupported_claims": 0,
        },
        "findings": {"scope": [], "pii": [], "groundedness": []},
        "execution_timeline": [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "What is the status of my order ORD-8819?",
            },
            {
                "step_index": 1,
                "type": "TOOL_CALL",
                "tool_name": "order_lookup",
                "tool_input": {"order_id": "ORD-8819"},
            },
            {
                "step_index": 2,
                "type": "TOOL_RESULT",
                "tool_name": "order_lookup",
                "observation": "Order ORD-8819 is DELIVERED to Austin, TX.",
            },
            {
                "step_index": 3,
                "type": "FINAL_ANSWER",
                "content": "Your order ORD-8819 has been delivered successfully.",
            },
        ],
    },
    {
        "trace_id": "tr-scope-002",
        "task_type": "customer_refund",
        "processed_at": "2026-09-27T11:30:00Z",
        "risk_score": 52.5,
        "risk_tier": "HIGH",
        "pii_count": 0,
        "scope_violations": 1,
        "groundedness_failures": 0,
        "summary": "Trace flagged HIGH due to unauthorized tool call 'web_search' for customer refund task.",
        "counts": {
            "total_steps": 4,
            "tool_calls": 2,
            "tool_results": 2,
            "errors": 0,
            "scope_violations": 1,
            "pii_entities_detected": 0,
            "unsupported_claims": 0,
        },
        "findings": {
            "scope": [
                {
                    "finding_id": "sc-001",
                    "tool_name": "web_search",
                    "rule_violated": "ALLOWED_TOOLS_RULE",
                    "severity": "HIGH",
                    "step_index": 1,
                    "detail": "Tool 'web_search' is not permitted for task 'customer_refund'. Allowed: order_lookup, refund_tool, calculator.",
                }
            ],
            "pii": [],
            "groundedness": [],
        },
        "execution_timeline": [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "Where is the nearest customer service center?",
            },
            {
                "step_index": 1,
                "type": "TOOL_CALL",
                "tool_name": "web_search",
                "tool_input": {"query": "customer support office address"},
            },
            {
                "step_index": 2,
                "type": "TOOL_RESULT",
                "tool_name": "web_search",
                "observation": "Found 3 offices in downtown district.",
            },
            {
                "step_index": 3,
                "type": "FINAL_ANSWER",
                "content": "There are three service centers located in the downtown district.",
            },
        ],
    },
    {
        "trace_id": "tr-pii-003",
        "task_type": "customer_refund",
        "processed_at": "2026-09-27T12:45:00Z",
        "risk_score": 85.0,
        "risk_tier": "CRITICAL",
        "pii_count": 2,
        "scope_violations": 0,
        "groundedness_failures": 0,
        "summary": "Trace flagged CRITICAL due to unredacted sensitive PII (Social Security Number and Payment Card).",
        "counts": {
            "total_steps": 3,
            "tool_calls": 1,
            "tool_results": 1,
            "errors": 0,
            "scope_violations": 0,
            "pii_entities_detected": 2,
            "unsupported_claims": 0,
        },
        "findings": {
            "scope": [],
            "pii": [
                {
                    "finding_id": "pii-001",
                    "step_index": 0,
                    "field_path": "steps[0].content",
                    "pii_type": "US_SSN",
                    "severity": "CRITICAL",
                    "redacted_snippet": "SSN <REDACTED_SSN>",
                    "confidence_score": 0.95,
                },
                {
                    "finding_id": "pii-002",
                    "step_index": 2,
                    "field_path": "steps[2].observation",
                    "pii_type": "CREDIT_CARD",
                    "severity": "CRITICAL",
                    "redacted_snippet": "Card ending in <REDACTED_CC>",
                    "confidence_score": 0.99,
                },
            ],
            "groundedness": [],
        },
        "execution_timeline": [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "Please verify my account with SSN <REDACTED_SSN>.",
            },
            {
                "step_index": 1,
                "type": "TOOL_CALL",
                "tool_name": "order_lookup",
                "tool_input": {"order_id": "ORD-1001"},
            },
            {
                "step_index": 2,
                "type": "TOOL_RESULT",
                "tool_name": "order_lookup",
                "observation": "Account found. Payment billing card: <REDACTED_CC>.",
            },
            {
                "step_index": 3,
                "type": "FINAL_ANSWER",
                "content": "Your account has been verified successfully.",
            },
        ],
    },
    {
        "trace_id": "tr-ground-004",
        "task_type": "research_summary",
        "processed_at": "2026-09-27T14:10:00Z",
        "risk_score": 65.0,
        "risk_tier": "HIGH",
        "pii_count": 0,
        "scope_violations": 0,
        "groundedness_failures": 2,
        "summary": "Trace flagged HIGH due to contradictory claim regarding revenue growth and unsupported margin estimate.",
        "counts": {
            "total_steps": 3,
            "tool_calls": 1,
            "tool_results": 1,
            "errors": 0,
            "scope_violations": 0,
            "pii_entities_detected": 0,
            "unsupported_claims": 1,
        },
        "findings": {
            "scope": [],
            "pii": [],
            "groundedness": [
                {
                    "finding_id": "gr-001",
                    "claim": "Revenue increased by 15% in Q3.",
                    "evidence_snippet": "Q3 Revenue dropped by 4.2% year-over-year.",
                    "evidence_step_index": 1,
                    "similarity": 0.88,
                    "nli_verdict": "CONTRADICTION",
                    "audit_verdict": "CONTRADICTED",
                    "severity": "CRITICAL",
                },
                {
                    "finding_id": "gr-002",
                    "claim": "Operating margin reached a record high of 28%.",
                    "evidence_snippet": "Operating margin was reported at 16.4%.",
                    "evidence_step_index": 1,
                    "similarity": 0.65,
                    "nli_verdict": "NEUTRAL",
                    "audit_verdict": "UNSUPPORTED",
                    "severity": "HIGH",
                },
            ],
        },
        "execution_timeline": [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "Summarize Q3 financial results for Acme Corp.",
            },
            {
                "step_index": 1,
                "type": "TOOL_CALL",
                "tool_name": "sec_edgar_research",
                "tool_input": {"ticker": "AAPL", "form": "10-Q"},
            },
            {
                "step_index": 2,
                "type": "TOOL_RESULT",
                "tool_name": "sec_edgar_research",
                "observation": "SEC 10-Q Filing: Q3 Revenue dropped by 4.2% year-over-year. Operating margin reported at 16.4%.",
            },
            {
                "step_index": 3,
                "type": "FINAL_ANSWER",
                "content": "Revenue increased by 15% in Q3. Operating margin reached a record high of 28%.",
            },
        ],
    },
    {
        "trace_id": "tr-multi-005",
        "task_type": "research_summary",
        "processed_at": "2026-09-27T15:20:00Z",
        "risk_score": 92.5,
        "risk_tier": "CRITICAL",
        "pii_count": 1,
        "scope_violations": 1,
        "groundedness_failures": 1,
        "summary": "Trace flagged CRITICAL with simultaneous unauthorized tool call, leaked API credentials, and fabricated guidance statement.",
        "counts": {
            "total_steps": 4,
            "tool_calls": 2,
            "tool_results": 2,
            "errors": 0,
            "scope_violations": 1,
            "pii_entities_detected": 1,
            "unsupported_claims": 1,
        },
        "findings": {
            "scope": [
                {
                    "finding_id": "sc-002",
                    "tool_name": "refund_tool",
                    "rule_violated": "ALLOWED_TOOLS_RULE",
                    "severity": "CRITICAL",
                    "step_index": 1,
                    "detail": "Tool 'refund_tool' is not permitted for task 'research_summary'.",
                }
            ],
            "pii": [
                {
                    "finding_id": "pii-003",
                    "step_index": 1,
                    "field_path": "steps[1].tool_input",
                    "pii_type": "API_KEY",
                    "severity": "CRITICAL",
                    "redacted_snippet": "api_key: <REDACTED_SECRET>",
                    "confidence_score": 0.99,
                }
            ],
            "groundedness": [
                {
                    "finding_id": "gr-003",
                    "claim": "Management guided forward revenue to exceed $500M next quarter.",
                    "evidence_snippet": "Guidance was withheld pending regulatory review.",
                    "evidence_step_index": 3,
                    "similarity": 0.79,
                    "nli_verdict": "CONTRADICTION",
                    "audit_verdict": "CONTRADICTED",
                    "severity": "CRITICAL",
                }
            ],
        },
        "execution_timeline": [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "Run report extraction for quarterly metrics and forward outlook.",
            },
            {
                "step_index": 1,
                "type": "TOOL_CALL",
                "tool_name": "refund_tool",
                "tool_input": {"order_id": "ORD-999", "amount": 100.0},
            },
            {
                "step_index": 2,
                "type": "TOOL_RESULT",
                "tool_name": "refund_tool",
                "observation": "Error: refund_tool not permitted in research context.",
            },
            {
                "step_index": 3,
                "type": "FINAL_ANSWER",
                "content": "Quarterly export complete. Management guided forward revenue to exceed $500M next quarter.",
            },
        ],
    },
    {
        "trace_id": "tr-degraded-006",
        "task_type": "customer_refund",
        "processed_at": "2026-09-27T16:00:00Z",
        "risk_score": 15.0,
        "risk_tier": "LOW",
        "status": "DEGRADED",
        "is_degraded": True,
        "degraded_reasons": [
            "NLI cross-encoder unavailable: torch.cuda.OutOfMemoryError",
            "Presidio NLP unavailable: spacy model 'en_core_web_sm' not installed",
        ],
        "engine_info": {
            "nli_engine": "heuristic-negation-overlap-v1",
            "embedding_engine": "sentence-transformers/all-MiniLM-L6-v2",
            "pii_engine": "regex-only-fallback",
            "is_degraded": True,
            "degraded_reasons": [
                "NLI cross-encoder unavailable: torch.cuda.OutOfMemoryError",
                "Presidio NLP unavailable: spacy model 'en_core_web_sm' not installed",
            ],
        },
        "pii_count": 0,
        "scope_violations": 0,
        "groundedness_failures": 0,
        "summary": "Trace evaluated in degraded mode using heuristic fallback engines due to unavailable ML dependencies.",
        "counts": {
            "total_steps": 2,
            "tool_calls": 1,
            "tool_results": 1,
            "errors": 0,
            "scope_violations": 0,
            "pii_entities_detected": 0,
            "unsupported_claims": 0,
        },
        "findings": {"scope": [], "pii": [], "groundedness": []},
        "execution_timeline": [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "Check refund status for RF-991.",
            },
            {
                "step_index": 1,
                "type": "TOOL_CALL",
                "tool_name": "refund_tool",
                "tool_input": {"order_id": "ORD-991"},
            },
            {
                "step_index": 2,
                "type": "TOOL_RESULT",
                "tool_name": "refund_tool",
                "observation": "Refund RF-991 processed successfully.",
            },
            {
                "step_index": 3,
                "type": "FINAL_ANSWER",
                "content": "Your refund RF-991 was processed successfully.",
            },
        ],
    },
]


def load_local_generated_traces() -> list[dict[str, Any]]:
    """Scan data/generated_traces and fixtures/ for local traces and convert to demo format."""
    from pathlib import Path
    traces: list[dict[str, Any]] = []
    root = Path(__file__).resolve().parent.parent
    paths = list(root.glob("data/generated_traces/**/*.json")) + list(root.glob("fixtures/valid_*.json"))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "trace_id" not in data or "steps" not in data:
                continue
            trace_id = data["trace_id"]
            if any(t["trace_id"] == trace_id for t in DEMO_TRACES) or any(t["trace_id"] == trace_id for t in traces):
                continue
            task_type = data.get("task_type", "custom")
            steps = data.get("steps", [])
            timeline: list[dict[str, Any]] = []
            for s in steps:
                if s.get("thought"):
                    timeline.append({"step_index": len(timeline), "type": "THOUGHT", "content": s["thought"]})
                if s.get("tool_name"):
                    timeline.append({"step_index": len(timeline), "type": "TOOL_CALL", "tool_name": s["tool_name"], "tool_input": s.get("tool_input", {})})
                if s.get("output"):
                    timeline.append({"step_index": len(timeline), "type": "TOOL_RESULT", "tool_name": s.get("tool_name", ""), "observation": str(s["output"])})
            if data.get("final_answer"):
                timeline.append({"step_index": len(timeline), "type": "FINAL_ANSWER", "content": data["final_answer"]})

            traces.append({
                "trace_id": trace_id,
                "task_type": task_type,
                "processed_at": data.get("started_at") or data.get("timestamp") or "2026-09-28T10:00:00Z",
                "risk_score": 10.0,
                "risk_tier": "LOW",
                "pii_count": 0,
                "scope_violations": 0,
                "groundedness_failures": 0,
                "summary": f"Locally generated agent trace for {task_type} ({len(steps)} steps).",
                "counts": {
                    "total_steps": len(timeline),
                    "tool_calls": sum(1 for s in steps if s.get("tool_name")),
                    "tool_results": sum(1 for s in steps if s.get("output")),
                    "errors": 0,
                    "scope_violations": 0,
                    "pii_entities_detected": 0,
                    "unsupported_claims": 0,
                },
                "findings": {"scope": [], "pii": [], "groundedness": []},
                "execution_timeline": timeline,
            })
        except Exception:
            continue
    return traces


class AuditApiClient:
    """Client for querying operational audit records from API Gateway or Demo fixtures."""

    def __init__(
        self,
        base_url: str | None = None,
        demo_mode: bool = False,
    ) -> None:
        """Initialize API client.

        Args:
            base_url: API Gateway base URL (e.g. 'https://abc123.execute-api.us-east-1.amazonaws.com/dev').
            demo_mode: If True, uses local demonstration fixtures instead of network calls.
        """
        raw_url = (base_url or os.environ.get("API_GATEWAY_URL", "")).strip().rstrip("/")
        if raw_url.endswith("/traces"):
            raw_url = raw_url[:-7].rstrip("/")
        self.base_url = raw_url

        # Auto-enable demo mode only if explicitly requested or if no API URL configured
        if demo_mode or not self.base_url:
            self.demo_mode = True
        else:
            self.demo_mode = False

    def _get_all_demo_traces(self) -> list[dict[str, Any]]:
        return DEMO_TRACES + load_local_generated_traces()

    def list_traces(
        self,
        task_type: str | None = None,
        risk_tier: str | None = None,
        date_filter: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve trace summary records with optional filters.

        Args:
            task_type: Optional task_type filter.
            risk_tier: Optional risk_tier filter.
            date_filter: Optional date string filter (YYYY-MM-DD).
            limit: Maximum items to return.

        Returns:
            List of summary record dictionaries.
        """
        if self.demo_mode:
            items = []
            for t in DEMO_TRACES:
                if task_type and t.get("task_type") != task_type:
                    continue
                if risk_tier and t.get("risk_tier") != risk_tier:
                    continue
                if date_filter and not t.get("processed_at", "").startswith(date_filter):
                    continue
                counts = t.get("counts", {})
                items.append({
                    "trace_id": t["trace_id"],
                    "task_type": t["task_type"],
                    "risk_score": t["risk_score"],
                    "risk_tier": t["risk_tier"],
                    "processed_at": t["processed_at"],
                    "is_degraded": bool(t.get("is_degraded", False)),
                    "engine_info": t.get("engine_info"),
                    "pii_count": counts.get("pii_entities_detected", 0),
                    "scope_violation_count": counts.get("scope_violations", 0),
                    "groundedness_failure_count": counts.get("unsupported_claims", 0),
                    "summary": t.get("summary", ""),
                })
            return items[:limit]

        # Live Mode via HTTP GET /traces
        url = f"{self.base_url}/traces?limit={limit}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])

            # Client-side filtering if API returns unfiltered list
            filtered = []
            for item in items:
                if task_type and item.get("task_type") != task_type:
                    continue
                if risk_tier and item.get("risk_tier") != risk_tier:
                    continue
                if date_filter and not str(item.get("processed_at", "")).startswith(date_filter):
                    continue
                filtered.append(item)
            return filtered
        except Exception as exc:
            logger.error("Failed to fetch traces from %s: %s", url, exc)
            raise ConnectionError(f"API Gateway unreachable at {self.base_url}: {exc}") from exc

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        """Retrieve full trace audit details including redacted execution timeline.

        Args:
            trace_id: Correlated trace ID.

        Returns:
            Detailed trace audit dictionary.

        Raises:
            KeyError: If trace is not found.
            ConnectionError: If API Gateway call fails.
        """
        if self.demo_mode:
            for t in DEMO_TRACES:
                if t["trace_id"] == trace_id:
                    return t
            raise KeyError(f"Trace '{trace_id}' not found in demo dataset")

        # Live Mode via HTTP GET /traces/{trace_id}
        url = f"{self.base_url}/traces/{trace_id}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Normalize risk attributes if returned in nested shape from Lambda
                if "risk" in data and isinstance(data["risk"], dict):
                    if "risk_score" not in data and "risk_score" in data["risk"]:
                        data["risk_score"] = data["risk"]["risk_score"]
                    if "risk_tier" not in data and "risk_tier" in data["risk"]:
                        data["risk_tier"] = data["risk"]["risk_tier"]
                elif "risk_score" in data and "risk" not in data:
                    data["risk"] = {
                        "risk_score": data.get("risk_score", 0.0),
                        "risk_tier": data.get("risk_tier", "LOW"),
                    }
                return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise KeyError(f"Trace '{trace_id}' not found on server") from exc
            raise ConnectionError(f"API error ({exc.code}): {exc.reason}") from exc
        except Exception as exc:
            raise ConnectionError(f"API Gateway unreachable at {self.base_url}: {exc}") from exc

    def get_summary_metrics(self) -> dict[str, int]:
        """Compute aggregate summary metrics across all known traces."""
        traces = self.list_traces(limit=500)
        total = len(traces)
        high = sum(1 for t in traces if t.get("risk_tier") == "HIGH")
        critical = sum(1 for t in traces if t.get("risk_tier") == "CRITICAL")
        scope = sum(t.get("scope_violation_count", 0) for t in traces)
        pii = sum(t.get("pii_count", 0) for t in traces)
        grounded = sum(t.get("groundedness_failure_count", 0) for t in traces)

        return {
            "total_traces": total,
            "high_risk_traces": high,
            "critical_risk_traces": critical,
            "scope_violations": scope,
            "pii_findings": pii,
            "groundedness_failures": grounded,
        }
