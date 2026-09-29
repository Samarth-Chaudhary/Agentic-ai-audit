# Deployment Guide: AI Agent Governance & Audit Trail Analyzer

This guide details the procedure for provisioning cloud infrastructure, deploying serverless workloads, generating agent traces, and launching the governance analytics dashboard.

---

## 1. Prerequisites

Before starting deployment, ensure the following tooling and accounts are configured:

- **AWS CLI**: v2.15+ configured with administrative credentials (`aws configure`).
- **Terraform**: v1.5.0+ installed and available on system `PATH`.
- **Python**: v3.10 or v3.11 with `pip` and virtual environment support (`venv`).
- **Docker**: (Optional) required only if packaging the audit Lambda runtime as a container image.
- **Node.js / npm**: (Optional) required if deploying frontend or supplementary tool wrappers.
- **Hugging Face / OpenAI API Key**: Configured if using remote LLM inference and embeddings.

---

## 2. Environment Variables

Set the following environment variables in your terminal or `.env` file prior to provisioning and local execution:

```bash
# AWS Identity & Region
export AWS_DEFAULT_REGION="us-east-1"
export AWS_REGION="us-east-1"

# Infrastructure Resource Names (Aligned with Terraform defaults)
export ENVIRONMENT="dev"
export DYNAMODB_TABLE_NAME="AgentAuditResults"
export RAW_TRACE_BUCKET="agent-audit-raw-traces-dev"
export AUDIT_RESULTS_BUCKET="agent-audit-analytics-results-dev"
export ATHENA_DATABASE="agent_audit_analytics"
export ATHENA_WORKGROUP="agent_audit_workgroup"
export ATHENA_RESULTS_BUCKET="agent-audit-analytics-results-dev"

# Model & Provider Configuration (Optional for mock mode)
export OPENAI_API_KEY="sk-..."
export HUGGINGFACE_TOKEN="hf_..."

# Dashboard & API Configuration
export API_BASE_URL="http://localhost:8000"
```

---

## 3. Terraform Infrastructure Provisioning

All cloud infrastructure is declared in HCL under [`terraform/`](../terraform/).

### 3.1 Initialize Terraform
Initialize providers and backend configurations:

```bash
cd terraform
terraform init
```

### 3.2 Validate Configuration
Verify that all HCL declarations, variable definitions, and provider schemas are syntactically valid:

```bash
terraform validate
```

### 3.3 Generate Execution Plan
Generate an execution plan to preview resource creations across S3, SQS, SNS, DynamoDB, Lambda, Glue, and Athena:

```bash
terraform plan -var="environment=dev" -out=tfplan
```

### 3.4 Apply Infrastructure Changes
Execute the planned changes against your configured AWS account:

```bash
terraform apply tfplan
```

*Note: Infrastructure outputs will display the provisioned bucket names, SQS queue URLs, DynamoDB table ARN, API Gateway endpoint URL, and Athena workgroup.*

---

## 4. Agent Trace Generation

Generate representative execution traces using the agent CLI runner:

### 4.1 Run Customer Refund Agent Task
```bash
python scripts/run_agent.py \
  --task-type "customer_refund" \
  --user-prompt "Customer requested a full refund of $120.00 for order ord-9821." \
  --output "fixtures/generated_refund_trace.json"
```

### 4.2 Run Research Summary Agent Task
```bash
python scripts/run_agent.py \
  --task-type "research_summary" \
  --user-prompt "Summarize recent findings on transformer attention mechanisms." \
  --output "fixtures/generated_research_trace.json"
```

---

## 5. Trace Upload to S3 Ingestion Bucket

Upload raw trace JSON files to the raw traces S3 bucket. Uploading to this prefix triggers the S3 `ObjectCreated` event, enqueueing the trace in Amazon SQS:

```bash
aws s3 cp fixtures/generated_refund_trace.json \
  s3://$RAW_TRACE_BUCKET/traces/task_type=customer_refund/year=2026/month=09/day=28/generated_refund_trace.json
```

To ingest all sample fixtures in batch:

```bash
aws s3 sync fixtures/ \
  s3://$RAW_TRACE_BUCKET/traces/task_type=sample_fixtures/year=2026/month=09/day=28/ \
  --exclude "*" \
  --include "*.json"
```

---

## 6. Athena & Glue Prerequisites

Before running analytical SQL queries across the audit results in Amazon Athena, ensure the Glue Catalog and Athena workgroups are initialized:

1. **Athena Query Result Location**: Athena requires an S3 output location for query execution results. Ensure the S3 bucket exists and the workgroup is configured:
   ```bash
   aws athena update-work-group \
     --work-group agent_audit_workgroup \
     --configuration-updates "ResultConfigurationUpdates={OutputLocation=s3://$AUDIT_RESULTS_BUCKET/athena-results/}"
   ```
2. **Execute Glue Crawler**: Run the crawler to discover newly partitioned audit result objects and register the table schema:
   ```bash
   aws glue start-crawler --name agent-audit-crawler-dev
   ```
3. **Verify Table Schema**: Confirm the `audit_analytics` table is queryable in Athena:
   ```bash
   aws athena start-query-execution \
     --query-string "MSCK REPAIR TABLE agent_audit_analytics.audit_analytics;" \
     --query-execution-context Database=agent_audit_analytics \
     --work-group agent_audit_workgroup
   ```

---

## 7. Launching the Governance Dashboard

The interactive governance dashboard runs on Streamlit and connects to both DynamoDB (for live operational records) and Athena (for historical analytical aggregations):

```bash
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
```

Once launched, navigate to `http://localhost:8501` to view:
- **Executive KPI Cards**: Total traces audited, high-risk flags, average groundedness score.
- **Trace Triage & Redacted Inspection**: Line-by-line inspection of tool calls with sensitive data masked.
- **Longitudinal Trend Analytics**: Model hallucination rates and scope violation distributions.
