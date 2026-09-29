"""Unit tests for agent tools: input validation, deterministic outputs, and calculator safety."""

import pytest

from agent.tools.base import ToolInputValidationError
from agent.tools.calculator import CalculatorTool
from agent.tools.order_lookup import OrderLookupTool
from agent.tools.refund_tool import RefundTool
from agent.tools.web_search import WebSearchTool

# ---------------------------------------------------------------------------
# Order Lookup Tool Tests
# ---------------------------------------------------------------------------

def test_order_lookup_deterministic_data():
    """Ensure OrderLookupTool returns expected synthetic order records."""
    tool = OrderLookupTool()
    res = tool.execute(order_id="ORD-1001")

    assert res["found"] is True
    assert res["order_id"] == "ORD-1001"
    assert res["customer_name"] == "Alice Smith"
    assert res["status"] == "DELIVERED"
    assert res["refund_eligible"] is True
    assert res["refundable_amount"] == 120.00
    assert res["data_source"] == "synthetic_order_database" or tool.data_source == "synthetic_order_database"


def test_order_lookup_not_found():
    """Ensure non-existent order returns structured found=False."""
    tool = OrderLookupTool()
    res = tool.execute(order_id="ORD-9999")
    assert res["found"] is False
    assert "not found" in res["error"].lower()


def test_order_lookup_input_validation():
    """Ensure invalid schema inputs raise ToolInputValidationError."""
    tool = OrderLookupTool()
    # Missing required argument
    with pytest.raises(ToolInputValidationError):
        tool.validate_input({})

    # Empty string should fail schema minLength
    with pytest.raises(ToolInputValidationError):
        tool.validate_input({"order_id": ""})


# ---------------------------------------------------------------------------
# Refund Tool Tests
# ---------------------------------------------------------------------------

def test_refund_tool_deterministic_success():
    """Ensure eligible order refund generates synthetic transaction confirmation."""
    tool = RefundTool()
    res = tool.execute(order_id="ORD-1001", amount=50.00)

    assert res["success"] is True
    assert res["order_id"] == "ORD-1001"
    assert res["refunded_amount"] == 50.00
    assert res["currency"] == "USD"
    assert res["transaction_id"].startswith("synth-tx-")


def test_refund_tool_ineligible_rejection():
    """Ensure ineligible in-transit order is refused with clear reason."""
    tool = RefundTool()
    res = tool.execute(order_id="ORD-1002", amount=45.50)

    assert res["success"] is False
    assert "not eligible" in res["error"].lower()
    assert res["transaction_id"] is None


def test_refund_tool_amount_exceeded():
    """Ensure refund exceeding available amount is rejected."""
    tool = RefundTool()
    res = tool.execute(order_id="ORD-1001", amount=999.00)

    assert res["success"] is False
    assert "exceeds available" in res["error"].lower()


def test_refund_tool_input_validation():
    """Ensure negative amount or missing fields fail validation."""
    tool = RefundTool()
    with pytest.raises(ToolInputValidationError):
        tool.validate_input({"order_id": "ORD-1001", "amount": -10.0})

    with pytest.raises(ToolInputValidationError):
        tool.validate_input({"order_id": "ORD-1001"})


# ---------------------------------------------------------------------------
# Web Search Tool Tests
# ---------------------------------------------------------------------------

def test_web_search_deterministic_matching():
    """Ensure web search returns matching synthetic documents with public_web_stub source."""
    tool = WebSearchTool()
    res = tool.execute(query="governance audit observability", max_results=2)

    assert res["results_count"] > 0
    first = res["results"][0]
    assert first["source"] == "public_web_stub"
    assert "governance" in first["title"].lower() or "governance" in first["snippet"].lower()


def test_web_search_input_validation():
    """Ensure empty query fails validation."""
    tool = WebSearchTool()
    with pytest.raises(ToolInputValidationError):
        tool.validate_input({"query": ""})


# ---------------------------------------------------------------------------
# Calculator Tool Tests & Safety
# ---------------------------------------------------------------------------

def test_calculator_basic_arithmetic():
    """Ensure safe arithmetic computes expected numbers."""
    calc = CalculatorTool()

    assert calc.execute(expression="10 + 20")["result"] == 30
    assert calc.execute(expression="89.99 * 0.20")["result"] == 17.998
    assert calc.execute(expression="(100 - 25) / 5")["result"] == 15.0
    assert calc.execute(expression="2 ** 4")["result"] == 16


def test_calculator_division_by_zero():
    """Ensure division by zero is handled safely."""
    calc = CalculatorTool()
    res = calc.execute(expression="10 / 0")
    assert res["success"] is False
    assert "division by zero" in res["error"].lower()


def test_calculator_safety_blocks_code_execution():
    """Ensure malicious or non-arithmetic syntax is completely blocked."""
    calc = CalculatorTool()

    # Block imports
    res_import = calc.execute(expression="__import__('os').system('echo pwned')")
    assert res_import["success"] is False

    # Block variable names
    res_name = calc.execute(expression="x + 5")
    assert res_name["success"] is False

    # Block function calls
    res_call = calc.execute(expression="print('hello')")
    assert res_call["success"] is False

    # Block eval
    res_eval = calc.execute(expression="eval('1 + 1')")
    assert res_eval["success"] is False
