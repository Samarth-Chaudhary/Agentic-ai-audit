"""Foundation tests for Trace validation against JSON Schema and Pydantic models."""

import subprocess
import sys
from pathlib import Path

from agent.validation import validate_trace_dict, validate_trace_file
from auditor.models import Trace


def test_valid_trace_passes_validation(fixtures_dir: Path):
    """Ensure a conforming trace passes schema validation and parses into Trace model."""
    valid_file = fixtures_dir / "valid_trace.json"
    result = validate_trace_file(valid_file)

    assert result.is_valid is True, f"Validation errors: {result.errors}"
    assert len(result.errors) == 0
    assert result.trace is not None
    assert isinstance(result.trace, Trace)
    assert result.trace.trace_id == "tr-98b43f11-7489-4a90-8e12-32ba56dc901a"
    assert len(result.trace.steps) == 4


def test_invalid_trace_missing_fields_fails(fixtures_dir: Path):
    """Ensure trace missing mandatory top-level contract fields is rejected with clear errors."""
    invalid_file = fixtures_dir / "invalid_missing_fields_trace.json"
    result = validate_trace_file(invalid_file)

    assert result.is_valid is False
    assert len(result.errors) > 0
    # Must report missing properties
    err_text = " ".join(result.errors)
    assert "final_answer" in err_text or "task_type" in err_text


def test_invalid_step_type_rejected(fixtures_dir: Path):
    """Ensure non-contractual step types (e.g. private_thought) are strictly rejected."""
    invalid_file = fixtures_dir / "invalid_step_type_trace.json"
    result = validate_trace_file(invalid_file)

    assert result.is_valid is False
    assert len(result.errors) > 0
    err_text = " ".join(result.errors)
    assert "private_thought" in err_text or "enum" in err_text.lower() or "type" in err_text.lower()


def test_invalid_tool_call_missing_required_fields(fixtures_dir: Path):
    """Ensure tool_call step without tool_name and input is rejected."""
    invalid_file = fixtures_dir / "invalid_tool_call_trace.json"
    result = validate_trace_file(invalid_file)

    assert result.is_valid is False
    assert len(result.errors) > 0
    err_text = " ".join(result.errors)
    assert "tool_name" in err_text or "input" in err_text


def test_invalid_tool_result_missing_output(valid_trace_dict: dict):
    """Ensure tool_result step without output fails validation."""
    data = dict(valid_trace_dict)
    data["steps"] = [
        {
            "index": 0,
            "type": "tool_result",
            "tool_name": "search_kb"
            # missing "output"
        }
    ]
    result = validate_trace_dict(data)
    assert result.is_valid is False
    assert any("output" in err for err in result.errors)


def test_invalid_assistant_message_missing_content(valid_trace_dict: dict):
    """Ensure assistant_message step without content fails validation."""
    data = dict(valid_trace_dict)
    data["steps"] = [
        {
            "index": 0,
            "type": "assistant_message"
            # missing "content"
        }
    ]
    result = validate_trace_dict(data)
    assert result.is_valid is False
    assert any("content" in err for err in result.errors)


def test_validate_trace_cli_valid(project_root: Path, fixtures_dir: Path):
    """Test CLI script returns 0 on valid trace file."""
    valid_file = fixtures_dir / "valid_trace.json"
    cli_script = project_root / "scripts" / "validate_trace.py"

    proc = subprocess.run(
        [sys.executable, str(cli_script), str(valid_file)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "VALID" in proc.stdout


def test_validate_trace_cli_invalid(project_root: Path, fixtures_dir: Path):
    """Test CLI script returns non-zero exit code on invalid trace file and explains errors."""
    invalid_file = fixtures_dir / "invalid_missing_fields_trace.json"
    cli_script = project_root / "scripts" / "validate_trace.py"

    proc = subprocess.run(
        [sys.executable, str(cli_script), str(invalid_file)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "INVALID" in proc.stdout
    assert "Total Errors Found" in proc.stdout
