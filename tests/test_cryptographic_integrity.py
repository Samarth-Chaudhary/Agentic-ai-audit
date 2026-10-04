"""Unit tests for cryptographic step hash chaining and tamper-evidence."""

from __future__ import annotations

from agent.trace_builder import TraceBuilder


def test_valid_trace_cryptographic_integrity():
    """Ensure a freshly built trace passes cryptographic verification."""
    builder = TraceBuilder(task_type="customer_refund")
    builder.add_assistant_message("Checking order status.")
    builder.add_tool_call("order_lookup", {"order_id": "ord-101"})
    builder.add_tool_result("order_lookup", {"order_id": "ord-101", "status": "DELIVERED", "refundable_amount": 100.0})
    builder.add_tool_call("refund_tool", {"order_id": "ord-101", "amount": 50.0})
    builder.add_tool_result("refund_tool", {"status": "SUCCESS", "refunded": 50.0})
    builder.set_final_answer("Refund of $50.00 processed successfully.")

    trace = builder.build()

    # Assert hashes exist and are populated
    assert trace.merkle_root_hash is not None
    assert len(trace.steps) == 5
    for step in trace.steps:
        assert step.step_hash is not None
        assert step.prev_step_hash is not None

    # Verify cryptographic integrity passes
    is_valid, error = trace.verify_integrity()
    assert is_valid is True
    assert error is None


def test_tampered_step_payload_fails_verification():
    """Ensure that modifying any step payload invalidates the cryptographic chain."""
    builder = TraceBuilder(task_type="customer_refund")
    builder.add_assistant_message("Checking order status.")
    builder.add_tool_call("order_lookup", {"order_id": "ord-101"})
    builder.add_tool_result("order_lookup", {"order_id": "ord-101", "status": "DELIVERED", "refundable_amount": 100.0})
    builder.add_tool_call("refund_tool", {"order_id": "ord-101", "amount": 50.0})
    builder.add_tool_result("refund_tool", {"status": "SUCCESS", "refunded": 50.0})
    builder.set_final_answer("Refund of $50.00 processed.")

    trace = builder.build()

    # Malicious insider changes the recorded refund amount from $50.0 to $500.0
    trace.steps[3].input["amount"] = 500.0

    is_valid, error = trace.verify_integrity()
    assert is_valid is False
    assert "Cryptographic integrity violation at step 3" in error


def test_deleted_step_fails_verification():
    """Ensure that deleting an intermediate step breaks the hash chain link."""
    builder = TraceBuilder(task_type="customer_refund")
    builder.add_assistant_message("Step 0")
    builder.add_tool_call("order_lookup", {"order_id": "ord-101"})
    builder.add_tool_result("order_lookup", {"status": "OK"})
    builder.set_final_answer("Done.")

    trace = builder.build()

    # Malicious insider removes step 1
    del trace.steps[1]

    is_valid, error = trace.verify_integrity()
    assert is_valid is False
    assert "Broken chain link" in error or "Cryptographic integrity violation" in error
