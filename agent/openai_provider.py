"""Real OpenAI LLM Provider implementation using official OpenAI SDK.

Uses real tool/function calling API. Reads API key from the environment.
Credentials are never hardcoded.
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from agent.provider import LLMMessage, LLMProvider, LLMResponse, ToolCall
from agent.tools.base import BaseTool

# Load .env if present
load_dotenv()


class ProviderError(Exception):
    """Base exception for LLM provider errors."""


class ProviderAuthenticationError(ProviderError):
    """Raised when API key is missing or invalid."""


class ProviderAPIError(ProviderError):
    """Raised when the LLM provider API returns a request error."""


class OpenAIProvider(LLMProvider):
    """Live LLM provider backed by OpenAI Chat Completions API with Tool Calling."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key or not self.api_key.strip():
            raise ProviderAuthenticationError(
                "OPENAI_API_KEY is not set. Please set the environment variable or define it in your .env file."
            )

        self.model = model
        self.temperature = temperature
        self._client = OpenAI(api_key=self.api_key)

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert internal LLMMessage objects to OpenAI API dictionary format."""
        converted: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role}

            if msg.role == "tool":
                entry["tool_call_id"] = msg.tool_call_id
                entry["content"] = msg.content or ""
                if msg.name:
                    entry["name"] = msg.name
            elif msg.role == "assistant":
                entry["content"] = msg.content
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.tool_name,
                                "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
            else:
                entry["content"] = msg.content or ""

            converted.append(entry)
        return converted

    def generate(
        self,
        messages: list[LLMMessage],
        tools: list[BaseTool] | None = None,
    ) -> LLMResponse:
        """Execute real completion request against OpenAI API."""
        openai_messages = self._convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": self.temperature,
        }

        if tools:
            kwargs["tools"] = [t.to_openai_tool() for t in tools]

        try:
            response = self._client.chat.completions.create(**kwargs)
        except AuthenticationError as e:
            raise ProviderAuthenticationError(f"OpenAI Authentication failed: {e.message}") from e
        except RateLimitError as e:
            raise ProviderAPIError(f"OpenAI rate limit exceeded: {e.message}") from e
        except APIConnectionError as e:
            raise ProviderAPIError(f"Failed to connect to OpenAI API: {e.message}") from e
        except OpenAIError as e:
            raise ProviderAPIError(f"OpenAI API call failed: {e!s}") from e

        if not response.choices:
            raise ProviderAPIError("OpenAI returned empty completion choices.")

        choice = response.choices[0]
        choice_msg = choice.message

        parsed_tool_calls: list[ToolCall] = []
        if choice_msg.tool_calls:
            for raw_tc in choice_msg.tool_calls:
                call_id = raw_tc.id
                fn_name = raw_tc.function.name
                raw_args = raw_tc.function.arguments
                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    parsed_args = {"raw_arguments": raw_args}

                parsed_tool_calls.append(
                    ToolCall(
                        call_id=call_id,
                        tool_name=fn_name,
                        arguments=parsed_args,
                    )
                )

        return LLMResponse(
            content=choice_msg.content,
            tool_calls=parsed_tool_calls,
            finish_reason=choice.finish_reason,
            model=response.model,
        )
