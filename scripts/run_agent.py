#!/usr/bin/env python
"""CLI tool for executing AI agents and generating schema-compliant audit traces.

Usage:
    python scripts/run_agent.py --task-type customer_refund --count 5
    python scripts/run_agent.py --task-type research_summary --scenario research_governance_frameworks
"""

import argparse
import os
import sys
from pathlib import Path

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
        help="Target task type (e.g. customer_refund, research_summary).",
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
        "--output-dir",
        type=str,
        default="data/generated_traces",
        help="Output directory for generated traces (default: data/generated_traces).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="OpenAI model identifier (default: gpt-4o-mini).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force using MockLLMProvider even if OpenAI credentials are set.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum loop iterations per agent execution (default: 10).",
    )

    args = parser.parse_args()
    configure_logging()

    # Determine provider
    api_key_present = bool(os.environ.get("OPENAI_API_KEY"))
    provider: LLMProvider

    if api_key_present and not args.mock:
        try:
            provider = OpenAIProvider(model=args.model)
            print(f"[INFO] Using live OpenAIProvider with model: {args.model}")
        except ProviderAuthenticationError as e:
            print(f"[WARN] OpenAI credentials check failed: {e}. Falling back to MockLLMProvider.")
            provider = MockLLMProvider()
    else:
        if args.mock:
            print("[INFO] --mock flag specified. Using MockLLMProvider.")
        else:
            print("[INFO] OPENAI_API_KEY not configured in environment. Using MockLLMProvider for offline execution.")
        provider = MockLLMProvider()

    runner = AgentRunner(provider=provider, max_iterations=args.max_iterations)

    print("=" * 60)
    print(f"Agent Trace Generator - Task: {args.task_type} (Count: {args.count})")
    print("=" * 60)

    generated_paths = []
    scenarios = list_scenarios(args.task_type)
    if not scenarios:
        print(f"[ERROR] No scenarios available for task_type '{args.task_type}'.")
        return 1

    for i in range(args.count):
        # Rotate through available scenarios if scenario not pinned
        sc_id = args.scenario if args.scenario else scenarios[i % len(scenarios)].scenario_id
        print(f"[{i+1}/{args.count}] Executing scenario: '{sc_id}'...")

        try:
            trace = runner.run(
                task_type=args.task_type,
                scenario_id=sc_id,
                output_dir=args.output_dir,
            )
            saved_file = Path(args.output_dir) / args.task_type / f"{trace.trace_id}.json"
            generated_paths.append(saved_file)
            print(f"       Generated Trace ID: {trace.trace_id}")
            print(f"       Steps: {len(trace.steps)} | Saved: {saved_file}")
        except Exception as e:
            print(f"       [FAILED] Execution error: {e}")
            return 1

    print("\n" + "=" * 60)
    print(f"Successfully generated {len(generated_paths)} schema-valid traces.")
    print(f"Output directory: {Path(args.output_dir) / args.task_type}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
