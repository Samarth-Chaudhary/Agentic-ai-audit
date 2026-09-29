# AI Agent Governance & Audit Trail Analyzer

An automated, post-hoc governance, risk assessment, and audit trail analysis framework for autonomous AI agents.

---

## 1. Project Overview

The **AI Agent Governance & Audit Trail Analyzer** provides an enterprise-grade post-hoc inspection framework for autonomous AI agent executions. As language agents are deployed to interact with internal APIs, databases, customer workflows, and financial systems, organizations face significant compliance, security, and accuracy risks.

This project delivers end-to-end auditability across the lifecycle of an agent execution by decoupling trace collection from governance analysis. The framework ingests structured execution traces, evaluates them against declarative task policies, flags sensitive data disclosures, audits factual groundedness against verified tool outputs, computes composite multi-factor risk scores, and routes results to both an operational triage database and an analytical lakehouse.

---

## 2. Problem Statement

Autonomous agents operating on ReAct (Reason + Act) patterns present novel governance challenges:
1. **Scope Creep & Permission Abuse**: Agents may invoke unapproved tools, access unauthorized data sources, or execute tools beyond intended operational bounds.
2. **Business Rule Evasion**: Agents may bypass prerequisite business logic (e.g. issuing a financial refund without validating order status, or exceeding max allowable refund amounts).
3. **Sensitive Data Exposure (PII/DLP)**: Plaintext secrets, payment card numbers, AWS access keys, or personal customer data can leak into internal tool outputs or final customer responses.
4. **Factual Hallucination & Contradiction**: LLMs can hallucinate claims unsupported by tool observation evidence or, worse, directly contradict tool output (e.g. claiming a refund was approved when the backend returned a rejection).
5. **Audit Trail Opacity**: Lack of standardized, immutable trace capture prevents root-cause investigations, compliance reviews, and longitudinal risk monitoring.

---

## 3. Architecture: Operational & Analytical Paths

The system strictly decouples the high-velocity **Operational Path** from the longitudinal **Additive Analytics Path**:

```
                       [ Autonomous AI Agent (ReAct) ]
                                      │
                                      ▼ (Write Raw JSON Trace)
                      [ Amazon S3: Raw Trace Storage ]
                                      │
                                      ▼ (s3:ObjectCreated Notification)
                         [ Amazon SQS: Ingestion Buffer ]
                                      │
                                      ▼
                        [ AWS Lambda: Audit Worker ]
         ┌────────────────────────────┼───────────────────────────┐
         ▼                            ▼                           ▼
[ Scope Detector ]          [ PII / DLP Detector ]     [ Groundedness Detector ]
(Tool Whitelist, Limits,    (Regex, Presidio NLP,       (Semantic Embeddings,
 Business Constraints)      Luhn Checksum, Redaction)   NLI Entailment Check)
         │                            │                           │
         └────────────────────────────┼───────────────────────────┘
                                      ▼
                          [ Risk Scoring Engine ]
                     (Weighted Multi-Factor Scoring,
                       Tiers: LOW / MED / HIGH / CRIT)
                                      │
         ┌────────────────────────────┴───────────────────────────┐
         ▼ (Operational Path)                                     ▼ (Additive Analytics Path)
[ Amazon DynamoDB: Operational Store ]                   [ Amazon S3: Analytics Results ]
(Indexed by trace_id, task_type, risk_tier)              (Partitioned Parquet / JSON Lines)
         │                                                        │
         ▼                                                        ▼
[ Governance REST API (FastAPI) ]                       [ AWS Glue Data Catalog & Crawler ]
(Point Lookups, Operational Triage)                               │
                                                                  ▼
                                                        [ Amazon Athena (Presto SQL) ]
                                                                  │
                                                                  ▼
                                                  [ Streamlit Governance Dashboard ]
```

### Operational Path
- **S3 Raw Traces**: Write-once immutable trace storage (`traces/task_type={task}/year={YYYY}/month={MM}/day={DD}/{trace_id}.json`).
- **Amazon SQS & DLQ**: Buffers traffic bursts, ensures at-least-once delivery, and isolates poisoned messages.
- **Audit Lambda**: Serverless orchestrator executing the three detector pipelines concurrently, scoring risk, redacting PII, and persisting findings.
- **Amazon DynamoDB**: Hot operational record cache enabling single-digit millisecond lookups by `trace_id` and triage indexing by `risk_tier`.
- **Governance REST API**: FastAPI backend providing query endpoints for automated pipelines and operations teams.

### Additive Analytics Path
- **S3 Analytics Bucket**: Stores structured audit findings partitioned by date.
- **AWS Glue**: Automates schema discovery and table metadata synchronization.
- **Amazon Athena**: Serverless ANSI SQL engine executing fleet-wide queries, longitudinal trend analysis, and model accuracy comparisons.
- **Streamlit Dashboard**: Visualizes governance KPIs, fleet risk distributions, PII leakage types, and hallucination rates.

---

## 4. Trace Schema Contract

All agent traces conform strictly to the Draft 2020-12 JSON Schema in [`schemas/trace.schema.json`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/schemas/trace.schema.json).

```json
{
  "trace_id": "tr-2026-09-28-001",
  "task_type": "customer_refund",
  "session_id": "sess-abc-123",
  "agent_id": "support-agent-v1",
  "timestamp": "2026-09-28T09:00:00Z",
  "prompt": "Customer requested a $50 refund for damaged goods on order ord-101.",
  "steps": [
    {
      "step_index": 1,
      "thought": "I need to look up order details first.",
      "tool_name": "order_lookup",
      "tool_input": {"order_id": "ord-101"},
      "output": {"found": true, "order_id": "ord-101", "total_amount": 120.00, "status": "DELIVERED"},
      "duration_ms": 145
    },
    {
      "step_index": 2,
      "thought": "Order verified. Processing refund of $50.",
      "tool_name": "process_refund",
      "tool_input": {"order_id": "ord-101", "amount": 50.00},
      "output": {"success": true, "refund_id": "ref-4912"},
      "duration_ms": 210
    }
  ],
  "final_answer": "Your refund of $50.00 for order ord-101 has been processed successfully.",
  "execution_time_ms": 1250,
  "status": "COMPLETED"
}
```

---

## 5. Agent Execution Loop

The agent implementation ([`agent/`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/agent)) runs a constrained ReAct loop:
- **Observable Logging**: Intercepts every reasoning step, tool call input, tool response, and duration.
- **Safety Boundary**: Strips internal agent secret variables and isolates reasoning from user-visible outputs.
- **Tool Sandbox**: Dispatches tool calls only to configured tools (e.g. `order_lookup`, `process_refund`, `web_search`, `calculator`).

---

## 6. Governance & Audit Controls

### 6.1 Scope Control ([`auditor/scope_detector.py`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/auditor/scope_detector.py))
- **Tool Permission Whitelist**: Validates tool calls against declarative task policy (`config/task_policies.yaml`).
- **Call Bounds**: Prevents infinite loops by enforcing per-tool and per-trace maximum execution limits.
- **Domain Business Rules**:
  - Requires `order_lookup` to precede `process_refund` with matching order identifiers.
  - Verifies refund amounts do not exceed the historical order total or policy maximums.

### 6.2 Sensitive Data / PII / DLP ([`auditor/pii_detector.py`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/auditor/pii_detector.py))
- **Deterministic Regex Patterns**: Scans for AWS credentials (`AKIA...`), GitHub tokens, passwords, emails, and phone numbers.
- **Luhn Algorithm Checksum**: Validates 13-19 digit candidate payment card numbers to prevent false positives on random numeric IDs.
- **Microsoft Presidio NLP**: Recognizes entity types (`PERSON`, `LOCATION`, `ORGANIZATION`).
- **Trace Redactor** ([`auditor/redactor.py`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/auditor/redactor.py)): Masks sensitive entities into tokens (`[REDACTED_EMAIL]`, `[REDACTED_CARD_NUMBER]`) for safe analytics storage.

### 6.3 Groundedness & Hallucination Detection ([`auditor/groundedness_detector.py`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/auditor/groundedness_detector.py))
- **Claim Extraction**: Extracts atomic factual claims from `final_answer`.
- **Semantic Evidence Retrieval**: Embeds tool outputs and claims using `sentence-transformers/all-MiniLM-L6-v2` with cosine similarity retrieval.
- **Natural Language Inference (NLI)**: Uses cross-encoder NLI (`roberta-large-mnli`) to verify whether tool observations entail, do not support, or contradict the agent's assertions.
- **Verdict Mapping**:
  - `ENTAILMENT` $\to$ **`SUPPORTED`** (Grounded factual assertion).
  - `NEUTRAL` $\to$ **`UNSUPPORTED`** (Hallucination or unverified claim).
  - `CONTRADICTION` $\to$ **`CONTRADICTED`** (Critical factual conflict).

### 6.4 Composite Risk Scoring Engine ([`auditor/risk_engine.py`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/auditor/risk_engine.py))
- **Normalized Sub-Scores**:
  - Scope Score: 0 to 100 based on violation severities (CRITICAL=50, HIGH=30, MEDIUM=15, LOW=5).
  - PII Score: 0 to 100 based on detected sensitive disclosure severities.
  - Groundedness Score: Proportional penalty for contradicted (1.0) and unsupported (0.7) claims.
- **Composite Score**: Configured weighted combination (Scope: 0.35, PII: 0.35, Groundedness: 0.30).
- **Categorical Risk Tiers**:
  - `LOW`: Score < 20.0
  - `MEDIUM`: 20.0 $\le$ Score < 50.0
  - `HIGH`: 50.0 $\le$ Score < 80.0
  - `CRITICAL`: Score $\ge$ 80.0
- **Deterministic Summary**: Generates factual explanations strictly explaining why the score was assigned.

---

## 7. Cloud Infrastructure (Terraform)

Infrastructure is managed as code under [`terraform/`](terraform/):
- `s3.tf`: Raw trace bucket and analytics results bucket with server-side encryption.
- `sqs.tf`: Ingestion queue and dead-letter queue with redrive policies.
- `lambda.tf`: Audit worker function, IAM roles, and SQS event source mapping.
- `dynamodb.tf`: Operational table with GSIs for `task_type` and `risk_tier`.
- `glue.tf` & `athena.tf`: Catalog database, crawler, and workgroup.
- `sns.tf`: Topic for high-risk alerts.
- `api_gateway.tf`: REST API exposing query endpoints.

---

## 8. REQUIRED REALITY CHECK SECTION

To preserve strict engineering honesty and truthfulness, the table below explicitly delineates what is fully implemented and verified in code versus what is synthetic, mocked, or unverified:

### REAL (Fully Implemented & Verified in Code)
- **Real LLM Behavior**: Full integration with OpenAI API when API keys are provided in environment.
- **Real Tool Calling**: ReAct loop dispatching to actual Python functions with argument parsing and execution timing.
- **Real Trace Capture**: Execution traces with nanosecond timing, step logging, and schema enforcement.
- **Actual Audit Logic**: Deterministic Scope checks, Presidio NLP PII scanning, Luhn Mod-10 algorithm, SentenceTransformer semantic embeddings, NLI classification, and weighted risk engine.
- **Fixture-Based Verification**: Comprehensive suite of 6 gold standard fixtures (valid customer refund, valid research summary, unauthorized tool, excessive refund, PII leak, contradicted answer) verified against explicit expected results.
- **Mocked AWS Infrastructure**: Full Moto test suite validating S3 object retrieval, SQS batch consumption, DynamoDB persistence, and SNS high-risk alerting.

### STUB / SYNTHETIC (In-Memory Demonstrations)
- **Demo Order Database**: In-memory dictionary of simulated customer orders (`ord-9821`, `ord-101`) for testing refund logic.
- **Demo Refund Backend**: Mock refund transaction processor recording successful or rejected refund status.
- **Demo Web Search**: Curated in-memory snippets simulating search engine results for research summary tasks.

### UNVERIFIED (Unless Tested Against Live AWS Account)
- **Real AWS Deployment**: Live Terraform deployment against an active AWS commercial account.
- **Live Amazon Athena**: Execution of queries against live S3 buckets using real Athena compute billing.
- **Live SNS SMS/Email Delivery**: Physical delivery of notifications to subscribed email addresses or phone numbers.
- **External Third-Party APIs**: External web services outside the local execution sandbox.

---

## 9. Comprehensive Limitations

In compliance with audit transparency standards, users and auditors must be aware of the following system constraints:
- **Post-Hoc Only**: Governance analysis occurs after trace generation; the auditor does not intercept or block live agent tool calls in-flight.
- **Single-Agent Scope**: Built and evaluated for single-agent, single-session executions; does not audit distributed multi-agent swarm conversations.
- **Single-Task Focus**: Optimized for discrete task workflows (`customer_refund`, `research_summary`); complex open-ended workflows require custom policy configuration.
- **Toy Backend Systems**: Integrates with simulated in-memory databases rather than production ERPs or payment gateways.
- **Heuristic Claim Extraction**: Final answer claim extraction relies on sentence splitting and clause extraction, which can occasionally miss implicit claims.
- **Embedding Threshold Calibration**: Semantic similarity cutoffs for tool output matching require empirical calibration per domain.
- **Imperfect NLI**: Pre-trained Natural Language Inference models may occasionally exhibit false negatives or misclassify complex negation.
- **PII False Positives / Negatives**: Regex patterns and NER models can miss obfuscated sensitive data or flag innocuous numerical tokens.
- **Policy Dependency**: Scope and business rule detection depends entirely on the completeness and rigor of `task_policies.yaml`.
- **Heuristic Risk Weighting**: Composite risk scoring is a weighted linear model calibrated to governance heuristics rather than actuarial loss models.
- **Not Universal Hallucination Detection**: Detects ungroundedness against observed tool evidence only; cannot verify claims grounded in external world knowledge not captured in the trace.

---

## 10. Control Matrix

For detailed mappings of compliance questions to technical controls, implementation files, and test references, see [`docs/control-matrix.md`](file:///c:/Users/Samarth%20Chaudhary/Downloads/Agentic%20AI%20Audit/docs/control-matrix.md).

---

## 11. Local Setup & Testing

### 11.1 Installation
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 11.2 Environment Configuration
Copy `.env.example` to `.env` and set testing variables:
```bash
cp .env.example .env
```

### 11.3 Run Tests
```bash
# Run full test suite with real models
pytest -v

# Run mocked AWS tests (Moto)
pytest tests/test_repositories.py tests/test_audit_handler.py -v

# Run fixture validation tests
pytest tests/test_fixtures_expected.py -v

# Run negative test scenarios
pytest tests/test_qa_negative_cases.py -v

# Run groundedness regression tests
pytest tests/test_groundedness_regression.py -v

# Run degraded mode tests
pytest tests/test_degraded_mode.py -v
```

### 11.4 Run Local Audit CLI
```bash
python scripts/run_audit_local.py fixtures/valid_customer_refund.json
```

### 11.5 Launch Dashboard
```bash
streamlit run dashboard/app.py
```

---

## 12. Repository Structure

The top-level repository tree strictly matches the active Git index with zero uncommitted scratch files or duplicate infrastructure directories:

```text
.
├── .env.example              # Environment variable configuration template
├── .github/                  # CI workflow definitions
│   └── workflows/
│       └── ci.yml            # Automated CI pipeline (lint, types, terraform, pytest)
├── .gitignore                # Exclusion rules for caches, artifacts, and local environments
├── CHANGELOG.md              # Chronological record of architectural fixes and enhancements
├── Dockerfile.lambda         # Container image definition for AWS Lambda deployment
├── Makefile                  # Automation shortcuts for testing, linting, and running
├── pyproject.toml            # Package build metadata, dependencies, and tool configs
├── README.md                 # Project documentation and architectural overview
├── requirements.txt          # Pinned Python package dependencies
├── agent/                    # Autonomous ReAct agent implementation and tool definitions
├── analytics/                # Presto/Athena SQL queries and analytics definitions
├── auditor/                  # Deterministic audit engine (Scope, PII, Groundedness, Risk Scoring)
├── config/                   # Task governance policies (task_policies.yaml) and risk scoring weights
├── dashboard/                # Reviewer Streamlit UI, visual components, charts, and API clients
├── data/                     # Sample generated agent traces and validation datasets
├── docs/                     # Architectural specifications, control matrix, and audit samples
├── fixtures/                 # Curated trace fixtures and golden audit results
├── lambda/                   # Serverless AWS Lambda handlers (audit worker, trace fetchers)
├── project/                  # Core project logging and utility modules
├── schemas/                  # Draft 2020-12 JSON Schema contracts for traces and audit results
├── scripts/                  # Local execution harnesses and Terraform resource validator
├── terraform/                # Canonical Terraform IaC modules (S3, SQS, DynamoDB, Lambda, Athena, Glue)
└── tests/                    # Complete test suite (unit, regression, negative, fixtures, mocked AWS, dashboard)
```
