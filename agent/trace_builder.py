"""Trace Builder for generating schema-compliant AI Agent execution traces.

Enforces monotonic step indexing, consistent timestamps, paired call_id values,
and strict validation against schemas/trace.schema.json.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.validation import validate_trace_dict
from auditor.models import StepType, Trace, TraceStep


def _utcnow_iso() -> str:
    """Return formatted UTC ISO 8601 timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TraceBuilder:
    """Builder utility ensuring deterministic and schema-compliant trace construction."""

    def __init__(
        self,
        trace_id: str | None = None,
        task_type: str = "customer_refund",
        schema_version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
        started_at: str | None = None,
    ) -> None:
        self.trace_id = trace_id or f"tr-{uuid.uuid4()}"
        self.task_type = task_type
        self.schema_version = schema_version
        self.metadata = metadata or {}
        self.started_at = started_at or _utcnow_iso()
        self.ended_at: str | None = None
        self._steps: list[TraceStep] = []
        self._final_answer: str | None = None

    @property
    def current_step_count(self) -> int:
        return len(self._steps)

    def add_assistant_message(
        self,
        content: str,
        timestamp: str | None = None,
    ) -> TraceStep:
        """Append an observable assistant message step."""
        step = TraceStep(
            index=self.current_step_count,
            type=StepType.ASSISTANT_MESSAGE,
            content=content,
            timestamp=timestamp or _utcnow_iso(),
        )
        self._steps.append(step)
        return step

    def add_tool_call(
        self,
        tool_name: str,
        input_payload: Any,
        call_id: str | None = None,
        timestamp: str | None = None,
    ) -> TraceStep:
        """Append a tool invocation step with paired call_id."""
        step = TraceStep(
            index=self.current_step_count,
            type=StepType.TOOL_CALL,
            tool_name=tool_name,
            input=input_payload,
            call_id=call_id or f"call-{uuid.uuid4().hex[:8]}",
            timestamp=timestamp or _utcnow_iso(),
        )
        self._steps.append(step)
        return step

    def add_tool_result(
        self,
        tool_name: str,
        output_payload: Any,
        call_id: str | None = None,
        timestamp: str | None = None,
    ) -> TraceStep:
        """Append a tool result step with correlating call_id."""
        step = TraceStep(
            index=self.current_step_count,
            type=StepType.TOOL_RESULT,
            tool_name=tool_name,
            output=output_payload,
            call_id=call_id,
            timestamp=timestamp or _utcnow_iso(),
        )
        self._steps.append(step)
        return step

    def add_error(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> TraceStep:
        """Append an observable execution error step."""
        step = TraceStep(
            index=self.current_step_count,
            type=StepType.ERROR,
            message=message,
            error_code=error_code,
            details=details,
            timestamp=timestamp or _utcnow_iso(),
        )
        self._steps.append(step)
        return step

    def set_final_answer(self, final_answer: str) -> None:
        """Set the observable final answer delivered to caller."""
        self._final_answer = final_answer

    def build(self, validate: bool = True) -> Trace:
        """Construct the finalized Trace instance and validate against schema."""
        if not self.ended_at:
            self.ended_at = _utcnow_iso()

        if self._final_answer is None:
            # Fallback if execution terminated without final answer
            self._final_answer = (
                self._steps[-1].content
                if self._steps and self._steps[-1].content
                else "Agent execution completed without explicit final answer."
            )

        if not self._steps:
            # If no steps were recorded, add an initial message
            self.add_assistant_message("No actions were executed.")

        trace_data: dict[str, Any] = {
            "trace_id": self.trace_id,
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "metadata": self.metadata,
            "steps": [s.model_dump(mode="json") for s in self._steps],
            "final_answer": self._final_answer,
        }

        if validate:
            validation_res = validate_trace_dict(trace_data)
            if not validation_res.is_valid:
                errors_str = "; ".join(validation_res.errors)
                raise ValueError(f"TraceBuilder generated schema-invalid trace: {errors_str}")
            assert validation_res.trace is not None
            return validation_res.trace

        return Trace.model_validate(trace_data)

    def save(self, output_path: str | Path, validate: bool = True) -> Path:
        """Build and serialize the trace to disk as a JSON file."""
        trace = self.build(validate=validate)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace.model_dump(mode="json"), f, indent=2)
        return path
