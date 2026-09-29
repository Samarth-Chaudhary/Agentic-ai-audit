"""Order lookup tool backed by the real Olist Brazilian E-Commerce dataset and demo fixtures.

Supports authentic order queries across thousands of real Olist records (status, amounts, product
categories translated to English, timestamps) as well as legacy synthetic demo fixtures.
All responses explicitly label data provenance (is_synthetic and data_source) with zero mixing.
"""

from __future__ import annotations

from typing import Any

from agent.data.olist_loader import OlistDataLoader
from agent.tools.base import BaseTool, ToolExecutionError

# Synthetic demo order store for backward-compatible fixtures
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
            {"sku": "SKU-A1", "name": "Ergonomic Office Chair", "price": 120.00, "qty": 1, "category": "office_furniture"}
        ],
        "delivery_date": "2026-09-20",
        "is_synthetic": True,
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
            {"sku": "SKU-B2", "name": "Wireless Mechanical Keyboard", "price": 45.50, "qty": 1, "category": "computers"}
        ],
        "notes": "Item in transit. Refunds only permitted after physical delivery.",
        "is_synthetic": True,
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
            {"sku": "SKU-C3", "name": "Noise Cancelling Headphones", "price": 300.00, "qty": 1, "category": "audio"}
        ],
        "notes": "Full refund previously issued on 2026-09-22.",
        "is_synthetic": True,
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
            {"sku": "SKU-D4", "name": "Smart Fitness Band", "price": 89.99, "qty": 1, "category": "wearables"}
        ],
        "delivery_date": "2026-09-24",
        "is_synthetic": True,
    },
}


class OrderLookupTool(BaseTool):
    """Tool for querying customer orders backed by the real Olist dataset and test fixtures."""

    def __init__(self, olist_loader: OlistDataLoader | None = None) -> None:
        self.olist_loader = olist_loader or OlistDataLoader()

    @property
    def name(self) -> str:
        return "order_lookup"

    @property
    def description(self) -> str:
        return (
            "Look up customer order details from the authentic Olist e-commerce database "
            "or test fixtures. Returns status, items, amounts, refund eligibility, and delivery dates."
        )

    @property
    def data_source(self) -> str:
        return "olist_ecommerce_dataset"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["order_id"],
            "properties": {
                "order_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Unique identifier of the order (e.g. real Olist ID 'e481f51cbdc54678b7cc49136f2d6af7' or 'ORD-1001').",
                }
            },
            "additionalProperties": False,
        }

    def execute(self, order_id: str, **kwargs: Any) -> dict[str, Any]:
        """Look up order by ID from real Olist dataset or synthetic fixture store."""
        raw_key = str(order_id).strip()
        if not raw_key:
            raise ToolExecutionError("order_id must be a non-empty string.")

        # Check synthetic fixtures first (case-insensitive for ORD-xxxx)
        upper_key = raw_key.upper()
        if upper_key in SYNTHETIC_ORDERS:
            order_data = dict(SYNTHETIC_ORDERS[upper_key])
            order_data["found"] = True
            order_data["data_source"] = "synthetic_order_database"
            order_data["backend"] = "synthetic_order_database_stub"
            order_data["is_synthetic"] = True
            return order_data

        # Check authentic Olist dataset
        lower_key = raw_key.lower()
        olist_order = self.olist_loader.get_order(lower_key)
        if olist_order is not None:
            res = dict(olist_order)
            res["found"] = True
            res["backend"] = "olist_sqlite_store"
            return res

        return {
            "found": False,
            "order_id": raw_key,
            "data_source": self.data_source,
            "error": f"Order '{raw_key}' was not found in Olist dataset or synthetic fixtures.",
            "backend": "olist_sqlite_store",
            "is_synthetic": False,
        }
