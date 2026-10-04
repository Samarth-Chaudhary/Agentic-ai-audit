"""Unit tests for the 3D Trail Replay builder and HTML renderer."""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.api_client import DEMO_TRACES
from dashboard.trail_replay import build_replay_data, render_replay_html


def test_build_replay_data_basic_structure():
    """Verify build_replay_data returns all expected top-level keys."""
    sample = {
        "trace_id": "tr-test-001",
        "task_type": "customer_refund",
        "risk_score": 45.2,
        "risk_tier": "MEDIUM",
        "findings": {
            "scope": [],
            "pii": [],
            "groundedness": [],
        },
        "execution_timeline": [
            {"step_index": 0, "type": "USER_INPUT", "content": "Request a refund"},
            {"step_index": 1, "type": "TOOL_CALL", "tool_name": "order_lookup", "tool_input": {"id": 1}},
            {"step_index": 2, "type": "TOOL_RESULT", "tool_name": "order_lookup", "observation": "Delivered"},
            {"step_index": 3, "type": "FINAL_ANSWER", "content": "Refund processed."},
        ],
    }

    data = build_replay_data(sample)
    assert data["id"] == "tr-test-001"
    assert data["task"] == "customer_refund"
    assert data["bot"] in ("ledger", "scout")
    assert data["score"] == 45.2
    assert data["tier"] == "MEDIUM"
    assert isinstance(data["tools"], list)
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "order_lookup"
    assert data["tools"][0]["out"] is False

    assert isinstance(data["steps"], list)
    assert len(data["steps"]) == 3  # 0, 1, 2 (final is separated)
    assert data["steps"][0]["k"] == "say"
    assert data["steps"][1]["k"] == "call"
    assert data["steps"][2]["k"] == "res"

    assert "t" in data["final"]
    assert "f" in data["final"]
    assert data["final"]["t"] == "Refund processed."


def test_build_replay_data_scope_violations():
    """Verify tools with scope violations have out=True and findings attached."""
    sample = {
        "trace_id": "tr-viol-002",
        "task_type": "customer_support",
        "risk_score": 75.0,
        "risk_tier": "HIGH",
        "findings": {
            "scope": [
                {
                    "finding_id": "sc-01",
                    "step_index": 1,
                    "tool_name": "web_search",
                    "severity": "HIGH",
                    "detail": "Tool 'web_search' is not permitted.",
                }
            ],
            "pii": [],
            "groundedness": [],
        },
        "execution_timeline": [
            {"step_index": 0, "type": "USER_INPUT", "content": "Search for info"},
            {"step_index": 1, "type": "TOOL_CALL", "tool_name": "web_search", "tool_input": {"q": "info"}},
            {"step_index": 2, "type": "TOOL_RESULT", "tool_name": "web_search", "observation": "Found"},
            {"step_index": 3, "type": "FINAL_ANSWER", "content": "Done."},
        ],
    }

    data = build_replay_data(sample)
    tool_entry = next((t for t in data["tools"] if t["name"] == "web_search"), None)
    assert tool_entry is not None
    assert tool_entry["out"] is True

    # Step 1 should have scope finding
    call_step = data["steps"][1]
    assert len(call_step["f"]) == 1
    assert call_step["f"][0][0] == "scope"
    assert call_step["f"][0][1] == "HIGH"


def test_build_replay_data_pii_and_groundedness():
    """Verify PII and groundedness findings are mapped correctly."""
    sample = {
        "trace_id": "tr-pii-003",
        "task_type": "research_summary",
        "risk_score": 85.0,
        "risk_tier": "CRITICAL",
        "findings": {
            "scope": [],
            "pii": [
                {
                    "finding_id": "pi-01",
                    "step_index": 0,
                    "severity": "CRITICAL",
                    "pii_type": "US_SSN",
                    "redacted_snippet": "SSN <REDACTED>",
                }
            ],
            "groundedness": [
                {
                    "finding_id": "gr-01",
                    "claim": "Revenue tripled.",
                    "severity": "CRITICAL",
                    "audit_verdict": "CONTRADICTION",
                }
            ],
        },
        "execution_timeline": [
            {"step_index": 0, "type": "USER_INPUT", "content": "Check revenue"},
            {"step_index": 1, "type": "FINAL_ANSWER", "content": "Revenue tripled in Q3."},
        ],
    }

    data = build_replay_data(sample)
    # Check step 0 has PII
    assert len(data["steps"][0]["f"]) == 1
    assert data["steps"][0]["f"][0][0] == "pii"
    assert data["steps"][0]["f"][0][1] == "CRITICAL"

    # Check final has groundedness finding
    assert len(data["final"]["f"]) == 1
    assert data["final"]["f"][0][0] == "gnd"
    assert data["final"]["f"][0][1] == "CRITICAL"


def test_render_replay_html():
    """Verify render_replay_html generates valid HTML document without placeholders."""
    sample = DEMO_TRACES[0]
    html = render_replay_html(sample)
    assert "<!DOCTYPE html>" in html
    assert "__DATA__" not in html
    assert "const D=" in html

    # Verify JSON inside HTML is valid
    start = html.find("const D=") + len("const D=")
    end = html.find(";\nconst $", start)
    json_str = html[start:end]
    parsed = json.loads(json_str)
    assert parsed["id"] == sample["trace_id"]


def test_all_demo_traces_render_cleanly():
    """Verify all DEMO_TRACES build and render without raising exceptions."""
    for trace in DEMO_TRACES:
        html = render_replay_html(trace)
        assert len(html) > 1000
        assert trace["trace_id"] in html


def test_template_file_exists():
    """Verify dashboard/trail_replay.html exists and contains the __DATA__ placeholder."""
    path = Path(__file__).resolve().parent.parent / "dashboard" / "trail_replay.html"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "__DATA__" in content


def test_replay_html_controls():
    """Verify player controls and container elements exist in rendered replay HTML."""
    sample = DEMO_TRACES[0]
    html = render_replay_html(sample)
    assert 'id="play"' in html
    assert 'id="step"' in html
    assert 'id="restart"' in html
    assert 'id="spd"' in html
    assert 'id="scene"' in html
    assert 'id="floor"' in html
    assert 'id="log"' in html
    assert 'id="big"' in html
    assert 'id="tier"' in html
