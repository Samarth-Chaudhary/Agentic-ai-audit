"""Public benchmark evaluation script for AI Agent Governance & Audit Trail Analyzer.

Evaluates the Groundedness Detector against the public HaluEval-QA benchmark:
  - Benchmark: HaluEval (EMNLP 2023)
  - Dataset: QA Hallucination Evaluation (qa_data.json)
  - License: MIT License
  - Source: https://github.com/RUCAIBox/HaluEval
  - Selection: First 50 sequential pairs (100 evaluated responses: 50 faithful, 50 hallucinated)

Measures exact Precision, Recall, F1, and Accuracy on data the system author did not create,
and publishes the performance gap relative to self-built evaluation sets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auditor.groundedness_detector import GroundednessDetector
from auditor.models import StepType, Trace, TraceStep
from auditor.nli_classifier import TransformerNLIClassifier
from project.logging import configure_logging, get_logger

logger = get_logger(__name__, component="public_benchmark_eval")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "data" / "public_benchmarks"
DATASET_PATH = BENCHMARK_DIR / "halueval_qa_50pairs.jsonl"
METADATA_PATH = BENCHMARK_DIR / "halueval_metadata.json"
RESULTS_PATH = BENCHMARK_DIR / "halueval_evaluation_results.json"


def build_trace(case_id: str, question: str, knowledge: str, answer: str) -> Trace:
    """Wrap a QA pair into an observable execution trace."""
    steps = [
        TraceStep(
            index=0,
            type=StepType.TOOL_CALL,
            tool_name="web_search",
            input={"query": question},
            call_id=f"c-{case_id}-0",
        ),
        TraceStep(
            index=1,
            type=StepType.TOOL_RESULT,
            tool_name="web_search",
            output={"results": knowledge, "snippets": [knowledge]},
            call_id=f"c-{case_id}-0",
        ),
    ]
    return Trace(
        trace_id=f"tr-halueval-{case_id}",
        schema_version="1.0.0",
        task_type="research_summary",
        started_at="2026-09-29T12:00:00Z",
        ended_at="2026-09-29T12:00:02Z",
        metadata={"source": "HaluEval-QA", "case_id": case_id},
        steps=steps,
        final_answer=answer,
    )


def run_halueval_evaluation(nli_model: str = "cross-encoder/nli-deberta-v3-small") -> dict[str, Any]:
    """Execute evaluation on HaluEval-QA benchmark and compute metrics."""
    configure_logging()
    print("=" * 80)
    print(f"[INFO] Initializing GroundednessDetector with NLI model: {nli_model}")
    detector = GroundednessDetector(nli_classifier=TransformerNLIClassifier(model_name=nli_model))

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Benchmark file not found: {DATASET_PATH}")

    with open(METADATA_PATH, encoding="utf-8") as f:
        meta = json.load(f)

    # Read pairs
    pairs: list[dict[str, Any]] = []
    with open(DATASET_PATH, encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                pairs.append(json.loads(line_str))

    tp = 0  # Hallucinated and detector flagged violation (passed == False)
    fp = 0  # Faithful but detector flagged violation (passed == False)
    tn = 0  # Faithful and detector approved (passed == True)
    fn = 0  # Hallucinated but detector approved (passed == True)

    eval_records: list[dict[str, Any]] = []

    print(f"[INFO] Evaluating {len(pairs)} pairs (total {len(pairs) * 2} test cases)...")

    for idx, item in enumerate(pairs, start=1):
        knowledge = item["knowledge"]
        question = item["question"]
        right_answer = item["right_answer"]
        hallucinated_answer = item["hallucinated_answer"]

        # Case A: Right Answer (Grounded / Faithful, expected: violation == False)
        trace_right = build_trace(f"{idx:03d}-right", question, knowledge, right_answer)
        res_right = detector.evaluate(trace_right)
        is_violation_right = not res_right.passed

        if is_violation_right:
            fp += 1
            eval_records.append({
                "case_id": f"halueval_{idx:03d}_right",
                "ground_truth": "FAITHFUL",
                "detector_verdict": "VIOLATION (UNSUPPORTED/CONTRADICTED)",
                "outcome": "FALSE_POSITIVE",
                "question": question,
                "answer": right_answer,
                "findings": [f.audit_verdict for f in res_right.findings],
            })
        else:
            tn += 1

        # Case B: Hallucinated Answer (Hallucination / Violation, expected: violation == True)
        trace_hallu = build_trace(f"{idx:03d}-hallu", question, knowledge, hallucinated_answer)
        res_hallu = detector.evaluate(trace_hallu)
        is_violation_hallu = not res_hallu.passed

        if is_violation_hallu:
            tp += 1
        else:
            fn += 1
            eval_records.append({
                "case_id": f"halueval_{idx:03d}_hallu",
                "ground_truth": "HALLUCINATED",
                "detector_verdict": "PASSED (SUPPORTED)",
                "outcome": "FALSE_NEGATIVE",
                "question": question,
                "answer": hallucinated_answer,
                "findings": [f.audit_verdict for f in res_hallu.findings],
            })

    total = tp + fp + tn + fn
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    accuracy = round((tp + tn) / total, 4)

    output = {
        "metadata": meta,
        "nli_model": nli_model,
        "metrics": {
            "total_cases": total,
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "accuracy": accuracy,
        },
        "phase2_comparison": {
            "self_built_f1": 0.828,
            "public_benchmark_f1": f1,
            "f1_gap": round(f1 - 0.828, 4),
            "self_built_precision": 0.706,
            "public_benchmark_precision": precision,
            "self_built_recall": 1.000,
            "public_benchmark_recall": recall,
        },
        "failure_analysis": {
            "total_false_positives": fp,
            "total_false_negatives": fn,
            "sample_failures": eval_records[:10],
        },
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 80)
    print("### Public Benchmark Evaluation Results (HaluEval-QA)")
    print("| Metric | HaluEval-QA Public Benchmark | Phase 2 Self-Built Benchmark | Performance Gap |")
    print("| :--- | :--- | :--- | :--- |")
    print(f"| **Precision** | **{precision:.3f}** | 0.706 | {precision - 0.706:+.3f} |")
    print(f"| **Recall** | **{recall:.3f}** | 1.000 | {recall - 1.000:+.3f} |")
    print(f"| **F1 Score** | **{f1:.3f}** | 0.828 | {f1 - 0.828:+.3f} |")
    print(f"| **Accuracy** | **{accuracy:.3f}** | 0.722 | {accuracy - 0.722:+.3f} |")
    print(f"| Cases (TP/FP/FN/TN) | {tp} / {fp} / {fn} / {tn} (Total: {total}) | 12 / 5 / 0 / 1 (Total: 18) | — |")
    print("=" * 80)
    print(f"Full evaluation results persisted to: {RESULTS_PATH}")
    return output


if __name__ == "__main__":
    run_halueval_evaluation()
