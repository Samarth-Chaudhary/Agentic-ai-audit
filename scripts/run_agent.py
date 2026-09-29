#!/usr/bin/env python
"""CLI tool for executing AI agents and generating schema-compliant audit traces.

Usage:
    python scripts/run_agent.py --task-type customer_refund --count 18 --model qwen2.5:1.5b --base-url http://127.0.0.1:11434/v1
    python scripts/run_agent.py --task-type research_summary --count 16 --model qwen2.5:1.5b --base-url http://127.0.0.1:11434/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure root directory is on PYTHONPATH
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agent.openai_provider import OpenAIProvider, ProviderAuthenticationError
from agent.provider import LLMProvider, MockLLMProvider
from agent.runner import AgentRunner
from agent.scenarios import list_scenarios
from project.logging import configure_logging, get_logger

logger = get_logger("run_agent_cli", component="cli")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run AI Agent on specified task and generate governance execution traces."
    )
    parser.add_argument(
        "--task-type",
        type=str,
        default="customer_refund",
        help="Target task type (e.g. customer_refund, research_summary, or all).",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Optional specific scenario identifier.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of traces to generate (default: 1).",
    )
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        help="Execute all registered scenarios for the selected task type.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/generated_traces",
        help="Output directory for generated traces (default: data/generated_traces).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen2.5:1.5b",
        help="LLM model identifier (default: qwen2.5:1.5b).",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        help="Base URL for OpenAI-compatible endpoint (default: http://127.0.0.1:11434/v1).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force using MockLLMProvider.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum loop iterations per agent execution (default: 10).",
    )
    parser.add_argument(
        "--run-log",
        type=str,
        default="data/generated_traces/run_log.json",
        help="Path to JSON run log recording attempted vs kept runs.",
    )

    args = parser.parse_args()
    configure_logging()

    # Determine provider
    provider: LLMProvider
    if not args.mock:
        try:
            provider = OpenAIProvider(
                model=args.model,
                base_url=args.base_url,
            )
            print(f"[INFO] Using live OpenAIProvider with model '{args.model}' at '{args.base_url}'")
        except ProviderAuthenticationError as e:
            print(f"[WARN] Provider credentials check failed: {e}. Falling back to MockLLMProvider.")
            provider = MockLLMProvider()
    else:
        print("[INFO] --mock flag specified. Using MockLLMProvider.")
        provider = MockLLMProvider()

    runner = AgentRunner(provider=provider, max_iterations=args.max_iterations)

    task_types = ["customer_refund", "research_summary"] if args.task_type == "all" else [args.task_type]

    run_records: list[dict[str, Any]] = []
    log_path = Path(args.run_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8") as f:
                run_records = json.load(f)
        except Exception:
            run_records = []

    total_attempted = 0
    total_kept = 0
    total_failed = 0

    for current_task in task_types:
        scenarios = list_scenarios(current_task)
        if not scenarios:
            print(f"[ERROR] No scenarios available for task_type '{current_task}'.")
            continue

        selected_scenarios = (
            scenarios if args.all_scenarios else [scenarios[i % len(scenarios)] for i in range(args.count)]
        )
        if args.scenario:
            selected_scenarios = [s for s in scenarios if s.scenario_id == args.scenario]

        print("=" * 60)
        print(f"Agent Trace Generator - Task: {current_task} (Running {len(selected_scenarios)} scenarios)")
        print("=" * 60)

        for i, scenario in enumerate(selected_scenarios):
            total_attempted += 1
            sc_id = scenario.scenario_id
            print(f"[{i+1}/{len(selected_scenarios)}] Running scenario '{sc_id}' ({scenario.title})...")
            start_ts = datetime.now(timezone.utc).isoformat()

            try:
                trace = runner.run(
                    task_type=current_task,
                    scenario_id=sc_id,
                    output_dir=args.output_dir,
                )
                saved_file = Path(args.output_dir) / current_task / f"{trace.trace_id}.json"
                total_kept += 1
                print(f"       Success: Trace ID {trace.trace_id} ({len(trace.steps)} steps)")
                print(f"       Saved: {saved_file}")

                run_records.append({
                    "trace_id": trace.trace_id,
                    "task_type": current_task,
                    "scenario_id": sc_id,
                    "model": getattr(provider, "model", "mock"),
                    "status": "KEPT",
                    "step_count": len(trace.steps),
                    "started_at": start_ts,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "file_path": str(saved_file),
                    "exclusion_reason": None,
                })
            except Exception as e:
                total_failed += 1
                print(f"       [FAILED] Execution error: {e}")
                run_records.append({
                    "trace_id": None,
                    "task_type": current_task,
                    "scenario_id": sc_id,
                    "model": getattr(provider, "model", "mock"),
                    "status": "FAILED",
                    "step_count": 0,
                    "started_at": start_ts,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "file_path": None,
                    "exclusion_reason": str(e),
                })

    # Save run log
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(run_records, f, indent=2)

    print("\n" + "=" * 60)
    print(f"Successfully generated {total_kept} schema-valid traces in {args.output_dir}")
    print(f"Execution complete: Attempted: {total_attempted}, Kept: {total_kept}, Failed: {total_failed}")
    print(f"Run log saved to: {log_path}")
    print("=" * 60)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
