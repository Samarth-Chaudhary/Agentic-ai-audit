"""3D Agent Trail Replay Data Builder and HTML Renderer.

Transforms audit trace details into the structured payload consumed by
dashboard/trail_replay.html.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_replay_data(detail: dict[str, Any]) -> dict[str, Any]:
    """Transform an audit trace detail dict into the 3D trail replay data schema.

    Schema specification for D:
      - id: str
      - task: str
      - bot: 'ledger' | 'scout'
      - score: float
      - tier: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
      - tools: list[{"name": str, "out": bool}]
      - steps: list[{"k": "say"|"call"|"res", "tool": str|None, "b": str, "t": str, "f": list[list]}]
      - final: {"t": str, "f": list[list]}
    """
    trace_id = str(detail.get("trace_id") or "tr-unknown")
    task_type = str(detail.get("task_type") or "customer_support")
    risk_score = float(detail.get("risk_score", 0.0) if detail.get("risk_score") is not None else 0.0)
    risk_tier = str(detail.get("risk_tier") or "LOW").upper()

    # Determine robot avatar: ledger for finance/refund/support, scout for research/scraping
    bot_type = "ledger" if any(w in task_type.lower() for w in ("refund", "finance", "support", "ledger", "order")) else "scout"

    findings = detail.get("findings") or {}
    scope_findings = findings.get("scope") or []
    pii_findings = findings.get("pii") or []
    groundedness_findings = findings.get("groundedness") or []

    # Map scope violations by tool name and step index
    tools_out_of_policy: set[str] = {
        str(f.get("tool_name") or f.get("tool"))
        for f in scope_findings
        if f.get("tool_name") or f.get("tool")
    }

    scope_by_step: dict[int, list[list[str]]] = {}
    for f in scope_findings:
        step_idx = f.get("step_index")
        if step_idx is not None:
            sev = str(f.get("severity", "HIGH")).upper()
            detail_msg = str(f.get("detail") or f.get("explanation") or f.get("rule_violated") or "Scope violation")
            scope_by_step.setdefault(int(step_idx), []).append(["scope", sev, detail_msg])

    pii_by_step: dict[int, list[list[str]]] = {}
    for f in pii_findings:
        step_idx = f.get("step_index")
        if step_idx is not None:
            sev = str(f.get("severity", "CRITICAL")).upper()
            ptype = str(f.get("pii_type") or f.get("type") or "Sensitive data")
            snip = str(f.get("redacted_snippet") or f.get("field_path") or "Detected")
            pii_by_step.setdefault(int(step_idx), []).append(["pii", sev, f"{ptype}: {snip}"])

    ground_by_step: dict[int, list[list[str]]] = {}
    ground_for_final: list[list[str]] = []
    for f in groundedness_findings:
        sev = str(f.get("severity", "HIGH")).upper()
        verdict = str(f.get("audit_verdict") or f.get("nli_verdict") or "UNGROUNDED")
        claim = str(f.get("claim") or "")
        entry = ["gnd", sev, f"{verdict}: {claim}"]
        ground_for_final.append(entry)

        ev_idx = f.get("evidence_step_index") if f.get("evidence_step_index") is not None else f.get("evidence_step")
        if ev_idx is not None:
            ground_by_step.setdefault(int(ev_idx), []).append(entry)

    timeline = detail.get("execution_timeline") or []
    if not timeline and "steps" in detail:
        # Synthesize timeline from raw steps if execution_timeline absent
        raw_steps = detail.get("steps") or []
        timeline = []
        if detail.get("prompt"):
            timeline.append({"step_index": 0, "type": "USER_INPUT", "content": detail["prompt"]})
        for s in raw_steps:
            if s.get("thought"):
                timeline.append({"step_index": len(timeline), "type": "THOUGHT", "content": s["thought"]})
            if s.get("tool_name"):
                timeline.append({"step_index": len(timeline), "type": "TOOL_CALL", "tool_name": s["tool_name"], "tool_input": s.get("tool_input", {})})
            if s.get("output") is not None:
                timeline.append({"step_index": len(timeline), "type": "TOOL_RESULT", "tool_name": s.get("tool_name"), "observation": str(s["output"])})
        if detail.get("final_answer"):
            timeline.append({"step_index": len(timeline), "type": "FINAL_ANSWER", "content": detail["final_answer"]})

    # Collect tool inventory
    discovered_tools: dict[str, bool] = {}
    for stp in timeline:
        raw_tool_name = stp.get("tool_name")
        if raw_tool_name:
            tname = str(raw_tool_name)
            if tname not in discovered_tools:
                discovered_tools[tname] = (tname in tools_out_of_policy)
    for raw_policy_tool in tools_out_of_policy:
        tname = str(raw_policy_tool)
        if tname and tname not in discovered_tools:
            discovered_tools[tname] = True

    tools_list = [{"name": name, "out": is_out} for name, is_out in discovered_tools.items()]

    replay_steps: list[dict[str, Any]] = []
    final_answer_text = detail.get("final_answer") or detail.get("summary") or "Task completed."
    final_findings = list(ground_for_final)

    for i, step in enumerate(timeline):
        raw_type = str(step.get("type", "UNKNOWN")).upper()
        step_idx = int(step.get("step_index", i))

        # Attach findings for this step
        step_f: list[list[str]] = []
        if step_idx in scope_by_step:
            step_f.extend(scope_by_step[step_idx])
        if step_idx in pii_by_step:
            step_f.extend(pii_by_step[step_idx])
        if step_idx in ground_by_step:
            step_f.extend(ground_by_step[step_idx])

        if raw_type in ("FINAL_ANSWER", "ANSWER"):
            final_answer_text = str(step.get("content") or step.get("final_answer") or final_answer_text)
            if step_idx in pii_by_step:
                final_findings.extend(pii_by_step[step_idx])
            continue

        if raw_type in ("TOOL_CALL", "CALL"):
            tool_name = step.get("tool_name") or "unknown_tool"
            tool_input = step.get("tool_input") or {}
            input_str = json.dumps(tool_input) if isinstance(tool_input, (dict, list)) else str(tool_input)
            replay_steps.append({
                "k": "call",
                "tool": tool_name,
                "b": f"{tool_name}()",
                "t": input_str,
                "f": step_f,
            })
        elif raw_type in ("TOOL_RESULT", "RESULT", "OBSERVATION"):
            tool_name = step.get("tool_name") or "tool"
            obs = str(step.get("observation") or step.get("output") or step.get("content") or "")
            replay_steps.append({
                "k": "res",
                "tool": tool_name,
                "b": f"{tool_name} result",
                "t": obs,
                "f": step_f,
            })
        else:
            # User or reasoning statement
            content = str(step.get("content") or step.get("thought") or step.get("prompt") or "")
            short_bubble = (content[:35] + "…") if len(content) > 35 else content
            replay_steps.append({
                "k": "say",
                "tool": None,
                "b": short_bubble or "Thinking…",
                "t": content,
                "f": step_f,
            })

    return {
        "id": trace_id,
        "task": task_type,
        "bot": bot_type,
        "score": round(risk_score, 1),
        "tier": risk_tier,
        "tools": tools_list,
        "steps": replay_steps,
        "final": {
            "t": final_answer_text,
            "f": final_findings,
        },
    }


def render_replay_html(detail: dict[str, Any]) -> str:
    """Render full standalone HTML document for 3D agent trail replay."""
    template_path = Path(__file__).resolve().parent / "trail_replay.html"
    if not template_path.is_file():
        raise FileNotFoundError(f"3D replay template missing at {template_path}")

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    data = build_replay_data(detail)
    data_json = json.dumps(data)
    return template.replace("__DATA__", data_json)
