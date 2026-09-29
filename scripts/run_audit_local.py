#!/usr/bin/env python
"""CLI tool to execute the deterministic local AI agent audit pipeline on a trace.

Usage:
    python scripts/run_audit_local.py path/to/trace.json
    python scripts/run_audit_local.py path/to/trace.json --output audit_result.json
    python scripts/run_audit_local.py path/to/trace.json --summary-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repository root is on sys.path for direct CLI invocation
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from auditor.orchestrator import (
    AuditOrchestrationError,
    AuditOrchestrator,
    TraceValidationError,
)
from project.logging import get_logger

logger = get_logger(__name__, component="run_audit_local")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run local governance audit controls and risk engine on an agent trace file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python scripts/run_audit_local.py fixtures/valid_customer_refund.json\n"
            "  python scripts/run_audit_local.py fixtures/bad/bad_scope_violation.json -o result.json\n"
        ),
    )
    parser.add_argument(
        "trace_path",
        type=str,
        help="Path to the JSON trace file to audit.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Optional destination path to write the formatted audit_result JSON file.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the concise human-readable audit narrative to stdout.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation spaces (default: 2).",
    )

    args = parser.parse_args()
    trace_path = Path(args.trace_path)

    if not trace_path.exists():
        sys.stderr.write(f"Error: Trace file does not exist at '{trace_path}'\n")
        return 1

    orchestrator = AuditOrchestrator()

    try:
        audit_result = orchestrator.audit(trace_path)
    except TraceValidationError as tve:
        sys.stderr.write(f"Trace Contract Validation Error:\n{tve}\n")
        return 1
    except AuditOrchestrationError as aoe:
        sys.stderr.write(f"Audit Orchestration Error:\n{aoe}\n")
        return 1
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Unexpected Execution Error: {e}\n")
        return 2

    # Serialize result
    result_dict = audit_result.model_dump(mode="json")
    formatted_json = json.dumps(result_dict, indent=args.indent)

    # Handle output destination
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted_json, encoding="utf-8")
        print(f"Audit completed successfully. Result written to: {out_path}")
        print(f"  Trace ID:    {audit_result.trace_id}")
        print(f"  Risk Tier:   {audit_result.risk_tier.value} (score: {audit_result.risk_score:.1f})")
        print(f"  Summary:     {audit_result.summary}")
    elif args.summary_only:
        print(f"Risk Tier:   {audit_result.risk_tier.value} (score: {audit_result.risk_score:.1f})")
        print(f"Summary:     {audit_result.summary}")
    else:
        print(formatted_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
