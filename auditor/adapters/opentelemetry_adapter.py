"""Adapter for ingesting OpenTelemetry GenAI Semantic Convention traces.

Specification & Citation:
  OpenTelemetry Semantic Conventions for Generative AI Systems v1.28.0
  https://opentelemetry.io/docs/specs/semconv/gen-ai/
  Cloud Native Computing Foundation (CNCF).

Converts external OpenTelemetry spans into the canonical internal Trace schema without
requiring manual user editing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auditor.models import StepType, Trace, TraceStep
from project.logging import get_logger

logger = get_logger(__name__, component="opentelemetry_adapter")


class OpenTelemetryGenAIAdapter:
    """Ingests OpenTelemetry GenAI spans and translates them into canonical Trace objects."""

    @classmethod
    def from_file(cls, file_path: str | Path) -> Trace:
        """Load an OpenTelemetry JSON trace export and convert to canonical Trace."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"OpenTelemetry trace file not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_otlp_dict(data)

    @classmethod
    def from_otlp_dict(cls, data: dict[str, Any]) -> Trace:
        """Convert an OpenTelemetry JSON dictionary to canonical Trace."""
        spans = cls._flatten_spans(data)
        if not spans:
            raise ValueError("No spans found in OpenTelemetry export")

        # 1. Identify Root Agent / Conversation Span
        root_span = cls._find_root_span(spans)
        trace_id = root_span.get("traceId", "otel-unknown-trace")

        # 2. Extract Task Type & Timestamps
        attrs = cls._parse_attributes(root_span.get("attributes", []))
        task_type = (
            attrs.get("task.type")
            or attrs.get("gen_ai.task_type")
            or cls._infer_task_type(root_span.get("name", ""))
            or "customer_refund"
        )

        start_nano = int(root_span.get("startTimeUnixNano", 0))
        end_nano = int(root_span.get("endTimeUnixNano", 0))
        started_at = cls._nano_to_iso(start_nano)
        ended_at = cls._nano_to_iso(end_nano)

        # 3. Extract Prompt & Final Answer from events or attributes
        prompt_text = cls._extract_prompt(root_span, attrs)
        final_answer = cls._extract_completion(root_span, attrs)

        # 4. Extract Tool Spans
        tool_spans = [
            s for s in spans
            if s.get("spanId") != root_span.get("spanId")
            and cls._is_tool_span(s)
        ]
        # Sort chronologically
        tool_spans.sort(key=lambda s: int(s.get("startTimeUnixNano", 0)))

        # 5. Synthesize Canonical TraceSteps
        steps: list[TraceStep] = []
        step_idx = 0

        for t_span in tool_spans:
            t_attrs = cls._parse_attributes(t_span.get("attributes", []))
            tool_name = (
                t_attrs.get("gen_ai.tool.name")
                or t_attrs.get("tool.name")
                or t_span.get("name", "").replace("execute_tool ", "")
            )
            call_id = t_attrs.get("gen_ai.tool.call.id", f"call_{t_span.get('spanId', step_idx)}")

            raw_input = t_attrs.get("gen_ai.tool.input") or t_attrs.get("tool.input") or {}
            parsed_input = cls._parse_json_or_raw(raw_input)

            raw_output = t_attrs.get("gen_ai.tool.output") or t_attrs.get("tool.output") or {}
            parsed_output = cls._parse_json_or_raw(raw_output)

            t_start = cls._nano_to_iso(int(t_span.get("startTimeUnixNano", 0)))
            t_end = cls._nano_to_iso(int(t_span.get("endTimeUnixNano", 0)))

            # Tool Call Step
            steps.append(
                TraceStep(
                    index=step_idx,
                    type=StepType.TOOL_CALL,
                    timestamp=t_start,
                    call_id=call_id,
                    tool_name=tool_name,
                    input=parsed_input,
                )
            )
            step_idx += 1

            # Tool Result Step
            steps.append(
                TraceStep(
                    index=step_idx,
                    type=StepType.TOOL_RESULT,
                    timestamp=t_end,
                    call_id=call_id,
                    tool_name=tool_name,
                    output=parsed_output,
                )
            )
            step_idx += 1

        # If no tool steps extracted, fallback to assistant message
        if not steps:
            steps.append(
                TraceStep(
                    index=0,
                    type=StepType.ASSISTANT_MESSAGE,
                    timestamp=started_at,
                    content=final_answer,
                )
            )

        metadata: dict[str, Any] = {
            "source_telemetry": "opentelemetry_genai",
            "semconv_version": "1.28.0",
            "otel_trace_id": trace_id,
            "root_span_id": root_span.get("spanId"),
            "model": attrs.get("gen_ai.request.model", "unknown"),
            "system": attrs.get("gen_ai.system", "unknown"),
        }
        if prompt_text:
            metadata["prompt"] = prompt_text

        return Trace(
            trace_id=f"tr-otel-{trace_id[:16]}",
            schema_version="1.0.0",
            task_type=task_type,
            started_at=started_at,
            ended_at=ended_at,
            metadata=metadata,
            steps=steps,
            final_answer=final_answer,
        )

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _flatten_spans(cls, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract all spans from nested OTLP resourceSpans / scopeSpans hierarchy."""
        spans: list[dict[str, Any]] = []
        if "resourceSpans" in data:
            for rs in data["resourceSpans"]:
                for ss in rs.get("scopeSpans", []):
                    spans.extend(ss.get("spans", []))
        elif "spans" in data:
            spans.extend(data["spans"])
        return spans

    @classmethod
    def _find_root_span(cls, spans: list[dict[str, Any]]) -> dict[str, Any]:
        """Locate root agent span (parentSpanId is empty or root in hierarchy)."""
        for s in spans:
            if not s.get("parentSpanId"):
                return s
        return spans[0]

    @classmethod
    def _parse_attributes(cls, attr_list: list[dict[str, Any]]) -> dict[str, Any]:
        """Convert OTLP attribute array ({key, value: {stringValue/...}}) into a dict."""
        out: dict[str, Any] = {}
        for item in attr_list:
            key = item.get("key")
            val_obj = item.get("value", {})
            if not key:
                continue
            if isinstance(val_obj, dict):
                # Standard OTLP typed value mapping
                if "stringValue" in val_obj:
                    out[key] = val_obj["stringValue"]
                elif "intValue" in val_obj:
                    out[key] = int(val_obj["intValue"])
                elif "doubleValue" in val_obj:
                    out[key] = float(val_obj["doubleValue"])
                elif "boolValue" in val_obj:
                    out[key] = bool(val_obj["boolValue"])
                else:
                    out[key] = str(val_obj)
            else:
                out[key] = val_obj
        return out

    @classmethod
    def _is_tool_span(cls, span: dict[str, Any]) -> bool:
        """Determine if a span represents a tool invocation."""
        name = span.get("name", "").lower()
        if "execute_tool" in name or "tool" in name:
            return True
        attrs = cls._parse_attributes(span.get("attributes", []))
        op = attrs.get("gen_ai.operation.name", "").lower()
        return op in ("execute_tool", "tool", "function_call")

    @classmethod
    def _extract_prompt(cls, root_span: dict[str, Any], attrs: dict[str, Any]) -> str:
        """Extract prompt from span events or attributes."""
        if "gen_ai.prompt" in attrs:
            return str(attrs["gen_ai.prompt"])
        for ev in root_span.get("events", []):
            if "prompt" in ev.get("name", "").lower():
                ev_attrs = cls._parse_attributes(ev.get("attributes", []))
                if "gen_ai.prompt" in ev_attrs:
                    return str(ev_attrs["gen_ai.prompt"])
        return ""

    @classmethod
    def _extract_completion(cls, root_span: dict[str, Any], attrs: dict[str, Any]) -> str:
        """Extract completion / final answer from span events or attributes."""
        if "gen_ai.completion" in attrs:
            return str(attrs["gen_ai.completion"])
        for ev in root_span.get("events", []):
            if "completion" in ev.get("name", "").lower() or "response" in ev.get("name", "").lower():
                ev_attrs = cls._parse_attributes(ev.get("attributes", []))
                if "gen_ai.completion" in ev_attrs:
                    return str(ev_attrs["gen_ai.completion"])
        return "Task concluded."

    @classmethod
    def _infer_task_type(cls, span_name: str) -> str:
        low = span_name.lower()
        if "refund" in low:
            return "customer_refund"
        if "research" in low:
            return "research_summary"
        return "customer_refund"

    @classmethod
    def _nano_to_iso(cls, nano: int) -> str:
        """Convert unix nanoseconds to ISO 8601 UTC string."""
        if nano <= 0:
            return datetime.now(timezone.utc).isoformat()
        seconds = nano / 1_000_000_000.0
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def _parse_json_or_raw(cls, value: Any) -> Any:
        """Parse JSON string if encoded, else return raw structure."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value
