"""Deterministic fake refund tool for AI Agent Governance.

BACKEND NOTICE: This is an isolated synthetic mock/stub service. It does NOT connect
to real payment gateways, credit card processors, or merchant banks.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent.tools.base import BaseTool
from agent.tools.order_lookup import SYNTHETIC_ORDERS


class RefundTool(BaseTool):
    """Tool for processing simulated customer refunds on synthetic orders."""

    @property
    def name(self) -> str:
        return "refund_tool"

    @property
    def description(self) -> str:
        return (
            "Process a customer refund for a specified order and dollar amount. "
            "Returns synthetic transaction verification and status."
        )

    @property
    def data_source(self) -> str:
        return "synthetic_refund_gateway"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["order_id", "amount"],
            "properties": {
                "order_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Identifier of the order to refund (e.g. 'ORD-1001').",
                },
                "amount": {
                    "type": "number",
                    "exclusiveMinimum": 0.0,
                    "description": "Monetary amount to refund (must be greater than 0).",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional business reason for the refund request.",
                },
            },
            "additionalProperties": False,
        }

    def execute(self, order_id: str, amount: float, reason: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Execute synthetic refund validation and generate synthetic confirmation."""
        clean_order_id = str(order_id).strip().upper()
        refund_amount = round(float(amount), 2)

        if refund_amount <= 0.0:
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": "Refund amount must be strictly positive.",
                "transaction_id": None,
                "backend": "synthetic_refund_gateway_stub",
            }

        # Check order existence and eligibility against synthetic order store
        if clean_order_id not in SYNTHETIC_ORDERS:
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": f"Cannot refund unknown order '{clean_order_id}'. Order lookup required first.",
                "transaction_id": None,
                "backend": "synthetic_refund_gateway_stub",
            }

        order = SYNTHETIC_ORDERS[clean_order_id]
        if not order.get("refund_eligible", False):
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": f"Order '{clean_order_id}' is not eligible for refund (Status: {order.get('status')}).",
                "transaction_id": None,
                "backend": "synthetic_refund_gateway_stub",
            }

        refundable_max = order.get("refundable_amount", 0.0)
        if refund_amount > refundable_max:
            return {
                "success": False,
                "order_id": clean_order_id,
                "error": (
                    f"Requested refund amount ${refund_amount:.2f} exceeds available refundable "
                    f"balance of ${refundable_max:.2f}."
                ),
                "transaction_id": None,
                "backend": "synthetic_refund_gateway_stub",
            }

        # Generate a deterministic synthetic transaction hash
        raw_hash = hashlib.sha256(f"{clean_order_id}:{refund_amount}:synthetic_salt_2026".encode()).hexdigest()[:12]
        synthetic_tx_id = f"synth-tx-{raw_hash}"

        return {
            "success": True,
            "order_id": clean_order_id,
            "refunded_amount": refund_amount,
            "currency": order.get("currency", "USD"),
            "transaction_id": synthetic_tx_id,
            "status": "COMPLETED",
            "reason": reason or "Customer requested refund",
            "data_source": self.data_source,
            "backend": "synthetic_refund_gateway_stub",
            "message": f"Synthetic refund of ${refund_amount:.2f} processed successfully for {clean_order_id}.",
        }
