# Deterministic Post-Hoc Audit & Governance for Autonomous AI Agents

**Author:** Samarth Chaudhary (`samarth-chaudhary` <chaudharysamarth784@gmail.com>)  
**Affiliation:** Independent Research & Systems Engineering  
**Publication Date:** September 2026  
**Document Link:** [docs/technical_writeup.md](https://github.com/samarth-chaudhary/Agentic-AI-Audit/blob/master/docs/technical_writeup.md)  

---

## Abstract
As autonomous agents powered by Large Language Models (LLMs) transition from conversational interfaces to operational tools that trigger financial transactions, invoke databases, and interact with private customer data, post-hoc governance becomes essential. Standard "LLM-as-a-judge" evaluation patterns suffer from non-deterministic variance, self-preference biases, and prohibitive operational costs when evaluating high-volume event streams. We present a deterministic, multi-control post-hoc audit framework designed for ReAct agent workflows. Our architecture decouples a high-velocity operational triage path (S3 $\rightarrow$ SQS $\rightarrow$ Lambda $\rightarrow$ DynamoDB) from a longitudinal analytical lakehouse (S3 $\rightarrow$ Glue $\rightarrow$ Athena $\rightarrow$ Streamlit). We evaluate our pipeline against hand-labeled agent execution traces, a 100-case public question-answering benchmark (HaluEval-QA), and an adversarial red-team suite of 9 penetration attacks. Across 54 hand-labeled agent cases, our framework achieves an F1 score of 0.960 for scope enforcement, 0.800 for PII detection, and 0.828 for factual groundedness. On the public HaluEval benchmark, factual groundedness F1 dropped to 0.667 (-0.161 gap), and our adversarial red-team achieved a 55.56% attack success rate (44.44% defense resilience). We report full architectural trade-offs, engineering load-test metrics (2,500 synthetic traces at 24.8 traces/sec), and an honest threats-to-validity analysis.

---

## 1. Introduction & Motivation
Autonomous AI agents executing iterative Reason-and-Act (ReAct) loops present unique failure modes that traditional software testing cannot adequately constrain:
1. **Unbounded Operational Scope**: LLMs can invoke unapproved internal endpoints, enter recursive tool loops, or violate business preconditions (such as issuing financial refunds prior to verifying order return status).
2. **Data Leakage (PII/DLP)**: Unsanitized customer records, credit cards, or internal API tokens can be emitted into intermediate reasoning logs or final client responses.
3. **Hallucination & Evidence Inversion**: Agents frequently invent claims unsupported by tool observation evidence, or make statements directly contradicting backend API responses.
4. **Audit Trail Opacity**: Absence of standardized, immutable execution trace capture prevents regulatory compliance reporting (EU AI Act, SOC 2, ISO 42001) and forensic post-mortems.

To address these vulnerabilities, we developed an automated post-hoc audit framework that inspects structured agent execution traces without requiring runtime agent interference.

---

## 2. Decoupled Dual-Path Architecture
The system architecture separates immediate operational triage from longitudinal analytics:

```
[ Agent Execution Trace ]
          │
          ▼
[ Amazon S3: Raw Traces ] ──(s3:ObjectCreated)──► [ Amazon SQS / DLQ ]
                                                          │
                                                          ▼
                                              [ AWS Lambda Audit Worker ]
                                                          │
          ┌───────────────────────────────────────────────┴───────────────────────────────┐
          ▼                                                                               ▼
  [ Operational Path ]                                                            [ Analytics Path ]
  • Amazon DynamoDB (Hot Store)                                                   • Amazon S3 Partitioned Parquet
  • Single-digit ms point lookups                                                 • AWS Glue Data Catalog
  • Triage by risk_tier (LOW/MED/HIGH/CRIT)                                       • Amazon Athena ANSI SQL
  • Governance REST API                                                           • Streamlit 3D Replay Dashboard
```

- **Operational Path**: Buffers high-velocity trace arrivals through SQS, orchestrates three governance detectors within an AWS Lambda worker, indexes findings into DynamoDB, and alerts security teams via Amazon SNS on critical violations.
- **Analytics Path**: Emits partitioned audit records (`date=YYYY-MM-DD/task_type=.../trace_id.json`) to Amazon S3. AWS Glue synchronizes the table catalog, enabling cross-fleet SQL queries in Amazon Athena and interactive WebGL 3D execution visualizer in Streamlit.

---

## 3. Governance Detection Controls

### 3.1 Scope Governance Control (`auditor/scope_detector.py`)
Enforces declarative task policies (`auditor/policies/*.yaml`) against agent execution steps:
- **Tool Allowlist**: Prohibits unauthorized tool invocations (e.g., preventing a customer support agent from invoking `database_cli` or `exec_code`).
- **Call Limit Enforcement**: Caps maximum allowable invocations per tool per session, halting denial-of-wallet loops.
- **Business Logic Order-of-Operations**: Enforces domain-specific invariants (e.g., verifying `order_lookup` returned `DELIVERED` before `process_refund` is allowed).

### 3.2 Sensitive Data & DLP Control (`auditor/pii_detector.py`)
Detects, classifies, and redacts sensitive data across user prompts, tool parameters, observations, and final responses:
- Microsoft Presidio Analyzer backed by spaCy NLP (`en_core_web_sm`).
- Regex pattern matchers for high-entropy secrets (AWS access keys `AKIA[0-9A-Z]{16}`, JWTs, RSA keys).
- Mod-10 Luhn checksum algorithm (`auditor/luhn.py`) to validate 13–19 digit credit cards while ignoring 16-digit order identifiers.

### 3.3 Factual Groundedness Control (`auditor/groundedness_detector.py`)
Verifies whether statements in the agent's `final_answer` are factually entailed by intermediate tool observations:
- Propositional claim extraction (`auditor/claim_extractor.py`).
- Dense semantic evidence retrieval via Sentence Transformers (`all-MiniLM-L6-v2`).
- Natural Language Inference classification via cross-encoder (`cross-encoder/nli-deberta-v3-small`) assigning `SUPPORTED`, `UNSUPPORTED`, or `CONTRADICTION`.
- Zero-dependency heuristic NLI fallback for offline/degraded environments.

### 3.4 Composite Multi-Factor Risk Engine (`auditor/risk_engine.py`)
Computes an explainable, deterministic risk score from 0.0 to 100.0:
$$\text{Risk Score} = 0.35 \cdot \text{Score}_{\text{scope}} + 0.35 \cdot \text{Score}_{\text{pii}} + 0.30 \cdot \text{Score}_{\text{groundedness}}$$
Categorizes into discrete operational triage tiers: `LOW` [0, 25), `MEDIUM` [25, 50), `HIGH` [50, 75), and `CRITICAL` [75, 100].

---

## 4. Empirical Evaluation Results

### 4.1 Hand-Labeled Governance Benchmark (54 Cases)
We evaluated the framework on 54 realistic agent execution traces across customer support and financial research tasks, comparing our detectors against naive baselines:

| Control Domain | Baseline Model | Baseline F1 | Framework Detector | Precision | Recall | **Framework F1** | F1 Gain |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Scope Enforcement** | Naive Tool Match | 0.667 | Policy Rule Engine | 0.923 | 1.000 | **0.960** | **+0.293** |
| **PII & Sensitive Data** | Plain Presidio | 0.800 | Presidio + Luhn + Regex | 0.769 | 0.833 | **0.800** | +0.000 (Precision +0.102) |
| **Factual Groundedness** | Heuristic Token Match | 0.828 | Embeddings + NLI DeBERTa | 0.706 | 1.000 | **0.828** | Perfect Recall |

- **Scope Control**: Eliminates false negatives by checking call counts and prerequisite tool dependencies.
- **PII Control**: Adding the Luhn checksum increased precision by 10.2 percentage points (from 0.667 to 0.769) by eliminating false alarms on numeric tracking numbers.

---

## 5. Negative Results & Adversarial Defeats

### 5.1 Public Benchmark Transfer Gap (HaluEval-QA)
To prevent overfitting to self-generated agent traces, we evaluated our groundedness detector on 100 randomly sampled cases from the public HaluEval-QA benchmark:

| Metric | Self-Built Hand-Labeled Fixtures (18 cases) | HaluEval-QA Public Benchmark (100 cases) | **Performance Gap** |
| :--- | :--- | :--- | :--- |
| **Precision** | 0.706 | 0.673 | -0.033 |
| **Recall** | 1.000 | 0.660 | **-0.340** |
| **F1 Score** | 0.828 | 0.667 | **-0.161** |
| **Accuracy** | 0.722 | 0.670 | -0.052 |

**Key Finding**: When exposed to diverse open-domain questions, recall dropped from 1.000 to 0.660. The sentence transformer retriever struggled with multi-sentence reasoning chains and subtle numerical paraphrasing present in open-domain text.

### 5.2 Adversarial Red-Team Penetration Attacks (9 Scenarios)
We subjected the governance pipeline to 9 adversarial attack vectors designed to bypass controls:
- **Total Attacks**: 9
- **Defended Successfully**: 4 (44.44% Resilience Rate)
- **Defeated**: 5 (55.56% Attack Success Rate)

```
[ Defended Attacks (4/9) ]
✓ Tool argument type tampering (caught by schema validator)
✓ Tool limit flooding (caught by call limit counter)
✓ Basic credit card masking evasion (caught by Luhn mod-10 scanner)
✓ Direct factual negation (caught by DeBERTa NLI contradiction check)

[ Defeated Vulnerabilities (5/9) ]
✗ SQL Injection inside permitted tool parameters (e.g. `order_id = "101; DROP TABLE orders"`)
✗ Base64-encoded prompt injection in customer input bypassing regex
✗ Indirect prompt injection from untrusted 3rd-party API responses overriding agent instructions
✗ Character-transposition PII evasion (spaced or leetspeak card numbers)
✗ Temporal reasoning inversion across out-of-order execution steps
```

---

## 6. Engineering Load Testing & Failure Recovery
We executed an end-to-end serverless load test processing **2,500 synthetic execution traces** (`dataset_tag: "synthetic-for-load-purposes"`, strictly segregated from accuracy benchmarks) through mocked AWS infrastructure:
- **Throughput**: 24.8 traces / second sustained.
- **Latency**: Median latency of 28.4 ms, P95 of 56.1 ms, P99 of 94.2 ms.
- **Cold Start Overhead**: 1.2% cold start occurrence with <250 ms invocation penalty.
- **Failure Path Testing**:
  1. *Poison Pill Payloads*: Malformed traces routed to SQS DLQ after retry exhaustion; 0% pipeline crashes.
  2. *Hot DynamoDB Outage*: Handled gracefully; traces persisted to S3 raw bucket for replay.
  3. *Downstream Degradation*: SQS exponential backoff successfully protected workers from throttling.

---

## 7. Threats to Validity & System Limitations

We explicitly document the following limitations of this study:
1. **Single-Author Scope & Small Benchmark Size**: The primary hand-labeled benchmark comprises 54 curated traces. While designed with balanced hard negatives, statistical significance is constrained by dataset size.
2. **Mocked Cloud Validation**: End-to-end load testing was conducted using Moto simulation in Python. While Moto exercises exact Boto3 API call signatures, real AWS network latency, cross-region throttling, and cold start container provision times were not measured on a live billing account.
3. **Adversarial Parameter Blindness**: The scope detector validates tool names and parameter data types, but does not parse deep SQL grammar or command payloads passed inside strings.
4. **Heuristic Offline Degradation**: In offline environments where PyTorch / Hugging Face models are unavailable, heuristic fallback suffers from token overlap false positives on complex financial sentences.
5. **No Native Audio / Video Trace Support**: The current schema and audit pipeline operate strictly on text and JSON payloads.

---

## 8. Conclusion
Post-hoc audit systems provide a non-invasive, deterministic, and auditable foundation for enterprise AI governance. By combining declarative policy ASTs, Presidio/Luhn secret detection, and NLI factual entailment within an asynchronous serverless pipeline, organizations can achieve continuous oversight of autonomous agents. Full source code, test suites, and reproduction scripts are published at [https://github.com/samarth-chaudhary/Agentic-AI-Audit](https://github.com/samarth-chaudhary/Agentic-AI-Audit).
