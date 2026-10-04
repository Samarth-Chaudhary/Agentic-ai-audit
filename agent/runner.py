"""Agent execution runner coordinating LLM tool calling and trace generation.

Implements the exact 15-step execution control flow required by the contract.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.pep_guardrail import PolicyEnforcementPoint, PolicyViolationError
from agent.provider import LLMMessage, LLMProvider
from agent.scenarios import Scenario, get_scenario
from agent.tools import get_tools_for_task
from agent.tools.base import BaseTool, ToolError
from agent.trace_builder import TraceBuilder
from auditor.models import Trace
from auditor.policy_loader import PolicyLoader
from project.logging import get_logger

logger = get_logger(__name__, component="agent_runner")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AgentRunner:
    """Orchestrates single-task agent execution and trace generation."""

    def __init__(
        self,
        provider: LLMProvider,
        max_iterations: int = 10,
        policy_loader: PolicyLoader | None = None,
    ) -> None:
        self.provider = provider
        self.max_iterations = max_iterations
        self.policy_loader = policy_loader or PolicyLoader()

    def run(
        self,
        task_type: str,
        scenario_id: str | None = None,
        custom_scenario: Scenario | None = None,
        output_dir: str | Path | None = None,
        guardrail_mode: bool = False,
    ) -> Trace:
        """Execute the complete agent flow following the 15-step contract."""
        # 1. create trace_id
        trace_id = f"tr-{uuid.uuid4()}"

        # 2. record start timestamp
        started_at = _utcnow_iso()

        # 3. load selected task/scenario
        if custom_scenario:
            scenario = custom_scenario
        else:
            scenario = get_scenario(task_type, scenario_id=scenario_id)

        # 4. load available tools based on policy
        policy = self.policy_loader.get_policy(task_type)
        pep = PolicyEnforcementPoint(policy) if guardrail_mode else None
        available_tools: list[BaseTool] = get_tools_for_task(policy.allowed_tools)
        tool_map: dict[str, BaseTool] = {t.name: t for t in available_tools}

        logger.info_event(
            event="agent_start",
            status="started",
            message=f"Starting agent run for task '{task_type}', scenario '{scenario.scenario_id}'",
            trace_id=trace_id,
            task_type=task_type,
            extra_data={"allowed_tools": policy.allowed_tools, "scenario": scenario.scenario_id},
        )

        trace_builder = TraceBuilder(
            trace_id=trace_id,
            task_type=task_type,
            schema_version="1.0.0",
            metadata={
                "scenario_id": scenario.scenario_id,
                "scenario_title": scenario.title,
                "provider": getattr(self.provider, "model", "mock"),
            },
            started_at=started_at,
        )

        # Initialize conversation messages
        messages: list[LLMMessage] = []
        if scenario.system_prompt:
            messages.append(LLMMessage(role="system", content=scenario.system_prompt))
        messages.append(LLMMessage(role="user", content=scenario.user_prompt))

        iteration = 0
        final_answer: str | None = None

        # Multi-turn execution loop (Steps 5-11)
        while iteration < self.max_iterations:
            iteration += 1

            # 5. send task and tool definitions to the model
            try:
                response = self.provider.generate(messages=messages, tools=available_tools)
            except Exception as e:
                logger.error_event(
                    event="model_error",
                    status="failed",
                    message=f"LLM Provider invocation failed: {e!s}",
                    trace_id=trace_id,
                    task_type=task_type,
                )
                trace_builder.add_error(
                    message=f"LLM Provider error: {e!s}",
                    error_code="PROVIDER_ERROR",
                )
                final_answer = f"Execution terminated due to model provider error: {e!s}"
                break

            # 6. inspect model response
            has_tool_calls = bool(response.tool_calls)
            content = response.content

            # If model returned text commentary alongside tool calls, record observable assistant step
            if content and has_tool_calls:
                trace_builder.add_assistant_message(content=content)
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content=content,
                        tool_calls=response.tool_calls,
                    )
                )
            elif content and not has_tool_calls:
                # 11/12. Model returns final answer (no more tool calls)
                trace_builder.add_assistant_message(content=content)
                final_answer = content
                break
            elif has_tool_calls and not content:
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content="",
                        tool_calls=response.tool_calls,
                    )
                )

            # 7. if tool calls exist, validate and execute them
            for tc in response.tool_calls:
                call_id = tc.call_id
                tool_name = tc.tool_name
                tool_args = tc.arguments

                # 8. append tool_call step
                trace_builder.add_tool_call(
                    tool_name=tool_name,
                    input_payload=tool_args,
                    call_id=call_id,
                )

                # Preventative Policy Enforcement Point check
                if pep is not None:
                    try:
                        pep.intercept_tool_call(tool_name, tool_args)
                    except PolicyViolationError as pve:
                        output_payload = {
                            "error": f"Policy Enforcement Point Block: {pve!s}",
                            "rule_violated": pve.rule_violated,
                            "severity": pve.severity.value,
                            "blocked": True,
                            "success": False,
                        }
                        trace_builder.add_tool_result(
                            tool_name=tool_name,
                            output_payload=output_payload,
                            call_id=call_id,
                        )
                        messages.append(
                            LLMProvider.create_tool_result_message(
                                tool_call_id=call_id,
                                tool_name=tool_name,
                                result=output_payload,
                            )
                        )
                        continue

                # Execute tool
                if tool_name not in tool_map:
                    output_payload = {
                        "error": f"Tool '{tool_name}' is not recognized or not authorized in available tools.",
                        "success": False,
                    }
                    trace_builder.add_error(
                        message=f"Unauthorized or unrecognized tool: {tool_name}",
                        error_code="TOOL_NOT_FOUND",
                    )
                else:
                    tool_instance = tool_map[tool_name]
                    try:
                        output_payload = tool_instance(**tool_args)
                        if pep is not None:
                            pep.record_successful_execution(tool_name, tool_args)
                    except ToolError as te:
                        output_payload = {"error": f"Tool validation error: {te!s}", "success": False}
                    except Exception as ex:
                        output_payload = {"error": f"Tool execution failed: {ex!s}", "success": False}

                # 9. append tool_result step
                trace_builder.add_tool_result(
                    tool_name=tool_name,
                    output_payload=output_payload,
                    call_id=call_id,
                )

                # 10. send tool results back to model (add to conversation history)
                messages.append(
                    LLMProvider.create_tool_result_message(
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        result=output_payload,
                    )
                )

        # Check loop iteration limit
        if iteration >= self.max_iterations and final_answer is None:
            err_msg = f"Agent execution exceeded maximum permitted iterations ({self.max_iterations})."
            trace_builder.add_error(message=err_msg, error_code="MAX_ITERATIONS_EXCEEDED")
            final_answer = f"Agent stopped: maximum iteration limit of {self.max_iterations} reached."
            logger.error_event(
                event="loop_limit_exceeded",
                status="limit_reached",
                message=err_msg,
                trace_id=trace_id,
                task_type=task_type,
            )

        # 12. append final observable assistant content
        trace_builder.set_final_answer(final_answer or "No response generated.")

        # 13. record end timestamp
        trace_builder.ended_at = _utcnow_iso()

        # 14. validate the complete trace
        trace = trace_builder.build(validate=True)

        # 15. save the trace
        base_dir = Path(output_dir) if output_dir else Path("data") / "generated_traces"
        save_path = base_dir / task_type / f"{trace_id}.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(trace.model_dump(mode="json"), f, indent=2)

        logger.info_event(
            event="agent_complete",
            status="completed",
            message=f"Agent trace saved successfully to {save_path}",
            trace_id=trace_id,
            task_type=task_type,
            extra_data={"step_count": len(trace.steps), "path": str(save_path)},
        )

        return trace
