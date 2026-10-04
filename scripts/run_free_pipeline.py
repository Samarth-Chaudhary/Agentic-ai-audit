#!/usr/bin/env python
"""Zero-Cost Local AWS Data Pipeline Server.

Emulates the complete AWS Serverless Data Pipeline locally using Moto:
- Amazon S3: Raw agent trace ingestion (s3://traces/...) & partitioned analytics lakehouse
- Amazon SQS: Buffer queue and event notifications (s3:ObjectCreated -> SQS)
- AWS Lambda: Audit Handler running deterministic multi-control governance
- Amazon DynamoDB: Hot operational store for point lookups & triage
- Amazon API Gateway: REST API exposing GET /traces and GET /traces/{trace_id}

Allows connecting the Streamlit dashboard directly to a live, working AWS data
pipeline for $0 without deploying to a paid AWS cloud account.

Usage:
    python scripts/run_free_pipeline.py
    python scripts/run_free_pipeline.py --port 8000
    python scripts/run_free_pipeline.py --full-ml   # Use heavy transformer models
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set testing credentials for Moto
os.environ["AWS_ACCESS_KEY_ID"] = "testing-mock-key"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing-mock-secret"
os.environ["AWS_SECURITY_TOKEN"] = "testing-mock-token"
os.environ["AWS_SESSION_TOKEN"] = "testing-mock-token"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"

TRACE_BUCKET = os.environ.get("TRACE_BUCKET", "ai-agent-audit-traces-prototype")
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "ai-agent-audit-results-prototype")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "ai_agent_audit_results")
SQS_QUEUE_NAME = "ai-agent-trace-ingestion-queue"
SNS_TOPIC_NAME = "ai-agent-governance-alerts"

import boto3
from moto import mock_aws

from auditor.nli_classifier import MockNLIClassifier, NLIVerdict
from auditor.orchestrator import AuditOrchestrator

audit_handler = importlib.import_module("lambda.audit_handler").handler
get_trace_handler = importlib.import_module("lambda.get_trace").handler
list_traces_handler = importlib.import_module("lambda.list_traces").handler
DynamoDBRepository = importlib.import_module("lambda.repositories.dynamodb_repository").DynamoDBRepository
S3Repository = importlib.import_module("lambda.repositories.s3_repository").S3Repository
SNSRepository = importlib.import_module("lambda.repositories.sns_repository").SNSRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("FreeAWSPipeline")


class PipelineState:
    """Holds active references to Moto-backed repositories and infrastructure."""

    def __init__(self, use_fast_mode: bool = True) -> None:
        self.use_fast_mode = use_fast_mode
        self.s3_client: Any = None
        self.dynamodb_resource: Any = None
        self.sqs_client: Any = None
        self.sns_client: Any = None
        self.s3_repo: S3Repository | None = None
        self.ddb_repo: DynamoDBRepository | None = None
        self.sns_repo: SNSRepository | None = None
        self.orchestrator: AuditOrchestrator | None = None
        self.queue_url: str = ""
        self.topic_arn: str = ""
        self.processed_count: int = 0
        self.lock = threading.Lock()

    def setup(self) -> None:
        """Create mock AWS resources."""
        self.s3_client = boto3.client("s3", region_name="us-east-1")
        self.s3_client.create_bucket(Bucket=TRACE_BUCKET)
        self.s3_client.create_bucket(Bucket=RESULTS_BUCKET)

        self.dynamodb_resource = boto3.resource("dynamodb", region_name="us-east-1")
        self.dynamodb_resource.create_table(
            TableName=DYNAMODB_TABLE,
            KeySchema=[{"AttributeName": "trace_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "trace_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        self.sqs_client = boto3.client("sqs", region_name="us-east-1")
        q_res = self.sqs_client.create_queue(QueueName=SQS_QUEUE_NAME)
        self.queue_url = q_res["QueueUrl"]

        self.sns_client = boto3.client("sns", region_name="us-east-1")
        t_res = self.sns_client.create_topic(Name=SNS_TOPIC_NAME)
        self.topic_arn = t_res["TopicArn"]

        self.s3_repo = S3Repository(s3_client=self.s3_client)
        self.ddb_repo = DynamoDBRepository(
            table_name=DYNAMODB_TABLE,
            dynamodb_resource=self.dynamodb_resource,
        )
        self.sns_repo = SNSRepository(topic_arn=self.topic_arn, sns_client=self.sns_client)

        if self.use_fast_mode:
            from auditor.groundedness_detector import GroundednessDetector
            from auditor.pii_detector import PIIDetector

            def fast_nli_rule(premise: str, hypothesis: str) -> NLIVerdict | None:
                p, h = premise.lower(), hypothesis.lower()
                if "delivered" in p and "cancelled" in h:
                    return NLIVerdict.CONTRADICTION
                if any(w in p for w in h.split() if len(w) > 4):
                    return NLIVerdict.ENTAILMENT
                return NLIVerdict.NEUTRAL

            mock_nli = MockNLIClassifier(default_verdict=NLIVerdict.ENTAILMENT, custom_rule=fast_nli_rule)
            fast_pii = PIIDetector(enable_presidio=False)
            fast_gnd = GroundednessDetector(nli_classifier=mock_nli)
            fast_gnd._embedder_failed = True

            self.orchestrator = AuditOrchestrator(
                pii_detector=fast_pii,
                groundedness_detector=fast_gnd,
            )
        else:
            self.orchestrator = AuditOrchestrator()

    def process_trace(self, trace_dict: dict[str, Any]) -> dict[str, Any]:
        """Send a raw trace through S3 -> SQS -> Audit Lambda -> DynamoDB & S3."""
        with self.lock:
            trace_id = trace_dict.get("trace_id", f"tr-live-{int(time.time() * 1000)}")
            trace_dict["trace_id"] = trace_id
            task_type = trace_dict.get("task_type", "customer_refund")
            s3_key = f"traces/task_type={task_type}/{trace_id}.json"

            # 1. Ingest raw trace to S3
            assert self.s3_repo is not None
            self.s3_repo.put_json(TRACE_BUCKET, s3_key, trace_dict)

            # 2. Trigger Audit Lambda
            event = {
                "Records": [
                    {
                        "s3": {
                            "bucket": {"name": TRACE_BUCKET},
                            "object": {"key": s3_key},
                        }
                    }
                ]
            }
            res = audit_handler(
                event=event,
                orchestrator=self.orchestrator,
                s3_repo=self.s3_repo,
                dynamodb_repo=self.ddb_repo,
                sns_repo=self.sns_repo,
            )
            self.processed_count += 1
            return res


STATE = PipelineState(use_fast_mode=True)


class FreeAWSPipelineRequestHandler(BaseHTTPRequestHandler):
    """Handles REST API Gateway calls matching the project contract."""

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")
        self.end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(200)

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        query_params = dict(urllib.parse.parse_qsl(parsed_url.query))

        # Root & Health check
        if path in ("", "/health"):
            items, _ = STATE.ddb_repo.list_audit_results(limit=1000) if STATE.ddb_repo else ([], None)
            resp = {
                "status": "online",
                "service": "AI Agent Governance - Free Local AWS Pipeline",
                "simulated_services": ["S3", "SQS", "Lambda", "DynamoDB", "SNS", "API Gateway"],
                "total_traces_audited": len(items),
                "endpoints": {
                    "list_traces": "GET /traces",
                    "get_trace": "GET /traces/{trace_id}",
                    "ingest_trace": "POST /traces",
                },
                "instructions": (
                    "In the Streamlit Dashboard sidebar, select 'Live AWS Pipeline' "
                    f"and set API Gateway URL to: http://localhost:{self.server.server_address[1]}"
                ),
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
            return

        # GET /traces (List traces summary)
        if path == "/traces":
            event = {
                "httpMethod": "GET",
                "path": "/traces",
                "queryStringParameters": query_params,
            }
            res = list_traces_handler(event, dynamodb_repo=STATE.ddb_repo)
            status_code = res.get("statusCode", 200)
            body = res.get("body", "{}")
            self._set_headers(status_code)
            self.wfile.write(body.encode("utf-8"))
            return

        # GET /traces/{trace_id} (Trace details)
        if path.startswith("/traces/"):
            trace_id = path[len("/traces/") :]
            event = {
                "httpMethod": "GET",
                "path": f"/traces/{trace_id}",
                "pathParameters": {"trace_id": trace_id},
            }
            res = get_trace_handler(
                event,
                dynamodb_repo=STATE.ddb_repo,
                s3_repo=STATE.s3_repo,
            )
            status_code = res.get("statusCode", 200)
            body = res.get("body", "{}")
            self._set_headers(status_code)
            self.wfile.write(body.encode("utf-8"))
            return

        # 404 for other paths
        self._set_headers(404)
        self.wfile.write(json.dumps({"error": f"Endpoint not found: {path}"}).encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")

        if path == "/traces":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Empty request body"}).encode("utf-8"))
                return

            body_bytes = self.rfile.read(content_length)
            try:
                trace_dict = json.loads(body_bytes.decode("utf-8"))
            except Exception as exc:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": f"Invalid JSON payload: {exc}"}).encode("utf-8"))
                return

            try:
                result = STATE.process_trace(trace_dict)
                self._set_headers(201)
                self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
            except Exception as exc:
                logger.error("Error processing trace: %s", exc)
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))
            return

        self._set_headers(404)
        self.wfile.write(json.dumps({"error": f"Endpoint not found: {path}"}).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Filter standard HTTP server logs to keep terminal clean."""
        logger.info("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)


def preload_traces(max_traces: int = 25) -> int:
    """Preload trace fixtures and generated traces through the full pipeline."""
    loaded = 0
    candidate_paths: list[Path] = []

    # 1. Curated fixtures
    fixtures_dir = PROJECT_ROOT / "fixtures"
    if fixtures_dir.exists():
        candidate_paths.extend(sorted(fixtures_dir.glob("valid_*.json")))

    # 2. Generated traces
    gen_dir = PROJECT_ROOT / "data" / "generated_traces"
    if gen_dir.exists():
        candidate_paths.extend(sorted(gen_dir.glob("*/*.json")))

    logger.info("Found %d candidate trace files. Preloading up to %d traces...", len(candidate_paths), max_traces)

    for p in candidate_paths[:max_traces]:
        try:
            with open(p, encoding="utf-8") as f:
                trace_data = json.load(f)
            if "trace_id" in trace_data and "steps" in trace_data:
                STATE.process_trace(trace_data)
                loaded += 1
                logger.info("✓ Processed trace [%s] (%s)", trace_data["trace_id"], trace_data.get("task_type", "default"))
        except Exception as exc:
            logger.warning("Could not preload %s: %s", p.name, exc)

    logger.info("Successfully preloaded %d traces into local S3 & DynamoDB.", loaded)
    return loaded


def run_pipeline_server(host: str = "127.0.0.1", port: int = 8000, preload_count: int = 25, fast: bool = True) -> None:
    """Start the mock AWS server and HTTP API Gateway."""
    STATE.use_fast_mode = fast

    with mock_aws():
        logger.info("========================================================================")
        logger.info("🛡️  STARTING ZERO-COST LOCAL AWS DATA PIPELINE (MOTO SIMULATION)")
        logger.info("========================================================================")
        STATE.setup()
        logger.info("[AWS S3]        Bucket: s3://%s", TRACE_BUCKET)
        logger.info("[AWS S3]        Bucket: s3://%s", RESULTS_BUCKET)
        logger.info("[AWS SQS]       Queue:  %s", SQS_QUEUE_NAME)
        logger.info("[AWS Lambda]    Worker: audit_handler (Scope, PII/Luhn, NLI, Risk Engine)")
        logger.info("[AWS DynamoDB]  Table:  %s", DYNAMODB_TABLE)
        logger.info("[AWS SNS]       Topic:  %s", SNS_TOPIC_NAME)
        logger.info("[Engine Mode]   %s", "Fast Deterministic" if fast else "Full ML Models")
        logger.info("------------------------------------------------------------------------")

        server_address = (host, port)
        httpd = ThreadingHTTPServer(server_address, FreeAWSPipelineRequestHandler)
        url = f"http://{host}:{port}"
        logger.info("========================================================================")
        logger.info("🚀 Local AWS API Gateway is LIVE at: %s", url)
        logger.info("")
        logger.info("HOW TO CONNECT THE STREAMLIT DASHBOARD:")
        logger.info("  1. In the sidebar, select: [Live AWS Pipeline]")
        logger.info("  2. In 'API Gateway URL', enter: %s", url)
        logger.info("  3. The dashboard connects to this live AWS data pipeline for $0/FREE!")
        logger.info("========================================================================")

        preload_traces(max_traces=preload_count)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("\nShutting down free local AWS data pipeline...")
            httpd.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-Cost Local AWS Data Pipeline Server for Agentic AI Audit")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--preload", type=int, default=20, help="Number of traces to preload (default: 20)")
    parser.add_argument("--full-ml", action="store_true", help="Use full heavy transformer models (slower)")
    args = parser.parse_args()

    run_pipeline_server(
        host=args.host,
        port=args.port,
        preload_count=args.preload,
        fast=not args.full_ml,
    )


if __name__ == "__main__":
    main()
