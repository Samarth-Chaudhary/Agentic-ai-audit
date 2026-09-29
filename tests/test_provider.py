"""Unit tests for LLM providers: interface abstractions, Mock provider, and OpenAI provider isolation."""

from unittest.mock import MagicMock, patch

import pytest
from openai import AuthenticationError

from agent.openai_provider import OpenAIProvider, ProviderAuthenticationError
from agent.provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    MockLLMProvider,
    ToolCall,
)


def test_provider_message_factories():
    """Ensure standard message helper factories produce correct formats."""
    user_msg = LLMProvider.create_user_message("Hello agent")
    assert user_msg.role == "user"
    assert user_msg.content == "Hello agent"

    tool_msg = LLMProvider.create_tool_result_message(
        tool_call_id="call-1",
        tool_name="order_lookup",
        result={"status": "DELIVERED"},
    )
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call-1"
    assert tool_msg.name == "order_lookup"
    assert '"status": "DELIVERED"' in (tool_msg.content or "")


def test_mock_provider_customer_refund_flow():
    """Ensure MockLLMProvider drives multi-turn customer refund simulation."""
    provider = MockLLMProvider()

    # Turn 1: user asks for refund
    messages = [LLMProvider.create_user_message("Please refund order ORD-1001.")]
    resp1 = provider.generate(messages=messages)
    assert len(resp1.tool_calls) == 1
    assert resp1.tool_calls[0].tool_name == "order_lookup"
    assert resp1.tool_calls[0].arguments["order_id"] == "ORD-1001"

    # Turn 2: feed tool result back
    messages.append(
        LLMProvider.create_tool_result_message(
            tool_call_id=resp1.tool_calls[0].call_id,
            tool_name="order_lookup",
            result={"found": True, "status": "DELIVERED", "refund_eligible": True, "refundable_amount": 120.00},
        )
    )
    resp2 = provider.generate(messages=messages)
    assert len(resp2.tool_calls) == 1
    assert resp2.tool_calls[0].tool_name == "refund_tool"
    assert resp2.tool_calls[0].arguments["amount"] == 120.00

    # Turn 3: feed refund result back
    messages.append(
        LLMProvider.create_tool_result_message(
            tool_call_id=resp2.tool_calls[0].call_id,
            tool_name="refund_tool",
            result={"success": True, "transaction_id": "synth-tx-12345", "refunded_amount": 120.00},
        )
    )
    resp3 = provider.generate(messages=messages)
    assert len(resp3.tool_calls) == 0
    assert "processed successfully" in (resp3.content or "")
    assert "synth-tx-12345" in (resp3.content or "")


def test_mock_provider_canned_responses():
    """Ensure explicit canned responses are returned sequentially."""
    canned = [
        LLMResponse(content="Step 1", tool_calls=[], finish_reason="stop"),
        LLMResponse(content="Step 2", tool_calls=[], finish_reason="stop"),
    ]
    provider = MockLLMProvider(canned_responses=canned)

    r1 = provider.generate([])
    assert r1.content == "Step 1"
    r2 = provider.generate([])
    assert r2.content == "Step 2"


def test_openai_provider_missing_key_raises_auth_error():
    """Ensure instantiating OpenAIProvider without API key raises ProviderAuthenticationError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ProviderAuthenticationError):
            OpenAIProvider(api_key=None)


def test_openai_provider_message_conversion():
    """Ensure internal messages convert accurately to OpenAI JSON format."""
    provider = OpenAIProvider(api_key="sk-dummy-test-key-12345678901234567890")
    messages = [
        LLMMessage(role="user", content="Test prompt"),
        LLMMessage(
            role="assistant",
            content="Invoking tool",
            tool_calls=[ToolCall(call_id="call-abc", tool_name="calculator", arguments={"expression": "2+2"})],
        ),
        LLMMessage(role="tool", tool_call_id="call-abc", name="calculator", content='{"result": 4}'),
    ]

    converted = provider._convert_messages(messages)
    assert len(converted) == 3
    assert converted[0]["role"] == "user"
    assert converted[1]["role"] == "assistant"
    assert converted[1]["tool_calls"][0]["function"]["name"] == "calculator"
    assert converted[2]["role"] == "tool"
    assert converted[2]["tool_call_id"] == "call-abc"


def test_openai_provider_error_handling():
    """Ensure OpenAI exceptions are intercepted and re-raised as typed ProviderError."""
    provider = OpenAIProvider(api_key="sk-dummy-test-key-12345678901234567890")
    provider._client = MagicMock()

    # Simulate authentication error from OpenAI SDK
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    provider._client.chat.completions.create.side_effect = AuthenticationError(
        message="Invalid API Key",
        response=mock_resp,
        body={"error": {"message": "Invalid API Key"}},
    )

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        provider.generate(messages=[LLMMessage(role="user", content="Hi")])
    assert "Authentication failed" in str(exc_info.value)
