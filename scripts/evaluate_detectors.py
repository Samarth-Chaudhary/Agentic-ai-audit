"""Evaluates Scope, PII, and Groundedness detectors against the labeled evaluation set.

Supports both production engines and naive baselines:
- Groundedness: Transformer CrossEncoder NLI vs Heuristic keyword fallback.
- PII: Custom governance layer (regex + Luhn + contextual severity) vs Plain Presidio.
- Scope: Policy business rule engine vs Naive tool allowlist.

Computes Precision, Recall, F1, and logs every FP and FN by ID with explanation.
Outputs JSON results to data/evaluation_set/ and renders side-by-side comparison tables.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from auditor.groundedness_detector import GroundednessDetector
from auditor.models import Trace
from auditor.nli_classifier import TransformerNLIClassifier
from auditor.pii_detector import PIIDetector
from auditor.policy_loader import PolicyLoader
from auditor.scope_detector import ScopeDetector
from project.logging import configure_logging, get_logger

logger = get_logger("evaluate_detectors", component="eval")

project_root = Path(__file__).resolve().parent.parent
EVAL_DIR = project_root / "data" / "evaluation_set"
TRACES_DIR = EVAL_DIR / "traces"


class PlainPresidioDetector:
    """Naive baseline: plain Presidio AnalyzerEngine with default recognizers and no custom layer."""

    def __init__(self) -> None:
        self.analyzer: Any | None = None
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            provider = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                }
            )
            nlp_engine = provider.create_engine()
            self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        except Exception as e:
            logger.warning(f"Presidio AnalyzerEngine unavailable: {e}")

    def audit_trace(self, trace: Trace) -> list[str]:
        """Detect any default PII entity across text steps."""
        if self.analyzer is None:
            return []

        findings: list[str] = []
        texts_to_scan: list[str] = []
        for step in trace.steps:
            if step.content:
                texts_to_scan.append(step.content)
            if isinstance(step.input, dict):
                texts_to_scan.append(json.dumps(step.input))
            elif isinstance(step.input, str):
                texts_to_scan.append(step.input)
        if trace.final_answer:
            texts_to_scan.append(trace.final_answer)

        for text in texts_to_scan:
            results = self.analyzer.analyze(text=text, language="en")
            for r in results:
                findings.append(r.entity_type)
        return findings


class NaiveScopeDetector:
    """Naive baseline: only checks tool names against allowed_tools allowlist.

    Completely ignores tool invocation order, refund eligibility, and max call thresholds.
    """

    def audit_trace(self, trace: Trace, policy_loader: PolicyLoader) -> list[str]:
        findings: list[str] = []
        try:
            policy = policy_loader.get_policy(trace.task_type)
        except Exception:
            return []

        for step in trace.steps:
            if step.type == "tool_call" and step.tool_name:
                if step.tool_name not in policy.allowed_tools:
                    findings.append(f"disallowed_tool:{step.tool_name}")
        return findings


def calculate_metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def run_evaluation(mode: str = "full") -> dict[str, Any]:
    """Run evaluation in 'full' (production engines) or 'baseline' (naive fallbacks) mode."""
    labels_file = EVAL_DIR / "labels.json"
    if not labels_file.exists():
        raise FileNotFoundError(f"Labels file not found at {labels_file}. Run scripts/build_evaluation_set.py first.")

    with open(labels_file, encoding="utf-8") as f:
        labels = json.load(f)

    policy_loader = PolicyLoader()

    # Initialize detectors based on mode
    if mode == "full":
        scope_detector = ScopeDetector()
        pii_detector = PIIDetector()
        groundedness_detector = GroundednessDetector(
            nli_classifier=TransformerNLIClassifier(model_name="cross-encoder/nli-deberta-v3-small")
        )
    else:
        # Baseline mode
        scope_detector = None
        pii_detector = None
        groundedness_detector = GroundednessDetector(
            nli_classifier=TransformerNLIClassifier(model_name="heuristic")
        )

    naive_scope = NaiveScopeDetector()
    naive_pii = PlainPresidioDetector()

    results_by_detector: dict[str, dict[str, Any]] = {
        "scope": {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "failures": []},
        "pii": {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "failures": []},
        "groundedness": {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "failures": []},
    }

    for case in labels:
        case_id = case["case_id"]
        fm = case["failure_mode"]
        is_violation = case["is_violation"]
        trace_file = TRACES_DIR / case["trace_file"]

        with open(trace_file, encoding="utf-8") as tf:
            trace_dict = json.load(tf)
        trace = Trace(**trace_dict)

        predicted_violation = False
        detected_details: list[str] = []

        if fm == "scope":
            if mode == "full":
                assert scope_detector is not None
                task_policy = policy_loader.get_policy(trace.task_type)
                scope_res = scope_detector.evaluate(trace, task_policy)
                predicted_violation = not scope_res.passed
                detected_details = [f.detail for f in scope_res.findings]
            else:
                naive_findings = naive_scope.audit_trace(trace, policy_loader)
                predicted_violation = len(naive_findings) > 0
                detected_details = naive_findings

        elif fm == "pii":
            if mode == "full":
                assert pii_detector is not None
                pii_res = pii_detector.evaluate(trace)
                predicted_violation = not pii_res.passed
                detected_details = [f"{f.pii_type} ({f.severity.value})" for f in pii_res.findings]
            else:
                presidio_findings = naive_pii.audit_trace(trace)
                predicted_violation = len(presidio_findings) > 0
                detected_details = presidio_findings

        elif fm == "groundedness":
            grd_res = groundedness_detector.evaluate(trace)
            predicted_violation = not grd_res.passed
            detected_details = [f"{f.audit_verdict or f.severity.value}: {f.claim}" for f in grd_res.findings]

        # Evaluate outcome
        bucket = results_by_detector[fm]
        if is_violation and predicted_violation:
            bucket["tp"] += 1
        elif not is_violation and not predicted_violation:
            bucket["tn"] += 1
        elif not is_violation and predicted_violation:
            bucket["fp"] += 1
            bucket["failures"].append({
                "case_id": case_id,
                "type": "FALSE_POSITIVE",
                "explanation": f"Detector flagged clean hard-negative trace as violation: {', '.join(detected_details[:2])}.",
            })
        elif is_violation and not predicted_violation:
            bucket["fn"] += 1
            bucket["failures"].append({
                "case_id": case_id,
                "type": "FALSE_NEGATIVE",
                "explanation": f"Detector missed actual violation: expected {case.get('expected_findings')} but none was flagged.",
            })

    # Summary table output
    final_output: dict[str, Any] = {"mode": mode, "detectors": {}}
    for fm, data in results_by_detector.items():
        metrics = calculate_metrics(data["tp"], data["fp"], data["fn"], data["tn"])
        metrics["failures"] = data["failures"]
        final_output["detectors"][fm] = metrics

    output_path = EVAL_DIR / f"evaluation_results_{mode}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)

    return final_output


def render_markdown_tables(full_results: dict[str, Any], baseline_results: dict[str, Any]) -> str:
    lines = []
    lines.append("### Detector Evaluation Results (Full Production Engine)")
    lines.append("| Detector | Precision | Recall | F1 Score | Accuracy | TP | FP | FN | TN |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for det, m in full_results["detectors"].items():
        lines.append(
            f"| **{det.capitalize()}** | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
            f"{m['accuracy']:.3f} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |"
        )

    lines.append("\n### Comparison Against Naive Baselines (Full vs. Baseline)")
    lines.append("| Detector | Approach | Precision | Recall | F1 Score | Notes |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for det in ["scope", "pii", "groundedness"]:
        fm = full_results["detectors"][det]
        bm = baseline_results["detectors"][det]
        if det == "scope":
            f_approach = "Policy Rules + Ordering Engine"
            b_approach = "Naive Allowlist Only"
            note = "Naive allowlist misses ordering, eligibility, and max-call limit violations."
        elif det == "pii":
            f_approach = "Custom Layer (Regex + Luhn + Context)"
            b_approach = "Plain Presidio Uncustomized"
            note = "Plain Presidio suffers false positives on formatted order IDs and misses secrets."
        else:
            f_approach = "Transformer CrossEncoder NLI"
            b_approach = "Heuristic Keyword Fallback"
            note = "Transformer NLI handles paraphrasing without false positive rejections."

        lines.append(f"| **{det.capitalize()}** | **Full ({f_approach})** | **{fm['precision']:.3f}** | **{fm['recall']:.3f}** | **{fm['f1']:.3f}** | Active production engine |")
        lines.append(f"| {det.capitalize()} | Baseline ({b_approach}) | {bm['precision']:.3f} | {bm['recall']:.3f} | {bm['f1']:.3f} | {note} |")

    lines.append("\n### False Positives and False Negatives Breakdown")
    for det, m in full_results["detectors"].items():
        lines.append(f"#### {det.capitalize()} Failures (Total: {len(m['failures'])})")
        if not m["failures"]:
            lines.append("- *No false positives or false negatives observed on the labeled benchmark.*")
        for fail in m["failures"]:
            lines.append(f"- **{fail['case_id']}** ({fail['type']}): {fail['explanation']}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate detectors against labeled evaluation set.")
    parser.add_argument(
        "--mode",
        choices=["full", "baseline", "compare"],
        default="compare",
        help="Evaluation engine mode: full, baseline, or compare both.",
    )
    args = parser.parse_args()
    configure_logging()

    if args.mode in ("full", "compare"):
        print("[INFO] Running evaluation with full production detectors...")
        full_results = run_evaluation(mode="full")

    if args.mode in ("baseline", "compare"):
        print("[INFO] Running evaluation with naive baseline detectors...")
        baseline_results = run_evaluation(mode="baseline")

    if args.mode == "compare":
        md = render_markdown_tables(full_results, baseline_results)
        print("\n" + "=" * 80)
        print(md)
        print("=" * 80)

        # Save comparison JSON
        comparison_file = EVAL_DIR / "evaluation_comparison.json"
        with open(comparison_file, "w", encoding="utf-8") as f:
            json.dump({
                "full_engine": full_results,
                "baseline_engine": baseline_results,
            }, f, indent=2)
        print(f"\n[INFO] Comparison results saved to {comparison_file}")
    elif args.mode == "full":
        print(json.dumps(full_results, indent=2))
    else:
        print(json.dumps(baseline_results, indent=2))


if __name__ == "__main__":
    main()
