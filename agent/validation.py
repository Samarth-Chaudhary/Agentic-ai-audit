"""Trace validation module for AI Agent execution traces.

Performs strict JSON Schema validation and Pydantic model conformance checks with detailed error reporting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ValidationError

from auditor.models import Trace


def _find_default_schema_path() -> Path:
    """Find trace.schema.json relative to project root or current working directory."""
    candidates = [
        Path.cwd() / "schemas" / "trace.schema.json",
        Path(__file__).resolve().parent.parent / "schemas" / "trace.schema.json",
        Path("schemas") / "trace.schema.json",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p.resolve()
    return candidates[0]


class TraceValidationResult:
    """Represents the outcome of validating an agent execution trace."""

    def __init__(
        self,
        is_valid: bool,
        errors: list[str] | None = None,
        trace: Trace | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.errors = errors or []
        self.trace = trace

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return f"<TraceValidationResult: {status} (errors={len(self.errors)})>"


class TraceValidator:
    """Validates raw trace dictionaries or JSON files against the primary data contract."""

    def __init__(self, schema_path: str | Path | None = None) -> None:
        self.schema_path = Path(schema_path) if schema_path else _find_default_schema_path()
        self._schema: dict[str, Any] | None = None
        self._validator: jsonschema.Draft7Validator | None = None

    def _load_schema(self) -> dict[str, Any]:
        if self._schema is None:
            if not self.schema_path.exists():
                raise FileNotFoundError(f"Trace JSON schema not found at: {self.schema_path}")
            with open(self.schema_path, encoding="utf-8") as f:
                self._schema = json.load(f)
            self._validator = jsonschema.Draft7Validator(self._schema)
        return self._schema

    def validate_dict(self, data: Any) -> TraceValidationResult:
        """Validate an in-memory dictionary against trace schema and model."""
        self._load_schema()
        assert self._validator is not None

        if not isinstance(data, dict):
            return TraceValidationResult(
                is_valid=False,
                errors=[f"Trace payload must be a JSON object, got {type(data).__name__}"],
            )

        errors: list[str] = []

        # 1. JSON Schema validation
        schema_errors = sorted(self._validator.iter_errors(data), key=lambda e: e.path)
        for err in schema_errors:
            path_str = " -> ".join(str(p) for p in err.path) if err.path else "root"
            # Format helpful message
            if err.validator == "required":
                errors.append(f"[{path_str}] Missing required property: {err.message}")
            elif err.validator == "enum":
                errors.append(f"[{path_str}] Value not allowed: {err.message}")
            elif err.validator == "additionalProperties":
                errors.append(f"[{path_str}] Disallowed additional property: {err.message}")
            else:
                errors.append(f"[{path_str}] Schema violation: {err.message}")

        # If schema validation fails, return schema errors directly
        if errors:
            return TraceValidationResult(is_valid=False, errors=errors)

        # 2. Pydantic model validation (ensuring Python models agree with JSON schema)
        try:
            trace_obj = Trace.model_validate(data)
        except ValidationError as val_err:
            for p_err in val_err.errors():
                loc = " -> ".join(str(part) for part in p_err["loc"])
                msg = p_err["msg"]
                errors.append(f"[{loc}] Model validation error: {msg}")
            return TraceValidationResult(is_valid=False, errors=errors)
        except Exception as e:
            errors.append(f"Unexpected model construction error: {e!s}")
            return TraceValidationResult(is_valid=False, errors=errors)

        return TraceValidationResult(is_valid=True, errors=[], trace=trace_obj)

    def validate_json_str(self, json_str: str) -> TraceValidationResult:
        """Validate a JSON string representation of a trace."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as jde:
            return TraceValidationResult(
                is_valid=False,
                errors=[f"JSON syntax error at line {jde.lineno}, column {jde.colno}: {jde.msg}"],
            )
        return self.validate_dict(data)

    def validate_file(self, file_path: str | Path) -> TraceValidationResult:
        """Validate a trace JSON file from disk."""
        path = Path(file_path)
        if not path.exists():
            return TraceValidationResult(
                is_valid=False,
                errors=[f"Trace file does not exist: {path}"],
            )
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return TraceValidationResult(
                is_valid=False,
                errors=[f"Failed to read file {path}: {e!s}"],
            )
        return self.validate_json_str(content)


# Module-level convenience functions
def validate_trace_dict(data: Any, schema_path: str | Path | None = None) -> TraceValidationResult:
    """Validate a dictionary against the trace contract."""
    validator = TraceValidator(schema_path=schema_path)
    return validator.validate_dict(data)


def validate_trace_file(file_path: str | Path, schema_path: str | Path | None = None) -> TraceValidationResult:
    """Validate a trace file on disk against the trace contract."""
    validator = TraceValidator(schema_path=schema_path)
    return validator.validate_file(file_path)
