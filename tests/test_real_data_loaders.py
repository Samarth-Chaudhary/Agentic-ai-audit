"""Tests verifying that tools are backed by real Olist and SEC EDGAR datasets end to end."""

from __future__ import annotations

from agent.data.edgar_loader import EdgarDataLoader
from agent.data.olist_loader import OlistDataLoader
from agent.tools.order_lookup import OrderLookupTool
from agent.tools.refund_tool import RefundTool
from agent.tools.sec_edgar import SecEdgarTool


class TestOlistRealData:
    """End-to-end tests verifying authentic Olist dataset records."""

    def test_olist_loader_known_real_record(self) -> None:
        """Verify known order e481f51cbdc54678b7cc49136f2d6af7 matches official Olist record."""
        loader = OlistDataLoader()
        order = loader.get_order("e481f51cbdc54678b7cc49136f2d6af7")

        assert order is not None, "Known Olist order must exist in seeded database"
        assert order["order_id"] == "e481f51cbdc54678b7cc49136f2d6af7"
        assert order["customer_id"] == "9ef432eb6251297304e76186b10a928d"
        assert order["status"] == "DELIVERED"
        assert order["currency"] == "BRL"
        assert order["is_synthetic"] is False
        assert order["data_source"] == "olist_ecommerce_dataset"
        # Total payment in official Olist dataset = 18.12 + 2.00 + 18.59 = 38.71
        assert order["order_total"] == 38.71
        assert order["refund_eligible"] is True
        assert order["refundable_amount"] == 38.71

        # Check item category translation
        assert len(order["items"]) >= 1
        item = order["items"][0]
        assert item["product_id"] == "87285b34884572647811a353c7ac498a"
        assert item["category"] == "housewares"
        assert item["price"] == 29.99

    def test_order_lookup_tool_with_real_olist_record(self) -> None:
        """Verify OrderLookupTool returns real Olist row and sets proper provenance tags."""
        tool = OrderLookupTool()
        res = tool.execute(order_id="e481f51cbdc54678b7cc49136f2d6af7")

        assert res["found"] is True
        assert res["order_id"] == "e481f51cbdc54678b7cc49136f2d6af7"
        assert res["is_synthetic"] is False
        assert res["data_source"] == "olist_ecommerce_dataset"
        assert res["status"] == "DELIVERED"
        assert res["order_total"] == 38.71
        assert res["items"][0]["category"] == "housewares"

    def test_refund_tool_with_real_olist_record(self) -> None:
        """Verify RefundTool validates real Olist balance and executes authentic refund."""
        tool = RefundTool()
        # Valid partial refund on delivered order
        res = tool.execute(order_id="e481f51cbdc54678b7cc49136f2d6af7", amount=20.00)
        assert res["success"] is True
        assert res["order_id"] == "e481f51cbdc54678b7cc49136f2d6af7"
        assert res["refunded_amount"] == 20.00
        assert res["currency"] == "BRL"
        assert res["is_synthetic"] is False
        assert res["data_source"] == "olist_refund_gateway"
        assert res["transaction_id"].startswith("olist-tx-")

        # Exceeding balance rejected
        exceed_res = tool.execute(order_id="e481f51cbdc54678b7cc49136f2d6af7", amount=9999.00)
        assert exceed_res["success"] is False
        assert "exceeds available" in exceed_res["error"].lower()


class TestSecEdgarRealData:
    """End-to-end tests verifying authentic SEC EDGAR XBRL corporate filings."""

    def test_edgar_loader_known_real_record(self) -> None:
        """Verify Apple Inc. FY2023 10-K filed revenue matches official SEC EDGAR XBRL filing."""
        loader = EdgarDataLoader()
        fact = loader.query_financial_metric("AAPL", "revenue", 2023)

        assert fact["found"] is True
        assert fact["entity_name"] == "Apple Inc."
        assert fact["ticker_or_cik"] == "AAPL"
        assert fact["cik"] == "0000320193"
        assert fact["fiscal_year"] == 2023
        assert fact["form"] == "10-K"
        # Official 10-K FY2023 Revenue: $383,285,000,000
        assert fact["value"] == 383285000000
        assert fact["formatted_value"] == "$383,285,000,000.00"
        assert fact["accession_number"] == "0000320193-23-000106"
        assert fact["is_synthetic"] is False
        assert fact["data_source"] == "sec_edgar_xbrl_api"

    def test_sec_edgar_tool_execution(self) -> None:
        """Verify SecEdgarTool retrieves filed metrics with accession provenance."""
        tool = SecEdgarTool()
        res = tool.execute(ticker="MSFT", metric="net_income", fiscal_year=2023)

        assert res["found"] is True
        assert "MICROSOFT" in res["entity_name"].upper()
        assert res["is_synthetic"] is False
        assert res["value"] > 0
        assert res["data_source"] == "sec_edgar_xbrl_api"
        assert "accession_number" in res
