# Core Architecture & Code Explanations

> **Document Type:** Independent Code Verification & Architecture Mastery  
> **Phase:** Phase 5 — Presentation and External Validation  
> **Author:** Samarth Chaudhary (`samarth-chaudhary` <chaudharysamarth784@gmail.com>)  
> **Purpose:** Technical defense and function-by-function explanations of 5 randomly selected core repository files, documented without relying on open code editors to demonstrate full conceptual and operational mastery of the governance system.

---

## 1. `auditor/scope_detector.py` (Scope Governance Engine)

### Architectural Role
The Scope Governance Detector evaluates whether an autonomous agent adheres to strict operational boundaries during execution. It operates on structured execution traces, comparing each step against declared declarative task policies (`auditor/policies/*.yaml`).

### Key Functions & Internal Mechanics
- `ScopeDetector.__init__(policy)`: Accepts a validated Pydantic `TaskPolicy` object defining tool allowlists, maximum invocations per tool, argument constraints, and domain prerequisites. Initializes the registered rule chain:
  1. `AllowedToolsRule`: Flags any invocation of an unapproved tool (e.g. `database_cli` or `exec_code`) as `HIGH` severity.
  2. `CallLimitRule`: Tracks cumulative calls per tool; triggers `MEDIUM` or `HIGH` violations if the agent exceeds maximum thresholds (preventing infinite tool loops or denial-of-wallet).
  3. `DataSourceVerificationRule`: Enforces domain allowlists for web scrapers or external fetchers (e.g., preventing access to untrusted external URLs).
  4. `RefundRules`: Enforces business logic order-of-operations (e.g., verifying that `order_lookup` returned a delivered status before `process_refund` is allowed, and capping refund amounts at policy limits).
- `ScopeDetector.audit_trace(trace)`: Iterates through each `TOOL_CALL` step in chronological sequence. For each step, it executes the registered rule chain, accumulating `ScopeFinding` records containing `step_index`, `tool_name`, `rule_violated`, `severity`, and an audit `explanation`. Returns a consolidated `ScopeAuditResult`.

---

## 2. `auditor/pii_detector.py` & `auditor/luhn.py` (Sensitive Data & DLP)

### Architectural Role
Identifies, validates, and redacts sensitive data and credentials across all execution surfaces (user prompts, intermediate thoughts, tool invocation arguments, tool results, and final answers).

### Key Functions & Internal Mechanics
- `PIIDetector.__init__(recognizers, threshold)`: Initializes Microsoft Presidio's `AnalyzerEngine` backed by spaCy's `en_core_web_sm` model, alongside custom regex-based recognizers for high-entropy secrets (AWS access keys `AKIA[0-9A-Z]{16}`, RSA private keys, JWT tokens, API bearer keys, and credit cards).
- `PIIDetector.detect(text, context)`: Scans input text for sensitive entities. For candidate credit card strings, it passes the digit sequence to `luhn_verify()` in `auditor/luhn.py`.
- `luhn_verify(number_str)`: Computes the Mod-10 Luhn checksum. Starting from the rightmost digit, every second digit is doubled; if greater than 9, 9 is subtracted. The sum modulo 10 must equal 0. This eliminates false positive alerts on 16-digit order identifiers or tracking numbers while reliably flagging genuine PANs.
- `PIIDetector.audit_trace(trace)`: Recursively traverses string fields across all steps. When an entity is detected, records a `PIIFinding` containing `step_index`, `field_path`, `pii_type`, `severity` (e.g. `CRITICAL` for secrets/cards, `MEDIUM` for emails/phones), and a redacted preview generated via `redact_text()` in `auditor/redaction.py`.

---

## 3. `auditor/groundedness_detector.py` (Factual Entailment & NLI)

### Architectural Role
Detects factual hallucinations and contradictions by verifying whether statements in the agent's `final_answer` are factually supported by verified evidence returned in intermediate `tool_result` steps.

### Key Functions & Internal Mechanics
- `ClaimExtractor.extract_claims(final_answer)`: Splits final responses into discrete testable propositional sentences using punctuation and clause boundary tokenizers. Filters out conversational filler, apologies, and subjective statements.
- `EvidenceRetriever.retrieve(claim, timeline, top_k=3)`: Extracts observation snippets from all `tool_result` steps. In full ML mode, encodes the claim and candidate evidence into 384-dimensional dense vectors using `all-MiniLM-L6-v2` and computes cosine similarity to retrieve the $k$ most semantically relevant evidence passages.
- `TransformerNLIClassifier.classify(premise, hypothesis)`: Evaluates retrieved evidence against the claim using `cross-encoder/nli-deberta-v3-small`. Returns softmax probabilities across `[ENTAILMENT, NEUTRAL, CONTRADICTION]`. If entailment probability exceeds 0.70, the claim is marked `SUPPORTED`. If contradiction probability exceeds 0.60, it is marked `CONTRADICTION`. Otherwise, `UNSUPPORTED`.
- `HeuristicNLIClassifier.classify(premise, hypothesis)`: Deterministic zero-dependency offline fallback. Performs token intersection, negation polarity detection, and numerical entity matching. If the premise contains numbers matching the claim, it marks entailment; if numbers conflict or negation words (`not`, `failed`, `cancelled`) invert polarity, it marks contradiction.
- `GroundednessDetector.audit_trace(trace)`: Aggregates claim verdicts into `GroundednessFinding` objects with exact evidence step citations, similarity metrics, and audit verdicts.

---

## 4. `auditor/risk_engine.py` (Composite Weighted Risk Engine)

### Architectural Role
Aggregates findings from the three specialized detectors into an explainable, deterministic risk score from 0.0 to 100.0, and assigns a categorical risk tier with a structured human-readable briefing.

### Key Functions & Internal Mechanics
- `RiskScoringEngine.__init__(weights)`: Validates and normalizes weights across the three control dimensions. The calibrated baseline uses:
  $$\text{Scope Weight} = 0.35, \quad \text{PII Weight} = 0.35, \quad \text{Groundedness Weight} = 0.30$$
- `_calculate_scope_score(findings)` / `_calculate_pii_score(findings)`: Converts finding severities into numerical points: `CRITICAL` = 30 pts, `HIGH` = 15 pts, `MEDIUM` = 5 pts, `LOW` = 2 pts. Caps each sub-score at 100.0.
- `_calculate_groundedness_score(findings)`: Evaluates claim ratios. Unfounded claims add 20 pts each; direct contradictions add 40 pts each, capped at 100.0.
- `calculate_risk(scope_res, pii_res, ground_res)`: Computes the overall composite score:
  $$\text{Composite Risk} = 0.35 \cdot \text{Score}_{\text{scope}} + 0.35 \cdot \text{Score}_{\text{pii}} + 0.30 \cdot \text{Score}_{\text{ground}}$$
- `_determine_risk_tier(score)`: Maps the continuous score into discrete operational triage tiers:
  - `LOW`: $[0.0, 25.0)$
  - `MEDIUM`: $[25.0, 50.0)$
  - `HIGH`: $[50.0, 75.0)$
  - `CRITICAL`: $[75.0, 100.0]$
- `_build_summary(...)`: Deterministically formats the four-part reviewer briefing: **WHAT** happened, **WHERE** (step indices), **WHY** (flagged rule violations), and **EVIDENCE** citations.

---

## 5. `lambda/audit_handler.py` (Serverless SQS Operational Worker)

### Architectural Role
Acts as the central serverless event handler in AWS Lambda, consuming execution events buffered in Amazon SQS, pulling raw traces from S3, orchestrating detection pipelines, and saving dual-path operational and analytical records.

### Key Functions & Internal Mechanics
- `lambda_handler(event, context)`: Entrypoint for AWS Lambda. Iterates through SQS records in the batch.
- `process_sqs_record(record)`:
  1. Parses S3 bucket and object key from the S3 event notification payload inside the SQS body.
  2. Retrieves raw JSON trace via `S3Repository.get_raw_trace(bucket, key)`.
  3. Validates trace against Draft 2020-12 JSON Schema (`schemas/trace.schema.json`). On validation error, formats a structured failure record, stores it in DLQ/DynamoDB, and logs the schema mismatch.
  4. Instantiates `AuditOrchestrator` to run Scope, PII, and Groundedness detectors concurrently.
  5. Computes composite risk score and tier using `RiskScoringEngine`.
  6. Writes hot operational record to Amazon DynamoDB (`AuditResultsTable`) keyed by `trace_id` with GSI on `risk_tier` and `task_type`.
  7. Formats and writes partitioned analytical record (`date=YYYY-MM-DD/task_type=.../trace_id.json`) to S3 Analytics bucket for Athena / Glue indexing.
  8. If risk tier is `CRITICAL`, publishes an alert message to Amazon SNS (`AlertTopicArn`).
- Exception & Poison Message Handling: Unhandled exceptions are logged with structured stack traces and allowed to fail back to SQS, triggering redrive policy to the Dead Letter Queue (DLQ) after 3 attempts.
