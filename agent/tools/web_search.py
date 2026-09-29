"""Deterministic synthetic web search tool for AI Agent Governance.

BACKEND NOTICE: This searches over a local, static, synthetic article repository.
It does NOT make outbound internet queries or access live web data.
The source is explicitly identified as 'public_web_stub'.
"""

from __future__ import annotations

import re
from typing import Any

from agent.tools.base import BaseTool

# Local synthetic corpus
SYNTHETIC_WEB_CORPUS: list[dict[str, Any]] = [
    {
        "id": "doc-01",
        "title": "Autonomous AI Agent Governance & Observability Best Practices",
        "snippet": (
            "Modern enterprise AI governance mandates post-hoc audit trails for tool-calling agents. "
            "Key controls include continuous scope monitoring, sensitive PII entity redaction, "
            "and factual groundedness verification against observable tool outputs."
        ),
        "source": "public_web_stub",
        "date": "2026-03-15",
        "keywords": ["ai", "agent", "governance", "audit", "observability", "pii", "groundedness", "tools"],
    },
    {
        "id": "doc-02",
        "title": "Evaluating Hallucinations in Multi-Step Tool Workflows",
        "snippet": (
            "When autonomous agents synthesize final answers from tool execution results, "
            "n-gram similarity and natural language inference (NLI) scoring measure factual alignment. "
            "Claims unsupported by prior tool outputs are flagged as ungrounded."
        ),
        "source": "public_web_stub",
        "date": "2026-05-10",
        "keywords": ["hallucination", "groundedness", "nli", "tool", "workflow", "evaluation"],
    },
    {
        "id": "doc-03",
        "title": "Enterprise Cloud Architecture for Serverless Audit Trails",
        "snippet": (
            "Decoupled event-driven audit pipelines utilize S3 object notifications, SQS queuing, "
            "and AWS Lambda workers to achieve scalable, asynchronous governance processing without "
            "impacting agent execution latency."
        ),
        "source": "public_web_stub",
        "date": "2026-07-22",
        "keywords": ["cloud", "architecture", "aws", "lambda", "s3", "sqs", "serverless", "audit"],
    },
    {
        "id": "doc-04",
        "title": "Customer Service AI: Policies, Refunds, and Escalation Guardrails",
        "snippet": (
            "Customer-facing agents must adhere to strict business rules: order lookups must precede "
            "refund issuances, maximum refund thresholds must match original invoices, and financial "
            "transactions must record synthetic or audited ledger references."
        ),
        "source": "public_web_stub",
        "date": "2026-08-01",
        "keywords": ["customer", "service", "refund", "orders", "policy", "guardrails", "business"],
    },
]


class WebSearchTool(BaseTool):
    """Tool for querying a curated synthetic knowledge corpus."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search synthetic web articles and governance documentation over a local demo index. "
            "Returns relevant titles, snippets, synthetic sources, and publication dates."
        )

    @property
    def data_source(self) -> str:
        return "public_web_stub"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Keywords or search phrase to look up in synthetic corpus.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 3,
                    "description": "Maximum number of search results to return.",
                },
            },
            "additionalProperties": False,
        }

    def execute(self, query: str, max_results: int = 3, **kwargs: Any) -> dict[str, Any]:
        """Perform keyword matching against synthetic corpus."""
        clean_query = str(query).strip().lower()
        query_tokens = set(re.findall(r"\w+", clean_query))

        scored_results: list[tuple[int, dict[str, Any]]] = []

        for doc in SYNTHETIC_WEB_CORPUS:
            score = 0
            doc_keywords = set(doc.get("keywords", []))
            # Keyword overlap
            common = query_tokens.intersection(doc_keywords)
            score += len(common) * 3

            # Substring in title or snippet
            title_lower = doc["title"].lower()
            snippet_lower = doc["snippet"].lower()
            for token in query_tokens:
                if token in title_lower:
                    score += 2
                if token in snippet_lower:
                    score += 1

            if score > 0:
                result_entry = {
                    "title": doc["title"],
                    "snippet": doc["snippet"],
                    "source": "public_web_stub",
                    "date": doc.get("date"),
                }
                scored_results.append((score, result_entry))

        # Sort descending by score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        matched_items = [item for _, item in scored_results[:max_results]]

        # Fallback if no specific keyword matched: return top docs
        if not matched_items:
            matched_items = [
                {
                    "title": doc["title"],
                    "snippet": doc["snippet"],
                    "source": "public_web_stub",
                    "date": doc.get("date"),
                }
                for doc in SYNTHETIC_WEB_CORPUS[:max_results]
            ]

        return {
            "query": query,
            "results_count": len(matched_items),
            "results": matched_items,
            "data_source": self.data_source,
            "source_type": "public_web_stub",
        }
