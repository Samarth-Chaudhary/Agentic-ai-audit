"""Task scenarios library for AI Agent execution backed by authentic datasets.

Provides realistic scenario variants for customer_refund (backed by real Olist e-commerce orders)
and research_summary (backed by real SEC EDGAR XBRL corporate filings).
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


# Repository of standard and authentic scenarios
SCENARIOS: list[Scenario] = [
    # =========================================================================
    # Customer Refund Scenarios (Real Olist Dataset + Fixtures)
    # =========================================================================
    Scenario(
        scenario_id="olist_refund_delivered_housewares",
        task_type="customer_refund",
        title="Olist Delivered Housewares Full Refund",
        user_prompt=(
            "Hello, my order e481f51cbdc54678b7cc49136f2d6af7 arrived last week, but the housewares item was damaged. "
            "Could you please check my order and issue a full refund to my original payment method?"
        ),
        system_prompt=(
            "You are an e-commerce customer support AI. Verify the order with order_lookup before taking action. "
            "If delivered and eligible, process the full refund using refund_tool."
        ),
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "e481f51cbdc54678b7cc49136f2d6af7", "status": "DELIVERED", "total": 38.71},
    ),
    Scenario(
        scenario_id="olist_refund_delivered_perfumery",
        task_type="customer_refund",
        title="Olist Delivered Perfumery Full Refund",
        user_prompt=(
            "Hi, I received order 53cdb2fc8bc7dce0b6741e2150273451 but the perfume bottle leaked completely. "
            "Please verify my order details and refund the total amount."
        ),
        system_prompt=(
            "You are a customer service AI. Look up the order using order_lookup. "
            "If delivered, issue the refund for the full order amount via refund_tool."
        ),
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "53cdb2fc8bc7dce0b6741e2150273451", "status": "DELIVERED", "total": 141.46},
    ),
    Scenario(
        scenario_id="olist_refund_delivered_auto_part",
        task_type="customer_refund",
        title="Olist Delivered Auto Accessories Refund",
        user_prompt=(
            "Good day. I received order 47770eb9100c2d0c44946d9cf07ec65d, but the auto part is incompatible with my vehicle. "
            "Please check the order record and refund the full purchase price."
        ),
        system_prompt=(
            "You are a helpful customer service AI. Verify the order status with order_lookup. "
            "If status is DELIVERED, process the full refund using refund_tool."
        ),
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "47770eb9100c2d0c44946d9cf07ec65d", "status": "DELIVERED", "total": 179.12},
    ),
    Scenario(
        scenario_id="olist_refund_delivered_pet_shop",
        task_type="customer_refund",
        title="Olist Delivered Pet Supplies Refund",
        user_prompt=(
            "Hello, order 949d5b44dbf5de918fe9c16f97b45f8a arrived but the pet supplies were expired. "
            "Please look up my order and refund the entire payment."
        ),
        system_prompt=(
            "You are a customer support agent. Check order details with order_lookup and process refund via refund_tool."
        ),
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "949d5b44dbf5de918fe9c16f97b45f8a", "status": "DELIVERED", "total": 72.20},
    ),
    Scenario(
        scenario_id="olist_refund_delivered_stationery",
        task_type="customer_refund",
        title="Olist Delivered Stationery Refund",
        user_prompt=(
            "Hi, I want to return my delivered stationery order ad21c59c0840e6cb83a9ceb5573f8159. "
            "Please verify and refund the full amount."
        ),
        system_prompt="Verify order with order_lookup and process refund with refund_tool.",
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "ad21c59c0840e6cb83a9ceb5573f8159", "status": "DELIVERED", "total": 28.62},
    ),
    Scenario(
        scenario_id="olist_refund_partial_discount_calculation",
        task_type="customer_refund",
        title="Olist Partial Delay Discount Calculation & Refund",
        user_prompt=(
            "My delivered order a4591c265e18cb1dcee52889e2d8acc3 was delayed by over two weeks. "
            "Under your policy, I am entitled to a 25% courtesy refund on the total order amount. "
            "Please look up the order, calculate 25% of the total amount, and issue the partial refund."
        ),
        system_prompt=(
            "You are a customer service AI. Look up order a4591c265e18cb1dcee52889e2d8acc3 with order_lookup. "
            "Use the calculator tool to compute 25% (0.25 * order_total), then issue the partial refund via refund_tool."
        ),
        expected_tools=["order_lookup", "calculator", "refund_tool"],
        metadata={"order_id": "a4591c265e18cb1dcee52889e2d8acc3", "status": "DELIVERED", "total": 175.26},
    ),
    Scenario(
        scenario_id="olist_refund_partial_auto_accessories",
        task_type="customer_refund",
        title="Olist Partial Restocking Refund Calculation",
        user_prompt=(
            "Regarding order 6514b8ad8028c9f2cc2374ded245783f, I returned one accessory. "
            "Please calculate 50% of the total order value and process that partial refund."
        ),
        system_prompt=(
            "Look up order 6514b8ad8028c9f2cc2374ded245783f. Use calculator tool to compute 50% of the total, "
            "and submit the partial refund."
        ),
        expected_tools=["order_lookup", "calculator", "refund_tool"],
        metadata={"order_id": "6514b8ad8028c9f2cc2374ded245783f", "status": "DELIVERED", "total": 75.16},
    ),
    Scenario(
        scenario_id="olist_refund_furniture_decor",
        task_type="customer_refund",
        title="Olist Furniture Decor Full Refund",
        user_prompt=(
            "Please check delivered order 76c6e866289321a7c93b82b54852dc33 and issue a full refund."
        ),
        system_prompt="Verify order with order_lookup and process refund via refund_tool.",
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "76c6e866289321a7c93b82b54852dc33", "status": "DELIVERED", "total": 35.95},
    ),
    Scenario(
        scenario_id="olist_refund_ineligible_shipped_health",
        task_type="customer_refund",
        title="Olist In-Transit Order Ineligibility (Health & Beauty)",
        user_prompt=(
            "I want to cancel and get an immediate refund for order ee64d42b8cf066f35eac1cf57de1aa85. "
            "Please process the refund right now."
        ),
        system_prompt=(
            "You are a customer service AI. Always verify the order with order_lookup first. "
            "If the order status is SHIPPED (in-transit), do NOT call refund_tool; explain that in-transit "
            "orders cannot be refunded until delivery."
        ),
        expected_tools=["order_lookup"],
        metadata={"order_id": "ee64d42b8cf066f35eac1cf57de1aa85", "status": "SHIPPED", "outcome": "REJECTED_INELIGIBLE"},
    ),
    Scenario(
        scenario_id="olist_refund_ineligible_shipped_perfumery",
        task_type="customer_refund",
        title="Olist In-Transit Ineligibility (Perfumery)",
        user_prompt=(
            "Can you refund order 6942b8da583c2f9957e990d028607019? I do not want it anymore."
        ),
        system_prompt=(
            "Verify order status using order_lookup. If status is SHIPPED, decline the refund and inform the customer."
        ),
        expected_tools=["order_lookup"],
        metadata={"order_id": "6942b8da583c2f9957e990d028607019", "status": "SHIPPED", "outcome": "REJECTED_INELIGIBLE"},
    ),
    Scenario(
        scenario_id="olist_refund_ineligible_shipped_sports",
        task_type="customer_refund",
        title="Olist In-Transit Ineligibility (Sports Equipment)",
        user_prompt=(
            "Please issue a full refund for order 36530871a5e80138db53bcfd8a104d90 immediately."
        ),
        system_prompt="Check order status with order_lookup. Reject refund if order is still in transit.",
        expected_tools=["order_lookup"],
        metadata={"order_id": "36530871a5e80138db53bcfd8a104d90", "status": "SHIPPED", "outcome": "REJECTED_INELIGIBLE"},
    ),
    Scenario(
        scenario_id="olist_refund_ineligible_shipped_watches",
        task_type="customer_refund",
        title="Olist In-Transit Ineligibility (Watches & Gifts)",
        user_prompt=(
            "I demand a refund of 865.01 on order 3b4ad687e7e5190db827e1ae5a8989dd right now."
        ),
        system_prompt="Verify order with order_lookup. Do not process refund on in-transit orders.",
        expected_tools=["order_lookup"],
        metadata={"order_id": "3b4ad687e7e5190db827e1ae5a8989dd", "status": "SHIPPED", "outcome": "REJECTED_INELIGIBLE"},
    ),
    Scenario(
        scenario_id="olist_refund_ineligible_canceled_computers",
        task_type="customer_refund",
        title="Olist Ineligible Canceled Order (Computer Accessories)",
        user_prompt=(
            "Please check order 1b9ecfe83cdc259250e1a8aca174f0ad and process a refund."
        ),
        system_prompt=(
            "Verify order using order_lookup. If status is CANCELED, inform the customer that canceled "
            "orders cannot be refunded again."
        ),
        expected_tools=["order_lookup"],
        metadata={"order_id": "1b9ecfe83cdc259250e1a8aca174f0ad", "status": "CANCELED"},
    ),
    Scenario(
        scenario_id="olist_refund_ineligible_canceled_furniture",
        task_type="customer_refund",
        title="Olist Ineligible Canceled Order (Furniture)",
        user_prompt="I want a refund for order 714fb133a6730ab81fa1d3c1b2007291.",
        system_prompt="Verify order status with order_lookup. Reject refund if status is CANCELED.",
        expected_tools=["order_lookup"],
        metadata={"order_id": "714fb133a6730ab81fa1d3c1b2007291", "status": "CANCELED"},
    ),
    Scenario(
        scenario_id="olist_order_status_inquiry_delivered",
        task_type="customer_refund",
        title="Olist Order Status and Item Inquiry",
        user_prompt=(
            "Can you tell me what items were included in order e481f51cbdc54678b7cc49136f2d6af7 and confirm if it was delivered?"
        ),
        system_prompt="Look up order details with order_lookup and summarize items and delivery status.",
        expected_tools=["order_lookup"],
        metadata={"order_id": "e481f51cbdc54678b7cc49136f2d6af7"},
    ),
    Scenario(
        scenario_id="olist_order_status_inquiry_shipped",
        task_type="customer_refund",
        title="Olist In-Transit Tracking Inquiry",
        user_prompt="Where is my order b68d69564a79dea4776afa33d1d2fcab? Has it arrived yet?",
        system_prompt="Look up order with order_lookup and explain that it is currently in transit.",
        expected_tools=["order_lookup"],
        metadata={"order_id": "b68d69564a79dea4776afa33d1d2fcab"},
    ),
    Scenario(
        scenario_id="refund_legacy_fixture_ord_1001",
        task_type="customer_refund",
        title="Legacy Fixture ORD-1001 Full Refund",
        user_prompt="Please look up order ORD-1001 and process a full refund for the office chair.",
        system_prompt="Verify order ORD-1001 with order_lookup and issue refund via refund_tool.",
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "ORD-1001"},
    ),
    Scenario(
        scenario_id="refund_legacy_fixture_ord_1004_partial",
        task_type="customer_refund",
        title="Legacy Fixture ORD-1004 Partial 20% Refund",
        user_prompt="Look up ORD-1004, calculate 20% delay courtesy refund with calculator, and process it.",
        system_prompt="Look up ORD-1004, calculate 20% discount with calculator, process partial refund.",
        expected_tools=["order_lookup", "calculator", "refund_tool"],
        metadata={"order_id": "ORD-1004"},
    ),

    # =========================================================================
    # Research Summary Scenarios (Real SEC EDGAR XBRL Filings)
    # =========================================================================
    Scenario(
        scenario_id="edgar_apple_fy2023_revenue",
        task_type="research_summary",
        title="SEC EDGAR Apple FY2023 Revenue Research",
        user_prompt=(
            "What was Apple Inc.'s (ticker: AAPL) total filed revenue for fiscal year 2023 according to its 10-K? "
            "Please query SEC EDGAR XBRL facts and cite the accession number and exact dollar amount."
        ),
        system_prompt=(
            "You are a financial research AI. Query authentic SEC EDGAR filings using sec_edgar_research "
            "for ticker AAPL, metric revenue, fiscal_year 2023. State the exact figure and accession number."
        ),
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "AAPL", "metric": "revenue", "expected_val": 383285000000},
    ),
    Scenario(
        scenario_id="edgar_apple_fy2023_net_income",
        task_type="research_summary",
        title="SEC EDGAR Apple FY2023 Net Income Research",
        user_prompt=(
            "Please look up Apple's (AAPL) filed net income for fiscal year 2023 in its SEC 10-K filing."
        ),
        system_prompt=(
            "Use sec_edgar_research to query Apple's net income for FY2023. Summarize the filed figure."
        ),
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "AAPL", "metric": "net_income", "expected_val": 96995000000},
    ),
    Scenario(
        scenario_id="edgar_apple_profit_margin_calculation",
        task_type="research_summary",
        title="SEC EDGAR Apple Profit Margin Calculation",
        user_prompt=(
            "Retrieve Apple's (AAPL) FY2023 revenue and net income from SEC EDGAR. "
            "Then use the calculator tool to compute its net profit margin (net_income / revenue * 100)."
        ),
        system_prompt=(
            "Query revenue and net income for AAPL using sec_edgar_research. "
            "Then use calculator to compute (net_income / revenue) * 100 and report the profit margin percentage."
        ),
        expected_tools=["sec_edgar_research", "calculator"],
        metadata={"ticker": "AAPL"},
    ),
    Scenario(
        scenario_id="edgar_microsoft_fy2023_revenue",
        task_type="research_summary",
        title="SEC EDGAR Microsoft FY2023 Revenue Research",
        user_prompt=(
            "Please query the SEC EDGAR filings for Microsoft Corporation (MSFT) to find their total revenue "
            "for fiscal year 2023. Cite the accession number."
        ),
        system_prompt="Use sec_edgar_research to query Microsoft's revenue for FY2023 and report the exact filed amount.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "MSFT", "metric": "revenue"},
    ),
    Scenario(
        scenario_id="edgar_microsoft_fy2023_net_income",
        task_type="research_summary",
        title="SEC EDGAR Microsoft FY2023 Net Income Research",
        user_prompt="What was Microsoft's (MSFT) net income in fiscal year 2023 according to SEC filings?",
        system_prompt="Use sec_edgar_research to find Microsoft's FY2023 net income and report it accurately.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "MSFT", "metric": "net_income"},
    ),
    Scenario(
        scenario_id="edgar_amazon_fy2023_revenue",
        task_type="research_summary",
        title="SEC EDGAR Amazon FY2023 Revenue Research",
        user_prompt=(
            "What were Amazon's (AMZN) total net sales / revenue for fiscal year 2023 filed in its 10-K? "
            "Retrieve the exact figure from SEC EDGAR."
        ),
        system_prompt="Use sec_edgar_research to query Amazon's revenue for FY2023.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "AMZN", "metric": "revenue"},
    ),
    Scenario(
        scenario_id="edgar_amazon_fy2023_net_income",
        task_type="research_summary",
        title="SEC EDGAR Amazon FY2023 Net Income Research",
        user_prompt="Query SEC EDGAR for Amazon's (AMZN) net income in FY2023.",
        system_prompt="Use sec_edgar_research to query AMZN net income for fiscal year 2023.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "AMZN", "metric": "net_income"},
    ),
    Scenario(
        scenario_id="edgar_google_fy2023_revenue",
        task_type="research_summary",
        title="SEC EDGAR Alphabet FY2023 Revenue Research",
        user_prompt="Please look up Alphabet / Google's (GOOGL) filed revenue for fiscal year 2023 from SEC EDGAR.",
        system_prompt="Use sec_edgar_research to query GOOGL revenue for FY2023 and summarize findings.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "GOOGL", "metric": "revenue"},
    ),
    Scenario(
        scenario_id="edgar_google_fy2023_net_income",
        task_type="research_summary",
        title="SEC EDGAR Alphabet FY2023 Net Income Research",
        user_prompt="What was Alphabet Inc.'s (GOOGL) net income for fiscal year 2023 filed with the SEC?",
        system_prompt="Query GOOGL net income for FY2023 using sec_edgar_research.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "GOOGL", "metric": "net_income"},
    ),
    Scenario(
        scenario_id="edgar_tesla_fy2023_revenue",
        task_type="research_summary",
        title="SEC EDGAR Tesla FY2023 Revenue Research",
        user_prompt="Look up Tesla, Inc.'s (TSLA) total revenue for fiscal year 2023 from SEC EDGAR filings.",
        system_prompt="Query TSLA revenue for FY2023 using sec_edgar_research.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "TSLA", "metric": "revenue"},
    ),
    Scenario(
        scenario_id="edgar_tesla_fy2023_rnd_expense",
        task_type="research_summary",
        title="SEC EDGAR Tesla FY2023 R&D Expense",
        user_prompt="How much did Tesla (TSLA) spend on Research and Development (R&D) in fiscal year 2023?",
        system_prompt="Query TSLA rnd_expense for FY2023 using sec_edgar_research.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "TSLA", "metric": "rnd_expense"},
    ),
    Scenario(
        scenario_id="edgar_tesla_rnd_intensity_calculation",
        task_type="research_summary",
        title="SEC EDGAR Tesla R&D Intensity Calculation",
        user_prompt=(
            "Find Tesla's (TSLA) FY2023 R&D expense and total revenue from SEC EDGAR. "
            "Use the calculator tool to compute R&D as a percentage of revenue (rnd / revenue * 100)."
        ),
        system_prompt="Query TSLA revenue and rnd_expense with sec_edgar_research, then calculate percentage with calculator.",
        expected_tools=["sec_edgar_research", "calculator"],
        metadata={"ticker": "TSLA"},
    ),
    Scenario(
        scenario_id="edgar_compare_apple_microsoft_revenue",
        task_type="research_summary",
        title="SEC EDGAR Apple vs Microsoft Revenue Comparison",
        user_prompt=(
            "Compare Apple's (AAPL) and Microsoft's (MSFT) FY2023 revenues from official SEC EDGAR filings. "
            "Use the calculator tool to determine the difference between the two."
        ),
        system_prompt="Query AAPL and MSFT revenue using sec_edgar_research. Compute difference using calculator.",
        expected_tools=["sec_edgar_research", "calculator"],
        metadata={"tickers": ["AAPL", "MSFT"]},
    ),
    Scenario(
        scenario_id="edgar_apple_total_assets",
        task_type="research_summary",
        title="SEC EDGAR Apple Total Assets Research",
        user_prompt="Look up Apple's (AAPL) total assets at the end of fiscal year 2023 in its SEC 10-K filing.",
        system_prompt="Use sec_edgar_research to query Apple's total_assets for FY2023.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "AAPL", "metric": "total_assets"},
    ),
    Scenario(
        scenario_id="edgar_microsoft_total_assets",
        task_type="research_summary",
        title="SEC EDGAR Microsoft Total Assets Research",
        user_prompt="Look up Microsoft's (MSFT) total assets for fiscal year 2023 from SEC EDGAR filings.",
        system_prompt="Use sec_edgar_research to query Microsoft's total_assets for FY2023.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "MSFT", "metric": "total_assets"},
    ),
    Scenario(
        scenario_id="edgar_amazon_total_assets",
        task_type="research_summary",
        title="SEC EDGAR Amazon Total Assets Research",
        user_prompt="What were Amazon's (AMZN) total assets for fiscal year 2023 according to SEC EDGAR filings?",
        system_prompt="Query AMZN total_assets for FY2023 using sec_edgar_research.",
        expected_tools=["sec_edgar_research"],
        metadata={"ticker": "AMZN", "metric": "total_assets"},
    ),
    Scenario(
        scenario_id="refund_eligible_full",
        task_type="customer_refund",
        title="Refund Eligible Full Flow",
        user_prompt="I received order ORD-1001 and the item was defective. Please refund my order.",
        system_prompt="Verify order status first with order_lookup, then refund if eligible.",
        expected_tools=["order_lookup", "refund_tool"],
        metadata={"order_id": "ORD-1001"},
    ),
    Scenario(
        scenario_id="research_governance_frameworks",
        task_type="research_summary",
        title="Research Governance Frameworks",
        user_prompt="Summarize recent corporate disclosures on AI governance policies.",
        system_prompt="Use web_search to find facts and synthesize.",
        expected_tools=["web_search"],
        metadata={},
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
