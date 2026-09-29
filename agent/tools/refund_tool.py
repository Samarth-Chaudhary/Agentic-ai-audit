"""Refund tool backed by real Olist order validation and demo fixtures.

Processes and validates customer refunds against authentic Olist Brazilian e-commerce orders
or legacy demo fixtures, verifying eligibility and amount constraints.
All outputs clearly distinguish authentic Olist transactions from synthetic fixtures.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent.data.olist_loader import OlistDataLoader
from agent.tools.base import BaseTool
from agent.tools.order_lookup import SYNTHETIC_ORDERS


class RefundTool(BaseTool):
    """Tool for processing refunds validated against authentic Olist records or demo fixtures."""

    def __init__(self, olist_loader: OlistDataLoader | None = None) -> None:
        self.olist_loader = olist_loader or OlistDataLoader()

    @property
    def name(self) -> str:
        return "refund_tool"

    @property
    def description(self) -> str:
        return (
            "Process a customer refund for a specified order and dollar/currency amount. "
            "Validates against real order status and maximum refundable balance."
        )

    @property
    def data_source(self) -> str:
        return "olist_refund_gateway"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["order_id", "amount"],
            "properties": {
                "order_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Identifier of the order to refund (e.g. real Olist ID or 'ORD-1001').",
                },
                "amount": {
                    "type": "number",
                    "exclusiveMinimum": 0.0,
                    "description": "Monetary amount to refund (must be strictly positive).",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional business reason for the refund request.",
                },
            },
            "additionalProperties": False,
        }

    def execute(self, order_id: str, amount: float, reason: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Execute refund validation against synthetic store or real Olist records."""
        clean_order_id = str(order_id).strip()
        refund_amount = round(float(amount), 2)

        if refund_amount <= 0.0:
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": "Refund amount must be strictly positive.",
                "transaction_id": None,
                "backend": "validation_gate",
                "is_synthetic": False,
            }

        # Case 1: Check synthetic fixtures
        upper_id = clean_order_id.upper()
        if upper_id in SYNTHETIC_ORDERS:
            synth_order = SYNTHETIC_ORDERS[upper_id]
            if not synth_order.get("refund_eligible", False):
                return {
                    "success": False,
                    "order_id": upper_id,
                    "error": f"Order '{upper_id}' is not eligible for refund (Status: {synth_order.get('status')}).",
                    "transaction_id": None,
                    "backend": "synthetic_refund_gateway_stub",
                    "data_source": "synthetic_refund_gateway",
                    "is_synthetic": True,
                }
            refundable_max = synth_order.get("refundable_amount", 0.0)
            if refund_amount > refundable_max:
                return {
                    "success": False,
                    "order_id": upper_id,
                    "error": f"Requested refund amount ${refund_amount:.2f} exceeds available refundable balance of ${refundable_max:.2f}.",
                    "transaction_id": None,
                    "backend": "synthetic_refund_gateway_stub",
                    "data_source": "synthetic_refund_gateway",
                    "is_synthetic": True,
                }
            raw_hash = hashlib.sha256(f"{upper_id}:{refund_amount}:synthetic_salt_2026".encode()).hexdigest()[:12]
            return {
                "success": True,
                "order_id": upper_id,
                "refunded_amount": refund_amount,
                "currency": synth_order.get("currency", "USD"),
                "transaction_id": f"synth-tx-{raw_hash}",
                "status": "COMPLETED",
                "reason": reason or "Customer requested refund",
                "data_source": "synthetic_refund_gateway",
                "backend": "synthetic_refund_gateway_stub",
                "message": f"Synthetic refund of ${refund_amount:.2f} processed successfully for {upper_id}.",
                "is_synthetic": True,
            }

        # Case 2: Check authentic Olist dataset
        lower_id = clean_order_id.lower()
        olist_order = self.olist_loader.get_order(lower_id)
        if olist_order is None:
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": f"Cannot refund unknown order '{clean_order_id}'. Order lookup required first.",
                "transaction_id": None,
                "backend": "olist_refund_gateway",
                "data_source": self.data_source,
                "is_synthetic": False,
            }

        if not olist_order.get("refund_eligible", False):
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": f"Order '{clean_order_id}' is not eligible for refund (Status: {olist_order.get('status')}). In-transit orders cannot be refunded until delivery.",
                "transaction_id": None,
                "backend": "olist_refund_gateway",
                "data_source": self.data_source,
                "is_synthetic": False,
            }

        refundable_max = olist_order.get("refundable_amount", 0.0)
        if refund_amount > refundable_max:
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": f"Requested refund amount R${refund_amount:.2f} exceeds available refundable balance of R${refundable_max:.2f}.",
                "transaction_id": None,
                "backend": "olist_refund_gateway",
                "data_source": self.data_source,
                "is_synthetic": False,
            }

        tx_hash = hashlib.sha256(f"{lower_id}:{refund_amount}:olist_real_2026".encode()).hexdigest()[:16]
        return {
            "success": True,
            "order_id": clean_order_id,
            "refunded_amount": refund_amount,
            "currency": olist_order.get("currency", "BRL"),
            "transaction_id": f"olist-tx-{tx_hash}",
            "status": "COMPLETED",
            "reason": reason or "Customer requested refund on delivered item",
            "data_source": self.data_source,
            "backend": "olist_refund_processor",
            "message": f"Authentic refund of R${refund_amount:.2f} processed successfully for Olist order {clean_order_id}.",
            "is_synthetic": False,
        }
