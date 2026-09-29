"""Integration and unit tests for AgentRunner: execution flow, trace validation, and safety limits."""

import subprocess
import sys
from pathlib import Path

from agent.provider import LLMResponse, MockLLMProvider, ToolCall
from agent.runner import AgentRunner
from agent.validation import validate_trace_dict
from auditor.models import StepType, Trace


def test_runner_customer_refund_complete_flow(tmp_path: Path):
    """Ensure runner executes full customer refund flow and produces a schema-valid trace."""
    provider = MockLLMProvider()
    runner = AgentRunner(provider=provider, max_iterations=10)

    trace = runner.run(
        task_type="customer_refund",
        scenario_id="refund_eligible_full",
        output_dir=tmp_path,
    )

    # 1. Structural assertions
    assert isinstance(trace, Trace)
    assert trace.task_type == "customer_refund"
    assert len(trace.steps) >= 4

    # 2. Monotonic step index assertion
    indexes = [s.index for s in trace.steps]
    assert indexes == list(range(len(trace.steps)))

    # 3. Step type assertions (must contain tool_call and tool_result)
    step_types = [s.type for s in trace.steps]
    assert StepType.TOOL_CALL in step_types
    assert StepType.TOOL_RESULT in step_types

    # 4. Paired call_id correlation assertion
    tool_calls = [s for s in trace.steps if s.type == StepType.TOOL_CALL]
    tool_results = [s for s in trace.steps if s.type == StepType.TOOL_RESULT]
    assert len(tool_calls) == len(tool_results)
    for tc, tr in zip(tool_calls, tool_results, strict=False):
        assert tc.call_id == tr.call_id
        assert tc.tool_name == tr.tool_name

    # 5. Contract validation assertion
    val_res = validate_trace_dict(trace.model_dump(mode="json"))
    assert val_res.is_valid is True, f"Errors: {val_res.errors}"

    # 6. File persisted assertion
    saved_file = tmp_path / "customer_refund" / f"{trace.trace_id}.json"
    assert saved_file.exists()


def test_runner_research_summary_flow(tmp_path: Path):
    """Ensure runner executes research summary flow and produces a valid trace."""
    provider = MockLLMProvider()
    runner = AgentRunner(provider=provider, max_iterations=10)

    trace = runner.run(
        task_type="research_summary",
        scenario_id="research_governance_frameworks",
        output_dir=tmp_path,
    )

    assert trace.task_type == "research_summary"
    val_res = validate_trace_dict(trace.model_dump(mode="json"))
    assert val_res.is_valid is True


def test_runner_loop_limit_enforcement(tmp_path: Path):
    """Ensure runner terminates gracefully when max_iterations is reached without infinite looping."""
    # Provider that perpetually issues tool calls
    infinite_tool_calls = [
        LLMResponse(
            content="Still researching...",
            tool_calls=[ToolCall(call_id=f"c-{i}", tool_name="calculator", arguments={"expression": "1+1"})],
            finish_reason="tool_calls",
        )
        for i in range(10)
    ]
    looping_provider = MockLLMProvider(canned_responses=infinite_tool_calls)
    runner = AgentRunner(provider=looping_provider, max_iterations=2)

    trace = runner.run(
        task_type="customer_refund",
        scenario_id="refund_eligible_full",
        output_dir=tmp_path,
    )

    # Must contain error step explaining limit exceeded
    error_steps = [s for s in trace.steps if s.type == StepType.ERROR]
    assert len(error_steps) >= 1
    assert error_steps[0].message is not None
    assert "maximum permitted iterations" in error_steps[0].message.lower()

    # Final trace must still be schema valid!
    val_res = validate_trace_dict(trace.model_dump(mode="json"))
    assert val_res.is_valid is True


def test_runner_malformed_or_unauthorized_tool_call(tmp_path: Path):
    """Ensure runner safely handles model requesting an unauthorized/nonexistent tool."""
    canned = [
        LLMResponse(
            content="Attempting unauthorized operation",
            tool_calls=[ToolCall(call_id="c-bad", tool_name="unauthorized_bash_exec", arguments={"cmd": "ls"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content="Tool was rejected, concluding task.",
            tool_calls=[],
            finish_reason="stop",
        ),
    ]
    provider = MockLLMProvider(canned_responses=canned)
    runner = AgentRunner(provider=provider, max_iterations=5)

    trace = runner.run(
        task_type="customer_refund",
        scenario_id="refund_eligible_full",
        output_dir=tmp_path,
    )

    # Must record tool_result with error and an error step
    assert any(s.type == StepType.ERROR for s in trace.steps)
    val_res = validate_trace_dict(trace.model_dump(mode="json"))
    assert val_res.is_valid is True


def test_run_agent_cli_mock(project_root: Path, tmp_path: Path):
    """Ensure CLI run_agent.py executes cleanly with --mock flag."""
    cli_path = project_root / "scripts" / "run_agent.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--task-type",
            "customer_refund",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path),
            "--mock",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert "Successfully generated 1 schema-valid traces" in proc.stdout
    # Check that a file was created in output directory
    generated_files = list((tmp_path / "customer_refund").glob("*.json"))
    assert len(generated_files) == 1
