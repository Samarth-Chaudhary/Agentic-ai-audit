"""Deterministic fake order lookup tool for AI Agent Governance.

BACKEND NOTICE: This is intentionally a synthetic toy/stub data source for testing
and governance demonstration. It does NOT connect to real customer or production databases.
"""

from __future__ import annotations

from typing import Any

from agent.tools.base import BaseTool, ToolExecutionError

# Synthetic demo order store
SYNTHETIC_ORDERS: dict[str, dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer_name": "Alice Smith",
        "customer_email": "alice.smith@example-synthetic.com",
        "order_total": 120.00,
        "currency": "USD",
        "status": "DELIVERED",
        "refund_eligible": True,
        "already_refunded": False,
        "refundable_amount": 120.00,
        "items": [
            {"sku": "SKU-A1", "name": "Ergonomic Office Chair", "price": 120.00, "qty": 1}
        ],
        "delivery_date": "2026-09-20",
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer_name": "Bob Jones",
        "customer_email": "bob.jones@example-synthetic.com",
        "order_total": 45.50,
        "currency": "USD",
        "status": "SHIPPED",
        "refund_eligible": False,
        "already_refunded": False,
        "refundable_amount": 0.00,
        "items": [
            {"sku": "SKU-B2", "name": "Wireless Mechanical Keyboard", "price": 45.50, "qty": 1}
        ],
        "notes": "Item in transit. Refunds only permitted after physical delivery.",
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "customer_name": "Carol White",
        "customer_email": "carol.white@example-synthetic.com",
        "order_total": 300.00,
        "currency": "USD",
        "status": "RETURNED",
        "refund_eligible": True,
        "already_refunded": True,
        "refundable_amount": 0.00,
        "items": [
            {"sku": "SKU-C3", "name": "Noise Cancelling Headphones", "price": 300.00, "qty": 1}
        ],
        "notes": "Full refund previously issued on 2026-09-22.",
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "customer_name": "David Brown",
        "customer_email": "david.brown@example-synthetic.com",
        "order_total": 89.99,
        "currency": "USD",
        "status": "DELIVERED",
        "refund_eligible": True,
        "already_refunded": False,
        "refundable_amount": 89.99,
        "items": [
            {"sku": "SKU-D4", "name": "Smart Fitness Band", "price": 89.99, "qty": 1}
        ],
        "delivery_date": "2026-09-24",
    },
}


class OrderLookupTool(BaseTool):
    """Tool for querying synthetic customer order records."""

    @property
    def name(self) -> str:
        return "order_lookup"

    @property
    def description(self) -> str:
        return (
            "Look up customer order details from the synthetic order database. "
            "Returns status, customer email, order total, refund eligibility, and refundable amount."
        )

    @property
    def data_source(self) -> str:
        return "synthetic_order_database"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["order_id"],
            "properties": {
                "order_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Unique identifier of the order (e.g. 'ORD-1001').",
                }
            },
            "additionalProperties": False,
        }

    def execute(self, order_id: str, **kwargs: Any) -> dict[str, Any]:
        """Look up order by ID from deterministic synthetic dataset."""
        order_key = str(order_id).strip().upper()
        if not order_key:
            raise ToolExecutionError("order_id must be a non-empty string.")

        if order_key in SYNTHETIC_ORDERS:
            order_data = dict(SYNTHETIC_ORDERS[order_key])
            order_data["found"] = True
            order_data["data_source"] = self.data_source
            order_data["backend"] = "synthetic_order_database_stub"
            return order_data

        return {
            "found": False,
            "order_id": order_key,
            "data_source": self.data_source,
            "error": f"Order '{order_key}' was not found in synthetic database.",
            "backend": "synthetic_order_database_stub",
        }
