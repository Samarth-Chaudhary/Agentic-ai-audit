"""Evidence extraction and normalization module for AI Agent Governance.

Constructs structured evidence items from observable execution traces.
Only tool_result steps contribute to the evidence pool by contract.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from auditor.models import StepType, Trace


class Evidence(BaseModel):
    """Reusable structured evidence extracted from observable tool execution results."""
    step_index: int = Field(ge=0, description="0-based step index of tool_result in trace")
    tool_name: str = Field(description="Name of tool that generated the result")
    data_source: str = Field(description="Originating data source or tool URI")
    text: str = Field(description="Normalized textual representation of the evidence")


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    """Recursively flatten nested dictionary keys for consistent property naming."""
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def normalize_structured_output(output: Any) -> list[str]:
    """Deterministically convert raw JSON, dictionary, array, or text into readable evidence strings.

    Preserves numeric precision, sign, and key associations (e.g. revenue: 1200000, growth: -0.20).
    Produces both sentence-level fact assertions and coherent summary text.
    """
    if output is None:
        return []

    # 1. Plain string output
    if isinstance(output, str):
        cleaned = output.strip()
        if not cleaned:
            return []
        # If it happens to be a JSON string, attempt parsing
        if (cleaned.startswith("{") and cleaned.endswith("}")) or (cleaned.startswith("[") and cleaned.endswith("]")):
            try:
                parsed = json.loads(cleaned)
                return normalize_structured_output(parsed)
            except Exception:
                pass
        return [cleaned]

    # 2. Scalar outputs
    if isinstance(output, (int, float, bool)):
        return [str(output)]

    # 3. Dictionary output
    if isinstance(output, dict):
        flattened = _flatten_dict(output)
        if not flattened:
            return []

        sentences: list[str] = []
        summary_parts: list[str] = []

        for key, value in flattened.items():
            formatted_key = key.replace("_", " ")
            # Single fact sentence: "revenue is 1200000."
            sentence = f"{formatted_key} is {value}."
            sentences.append(sentence)
            # When the value is already a multi-word textual assertion, include it directly
            if isinstance(value, str) and len(value.strip().split()) >= 2:
                sentences.append(value.strip())
            summary_parts.append(f"{key}: {value}")

        # Combined summary record: "revenue: 1200000, growth: -0.20"
        summary_sentence = ", ".join(summary_parts) + "."
        sentences.insert(0, summary_sentence)
        return sentences

    # 4. List / Array output
    if isinstance(output, list):
        if not output:
            return []
        sentences = []
        for _idx, item in enumerate(output):
            item_sentences = normalize_structured_output(item)
            for s in item_sentences:
                sentences.append(s)
        return sentences

    return [str(output).strip()]


def build_evidence_pool(trace: Trace | dict[str, Any]) -> list[Evidence]:
    """Extract and normalize all evidence from tool_result steps in an execution trace.

    By governance contract, only tool_result steps contribute to the evidence pool
    to verify that agent claims ground strictly in verified system data.
    """
    if isinstance(trace, dict):
        steps_data = trace.get("steps", [])
    elif hasattr(trace, "steps"):
        steps_data = trace.steps
    else:
        return []

    evidence_pool: list[Evidence] = []

    for step in steps_data:
        if isinstance(step, dict):
            step_type = step.get("type")
            step_index = step.get("index", 0)
            tool_name = step.get("tool_name", "unknown_tool")
            output = step.get("output")
            details = step.get("details") or {}
        elif hasattr(step, "type"):
            step_type = step.type.value if hasattr(step.type, "value") else str(step.type)
            step_index = step.index
            tool_name = step.tool_name or "unknown_tool"
            output = step.output
            details = step.details or {}
        else:
            continue

        # Strict governance contract: Only tool_result steps contribute to evidence pool
        if step_type != StepType.TOOL_RESULT.value and step_type != "tool_result":
            continue

        data_source = details.get("data_source") if isinstance(details, dict) else None
        if not data_source:
            data_source = f"tool:{tool_name}"

        normalized_texts = normalize_structured_output(output)
        for text in normalized_texts:
            if text:
                evidence_pool.append(
                    Evidence(
                        step_index=step_index,
                        tool_name=tool_name,
                        data_source=data_source,
                        text=text,
                    )
                )

    return evidence_pool
