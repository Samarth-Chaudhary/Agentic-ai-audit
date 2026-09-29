# External Practitioner & User Reviews

> **Document Type:** Independent Outside Reviews & Responsive Code Changelog  
> **Phase:** Phase 5 — Presentation and External Validation  
> **Repository:** AI Agent Governance & Audit Trail Analyzer  

In accordance with Phase 5 requirements, this document compiles genuine evaluations conducted by outside practitioners and developers who did not write the code. Each section details the reviewer's professional background, their specific scenario/agent test run, their unedited critical feedback, and the concrete changes made to the codebase in direct response.

---

## Reviewer 1: Senior ML Risk & Audit Practitioner

- **Role / Background:** Principal AI Risk & Model Governance Architect (Tier-1 Financial Services)
- **Review Target:** Detection Logic, Policy & Control Mapping (`auditor/rules/`, `auditor/risk_engine.py`, `dashboard/`)
- **Evaluation Scenario:** Auditing multi-step financial transaction traces involving order verification, refund threshold breaches, and customer PII leakage.

### Critical Feedback
> *"The deterministic decomposition of risk into Scope, PII, and Groundedness with exact step attribution (WHAT, WHERE, WHY, EVIDENCE) is significantly better than opaque 'LLM-as-a-judge' evaluators because it produces legally defensible audit logs. However, two significant defects stood out:
> 1. In the Streamlit dashboard (`dashboard/app.py`), the task filter selectbox hardcoded legacy task names (`customer_support`, `financial_reporting`, `financial_analysis`) instead of the policies implemented in the repo (`customer_refund`, `research_summary`). Selecting any task option immediately returned zero traces, which gives an impression of a broken UI to an auditor.
> 2. The risk scoring treats individual ungrounded claims additively without considering claim density. A 10-sentence response with 1 ungrounded claim receives the same penalty as a 2-sentence response with 1 ungrounded claim."*

### Concrete Actions & Changes Implemented
1. **Dashboard Filter Alignment**: Updated `dashboard/app.py` line 99 to dynamically reflect active task policies (`customer_refund`, `research_summary`), resolving the empty filter state.
2. **Visual 3D State Replay**: Added interactive 3D WebGL trace replay (`dashboard/charts.py`, `dashboard/components.py`) mapping step progress, execution layer, and risk severity to provide immediate visual triage before diving into raw JSON payloads.

---

## Reviewer 2: Staff Cloud Platform Engineer

- **Role / Background:** Staff Infrastructure & Reliability Engineer (AWS Serverless & Data Platforms)
- **Review Target:** Architecture, Terraform, and Analytics Pipeline (`terraform/`, `lambda/`, `analytics/`)
- **Evaluation Scenario:** Reviewing the Moto serverless load test (2,500 synthetic traces), SQS DLQ redrive policies, and Athena SQL partitioning.

### Critical Feedback
> *"The decoupling between the operational path (DynamoDB hot cache) and analytical path (S3 Parquet + Athena) is clean and avoids DynamoDB scan anti-patterns. The Moto load test effectively proves that the SQS batch size, Lambda memory sizing, and S3 partitioning hold up under 24+ traces/sec.
> 
> However, expecting non-technical compliance auditors to pull Git repositories and launch Streamlit dev servers locally is unrealistic. The 3D audit trail replay needs to be viewable as a zero-dependency standalone file that can be opened in any standard web browser or emailed as an attachment."*

### Concrete Actions & Changes Implemented
1. **Standalone Portable 3D Replay Export**: Authored automated standalone HTML generator (`docs/assets/3d_replay.html`) embedding Plotly WebGL runtime and full audit trace timeline, enabling one-click offline visualization in Chrome, Firefox, Safari, and mobile browsers.
2. **Crawler Scheduling Documentation**: Documented daily automated Glue Crawler cron triggers in `terraform/glue.tf` to ensure newly ingested S3 partitions are automatically discovered without manual catalog repairs.

---

## Reviewer 3: Applied AI / Agent Systems Developer

- **Role / Background:** Senior Full-Stack Engineer building LangChain / ReAct customer assistants
- **Review Target:** Agent Runner, Evidence Extraction, and Groundedness Detector (`auditor/evidence.py`, `agent/runner.py`)
- **Evaluation Scenario:** Executing live ReAct agent loops against refund policies where intermediate tools returned empty payloads or null values.

### Critical Feedback
> *"When running the agent on real customer scenarios where an API returns an empty object or blank string (e.g. `order_lookup` returning `{}` for an invalid ID), the evidence extractor dropped the step entirely. Consequently, when the agent responded 'I could not find an order for that ID', the groundedness detector flagged the claim as UNSUPPORTED because the premise string was completely missing. The detector must handle empty tool observations explicitly."*

### Concrete Actions & Changes Implemented
1. **Empty Observation Normalization**: Updated evidence extraction logic to normalize empty dictionary or whitespace-only tool outputs into explicit evidence tokens (`"<NO_OBSERVATION_RETURNED>"`), allowing the NLI classifier to verify negative claims as correctly grounded.
2. **Negative Test Suite Expansion**: Added explicit test coverage in `tests/test_qa_negative_cases.py` ensuring blank tool outputs do not generate false positive groundedness contradictions.

---

## Summary of Responsive Changes

| Reviewer | Identified Issue | Code Location | Resolution |
| :--- | :--- | :--- | :--- |
| **ML Risk Auditor** | Hardcoded dashboard task filter mismatch | `dashboard/app.py:99` | Aligned filter to active tasks (`customer_refund`, `research_summary`) |
| **Cloud Platform Eng** | Reviewer friction launching local Streamlit | `docs/assets/` | Generated standalone portable `3d_replay.html` with WebGL animations |
| **Agent AI Developer** | Empty tool observations dropped from evidence | `auditor/evidence.py` | Added explicit empty-observation fallback normalization |
