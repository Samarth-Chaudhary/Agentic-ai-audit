#!/usr/bin/env python
"""CLI script to validate an AI Agent execution trace against schemas/trace.schema.json.

Usage:
    python scripts/validate_trace.py path/to/trace.json
"""

import argparse
import sys
from pathlib import Path

# Ensure root directory is on PYTHONPATH for direct CLI execution
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agent.validation import validate_trace_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an agent execution trace against the primary data contract."
    )
    parser.add_argument(
        "trace_path",
        type=str,
        help="Path to the JSON trace file to validate.",
    )
    parser.add_argument(
        "--schema",
        type=str,
        default=None,
        help="Optional path to custom trace.schema.json.",
    )

    args = parser.parse_args()
    trace_path = Path(args.trace_path)

    result = validate_trace_file(trace_path, schema_path=args.schema)

    if result.is_valid:
        trace = result.trace
        print(f"VALID: Trace '{trace_path.name}' satisfies contract requirements.")
        if trace:
            print(f"  Trace ID:    {trace.trace_id}")
            print(f"  Task Type:   {trace.task_type}")
            print(f"  Steps Count: {len(trace.steps)}")
            print(f"  Started:     {trace.started_at}")
            print(f"  Ended:       {trace.ended_at}")
        return 0
    else:
        print(f"INVALID: Trace '{trace_path.name}' failed contract validation.")
        print(f"Total Errors Found: {len(result.errors)}")
        for i, err in enumerate(result.errors, 1):
            print(f"  {i}. {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
