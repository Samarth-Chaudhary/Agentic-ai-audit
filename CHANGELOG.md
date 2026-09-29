# Changelog

All notable changes to the AI Agent Governance & Audit Trail Analyzer project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - Phase 3: Independent Evidence (2026-09-29)

### Added
- **Independent Public Benchmark Evaluation (HaluEval-QA)**:
  - Downloaded and evaluated 100 responses (unfiltered first 50 pairs: 50 faithful, 50 hallucinated) from the official HaluEval QA benchmark (EMNLP 2023, MIT License) to `data/public_benchmarks/halueval_qa_50pairs.jsonl`.
  - Built public benchmark runner `scripts/evaluate_public_benchmark.py` evaluating Groundedness via `cross-encoder/nli-deberta-v3-small`.
  - Published comprehensive results (`data/public_benchmarks/halueval_evaluation_results.json`) disclosing exact metrics (Precision: 0.673, Recall: 0.660, F1: 0.667, Accuracy: 0.670) and honest performance gap vs Phase 2 self-built fixtures (-0.161 F1 gap, -0.340 recall gap).
- **Red-Team Adversarial Audit Suite**:
  - Implemented generator `scripts/build_adversarial_suite.py` producing 9 schema-valid adversarial traces across Scope, PII, and Groundedness (`data/adversarial/traces/`).
  - Implemented evaluation harness `scripts/evaluate_adversarial.py` logging outcomes, defect root causes, and needed architectural fixes in `data/adversarial/adversarial_evaluation_results.json`.
  - Honestly reported all 5 auditor defeats (SQL injection in args, evasive tool alias injection, obfuscated email, base64 token, and prompt injection inside tool result) alongside 4 successful defenses.
- **External Non-Native Trace Format Adapter (OpenTelemetry GenAI)**:
  - Implemented `OpenTelemetryGenAIAdapter` (`auditor/adapters/opentelemetry_adapter.py`) converting CNCF OpenTelemetry GenAI Semantic Conventions v1.28.0 OTLP JSON traces into the canonical internal `Trace` schema without hand-editing.
  - Added real OTLP sample trace fixture at `fixtures/external_traces/opentelemetry_genai_trace.json`.
  - Implemented comprehensive unit and end-to-end audit tests in `tests/test_opentelemetry_adapter.py` (4 tests passing).
- **Single-Command Metric Reproducibility & CI Enforcement**:
  - Created master reproducibility verification script `scripts/reproduce_all_metrics.py` asserting that 100% of published numbers in the README match repository outputs within floating-point tolerance.
  - Added `make reproduce` and `make benchmark` targets to `Makefile`.
  - Integrated `python scripts/reproduce_all_metrics.py --verify-all` and scheduled weekly cron (`cron: '0 4 * * 1'`) into `.github/workflows/ci.yml`.

---

## [0.2.0] - Phase 2: Real Agents on Real Data (2026-09-29)

### Added
- **Real Underlying Datasets & Tool Backing**:
  - Implemented `OlistDataLoader` (`agent/data/olist_loader.py`) indexing 5,000 authentic orders, 5,196 payments, 5,603 order items, 3,859 products, and category translations from the Olist Brazilian E-Commerce dataset into a local SQLite store (`data/olist/olist.db`).
  - Implemented `SecEdgarDataLoader` (`agent/data/edgar_loader.py`) querying live corporate 10-K and 10-Q XBRL financial facts from the U.S. SEC EDGAR public API with User-Agent compliance, gzip decompression, and local caching under `data/sec_edgar/`.
  - Upgraded `order_lookup`, `refund_tool`, and added `sec_edgar_research` tools with strict provenance tracking (`data_source: "olist_ecommerce_dataset"` / `"sec_edgar_xbrl_api"`, `is_synthetic: false`).
- **Real LLM Function-Calling Execution**:
  - Executed 34 genuine agent execution traces spanning `customer_refund` and `research_summary` tasks using `llama3.2:3b` over a local Ollama server.
  - Intercepted 100% of reasoning steps, tool calls, and tool outputs with natural variation in step counts (3 to 7 steps) and tool call sequences.
  - Persisted all raw traces under `data/generated_traces/` with complete attempt logging in `data/generated_traces/run_log.json`.
- **Hand-Labeled 54-Case Evaluation Benchmark**:
  - Constructed 54 hand-labeled test cases across Scope, PII, and Groundedness (18 cases each: 12 true violations + 6 hard negatives).
  - Built machine-readable label catalog in `data/evaluation_set/labels.json` and trace fixtures in `data/evaluation_set/traces/`.
- **Per-Detector Empirical Evaluation & Naive Baseline Comparison**:
  - Implemented `scripts/evaluate_detectors.py` supporting production engines and naive baselines (Allowlist for Scope, Plain Presidio for PII, Keyword Fallback for Groundedness).
  - Measured and published exact precision, recall, and F1 per detector with full false positive and false negative audit.
- **Risk-Score Weight Calibration & Sensitivity Analysis**:
  - Implemented `scripts/calibrate_risk_weights.py` evaluating production weights (0.35, 0.35, 0.30) against 4 alternative schemes.
  - Conducted sensitivity analysis with $\pm 10\%$ perturbations confirming risk tier assignment stability.

---

## [0.1.0] - Phase 1: Trust & Integrity (2026-09-29)

### Fixed
- **Groundedness False Positive on Supported Claims**:
  - **Root Cause**: Nearest-result matching instead of full-evidence search. The previous detector computed embedding similarities across the entire flattened evidence pool and only evaluated NLI against the single top-similarity candidate (`best_idx = max(similarities)`). In multi-step agent traces, early discovery tools (e.g., `order_lookup`) often had higher lexical similarity for common entity tokens than downstream action tools (e.g., `refund_tool`). When the top-similarity candidate did not directly entail the final refund confirmation claim, the detector returned `NEUTRAL` and incorrectly flagged a fully grounded answer as `UNSUPPORTED`. Furthermore, raw string comparisons failed when comparing equivalent numbers in different string formats (e.g., `'120.0'` vs `'120.00'`).
  - **Fix**: Refactored `GroundednessDetector.evaluate()` to perform a comprehensive full-evidence search across every distinct tool execution step in the trace. The evaluator now gathers the best candidate from each tool result alongside high-similarity candidates, evaluates candidates in descending similarity order, and immediately marks a claim as `SUPPORTED` when any valid tool execution provides `ENTAILMENT`. Number extraction was upgraded to parse float values and verify subset containment before falling back to NLI.
  - **Regression Test Coverage**: Added `tests/test_groundedness_regression.py` containing 8 automated test cases, including the clean refund trace (`fixtures/valid_customer_refund.json`), 5 non-first/non-adjacent multi-step cases (flight rebooking, IT helpdesk, banking dispute credit, cloud autoscaling, and e-commerce payment gateway), and negative controls confirming that genuine hallucinations remain `UNSUPPORTED` and numeric discrepancies remain `CONTRADICTED`.

### Added
- **Explicit Engine Identity Disclosure**:
  - Extended JSON Schema (`schemas/audit_result.schema.json`) and data models (`auditor/models.py`) with `EngineInfo` structure capturing `nli_engine`, `embedding_engine`, `pii_engine`, `is_degraded`, and `degraded_reasons`.
  - Added `engine: str | None` property to `GroundednessFinding`, `PIIFinding`, and `ScopeFinding` schemas and data models.
  - Persisted concrete engine metadata into DynamoDB records, S3 analytics outputs, and API Gateway responses (`lambda/get_trace.py`, `lambda/list_traces.py`, `lambda/repositories/dynamodb_repository.py`).
  - Updated Streamlit Reviewer Dashboard (`dashboard/components.py`, `dashboard/app.py`) to display concrete engine identification badges next to every risk score and within each technical evidence tab.
  - Added sample audit results illustrating full-model runs (`docs/samples/audit_result_full_model.json`) and degraded heuristic runs (`docs/samples/audit_result_degraded.json`).
- **Explicit Degraded Mode (Never Silent)**:
  - Added `fail_on_degraded: bool` option to `AuditOrchestrator`.
  - Implemented `DegradedEngineError` in `auditor/orchestrator.py` which rejects audits when `fail_on_degraded=True` and required ML engines are unavailable.
  - Implemented degraded flagging pathway when `fail_on_degraded=False`, recording `status="DEGRADED"`, `is_degraded=True`, and populating `degraded_reasons`.
  - Added prominent visual warning banners and badges in the Streamlit Reviewer Dashboard (`dashboard/components.py`) when reviewing degraded audit records.
  - Added `tests/test_degraded_mode.py` covering failure-and-refuse, degraded-and-flag, and cross-environment disclosure variance.
- **CI Quality Enforcement**:
  - Integrated `hashicorp/setup-terraform@v3` running `terraform fmt -check -diff terraform/` and `terraform validate` against the canonical `terraform/` directory.
  - Integrated `mypy` type checking across all project source files with zero escape hatches.
  - Enforced strict `ruff check .` with zero `|| true` bypasses.

### Changed
- **Repository Hygiene & Consolidation**:
  - Deleted duplicate placeholder directory `infra/` to maintain `terraform/` as the sole canonical infrastructure module.
  - Verified `.gitignore` covers all `__pycache__`, `.pytest_cache`, `.ruff_cache`, and `scratch/` directories with zero cached artifacts tracked in git.
  - Updated `pyproject.toml` package metadata with verified author and descriptive project summary.
