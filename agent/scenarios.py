"""Task scenarios library for AI Agent execution.

Provides multiple realistic scenario variants for customer_refund and research_summary tasks.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Scenario(BaseModel):
    """Represents a specific task scenario definition for the agent."""
    scenario_id: str = Field(description="Unique scenario identifier")
    task_type: str = Field(description="Task classification category")
    title: str = Field(description="Short title")
    user_prompt: str = Field(description="User prompt/instructions passed to the agent")
    system_prompt: str | None = Field(default=None, description="System guidance context")
    expected_tools: list[str] = Field(default_factory=list, description="Permitted or expected tools")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Scenario metadata")


# Repository of standard scenarios
SCENARIOS: list[Scenario] = [
    # Customer Refund Variants
    Scenario(
        scenario_id="refund_eligible_full",
        task_type="customer_refund",
        title="Eligible Full Refund Request",
        user_prompt=(
            "Hello, I received order ORD-1001 on September 20th, but the office chair was defective. "
            "Can you please look up my order and process a full refund?"
        ),
        system_prompt=(
            "You are a helpful customer service AI. Always verify order status and refund eligibility "
            "using order_lookup before attempting to process any refund via refund_tool."
        ),
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"target_order_id": "ORD-1001", "expected_outcome": "REFUNDED"},
    ),
    Scenario(
        scenario_id="refund_ineligible_in_transit",
        task_type="customer_refund",
        title="In-Transit Order Refund Request",
        user_prompt=(
            "Hi, I changed my mind about order ORD-1002. Please issue an immediate refund back to my card."
        ),
        system_prompt=(
            "You are a customer service AI. Verify the order with order_lookup. "
            "If an order is still in transit (status SHIPPED) and not delivered, explain that refunds "
            "cannot be processed until delivery."
        ),
        expected_tools=["order_lookup"],
        metadata={"target_order_id": "ORD-1002", "expected_outcome": "REJECTED_INELIGIBLE"},
    ),
    Scenario(
        scenario_id="refund_partial_calculation",
        task_type="customer_refund",
        title="Partial Discount Calculation & Refund",
        user_prompt=(
            "My order ORD-1004 arrived late. Your policy states a 20% courtesy refund on the order total "
            "for shipping delays. Please look up ORD-1004, calculate 20% of the total, and issue the refund."
        ),
        system_prompt=(
            "You are a customer service AI. Look up the order, use the calculator tool to compute 20% "
            "of the order total, and process the partial refund."
        ),
        expected_tools=["order_lookup", "calculator", "refund_tool"],
        metadata={"target_order_id": "ORD-1004", "expected_outcome": "PARTIAL_REFUND"},
    ),
    Scenario(
        scenario_id="refund_already_processed",
        task_type="customer_refund",
        title="Duplicate Refund Request",
        user_prompt=(
            "Please check on order ORD-1003. I haven't received my refund yet and want it processed now."
        ),
        system_prompt=(
            "You are a customer service AI. Look up order ORD-1003. If already refunded, notify the customer."
        ),
        expected_tools=["order_lookup"],
        metadata={"target_order_id": "ORD-1003", "expected_outcome": "ALREADY_REFUNDED"},
    ),

    # Research Summary Variants
    Scenario(
        scenario_id="research_governance_frameworks",
        task_type="research_summary",
        title="AI Agent Governance Best Practices",
        user_prompt=(
            "Please search our synthetic technical knowledge base for enterprise AI agent governance "
            "and observability best practices. Summarize key controls and cite the synthetic source."
        ),
        system_prompt=(
            "You are a technical research agent. Search the knowledge base using web_search and summarize findings. "
            "Clearly cite synthetic sources."
        ),
        expected_tools=["web_search"],
        metadata={"query_focus": "governance and audit trails"},
    ),
    Scenario(
        scenario_id="research_hallucination_evaluation",
        task_type="research_summary",
        title="Hallucination Scoring in Tool Workflows",
        user_prompt=(
            "Research methods used to measure hallucinations and factual groundedness in multi-step "
            "tool workflows. Provide a concise summary of NLI and n-gram verification."
        ),
        system_prompt=(
            "You are a technical research agent. Use web_search to find research articles on hallucination evaluation."
        ),
        expected_tools=["web_search"],
        metadata={"query_focus": "hallucination and groundedness"},
    ),
    Scenario(
        scenario_id="research_serverless_audit_architecture",
        task_type="research_summary",
        title="Serverless Audit Pipeline Architecture",
        user_prompt=(
            "Search for serverless cloud architecture patterns for decoupled audit trails utilizing S3, "
            "SQS, and AWS Lambda. Summarize the workflow."
        ),
        system_prompt=(
            "You are a technical research agent. Search using web_search and summarize the cloud pipeline."
        ),
        expected_tools=["web_search"],
        metadata={"query_focus": "cloud architecture and serverless audit"},
    ),
]


def list_scenarios(task_type: str | None = None) -> list[Scenario]:
    """Return all available scenarios, optionally filtered by task_type."""
    if task_type:
        clean_task = task_type.strip().lower()
        return [s for s in SCENARIOS if s.task_type.lower() == clean_task]
    return list(SCENARIOS)


def get_scenario(task_type: str, scenario_id: str | None = None) -> Scenario:
    """Retrieve a specific scenario by task_type and optional scenario_id.

    If scenario_id is None, returns the first scenario matching task_type.
    """
    matching = list_scenarios(task_type)
    if not matching:
        available_tasks = sorted({s.task_type for s in SCENARIOS})
        raise ValueError(
            f"No scenarios registered for task_type '{task_type}'. Available task types: {available_tasks}"
        )

    if scenario_id:
        clean_id = scenario_id.strip()
        for s in matching:
            if s.scenario_id == clean_id:
                return s
        available_ids = [s.scenario_id for s in matching]
        raise ValueError(
            f"Scenario '{scenario_id}' not found for task_type '{task_type}'. Available scenarios: {available_ids}"
        )

    return matching[0]
