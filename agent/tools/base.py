"""Base interface and abstract definition for agent tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import jsonschema


class ToolError(Exception):
    """Base exception for all tool failures."""


class ToolInputValidationError(ToolError):
    """Raised when provided arguments fail the tool's JSON schema validation."""


class ToolExecutionError(ToolError):
    """Raised when an internal error occurs during tool execution."""


class BaseTool(ABC):
    """Abstract base class for all agent execution tools.

    Each tool exposes structured schemas for LLM function calling,
    a data source identifier for governance auditing, and deterministic validation.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable unique identifier for the tool."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Natural-language description guiding the LLM on tool usage."""

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema defining the accepted input arguments."""

    @property
    @abstractmethod
    def data_source(self) -> str:
        """Identifier for the data source or backend backing this tool."""

    def validate_input(self, arguments: dict[str, Any]) -> None:
        """Validate input arguments against the tool's parameter schema."""
        if not isinstance(arguments, dict):
            raise ToolInputValidationError(
                f"Arguments for tool '{self.name}' must be a dictionary, got {type(arguments).__name__}"
            )
        try:
            jsonschema.validate(instance=arguments, schema=self.parameters_schema)
        except jsonschema.ValidationError as e:
            raise ToolInputValidationError(
                f"Validation failed for tool '{self.name}' input: {e.message}"
            ) from e

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert tool definition into OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    @abstractmethod
    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the tool logic and return structured output."""

    def __call__(self, **kwargs: Any) -> Any:
        """Validate input and execute tool."""
        self.validate_input(kwargs)
        return self.execute(**kwargs)
