"""Agent tools package exposing standard tools and registry."""

from agent.tools.base import (
    BaseTool,
    ToolError,
    ToolExecutionError,
    ToolInputValidationError,
)
from agent.tools.calculator import CalculatorTool
from agent.tools.order_lookup import OrderLookupTool
from agent.tools.refund_tool import RefundTool
from agent.tools.web_search import WebSearchTool


def get_default_tools() -> dict[str, BaseTool]:
    """Instantiate and return standard tools keyed by tool name."""
    tools = [
        OrderLookupTool(),
        RefundTool(),
        WebSearchTool(),
        CalculatorTool(),
    ]
    return {t.name: t for t in tools}


def get_tools_for_task(allowed_tool_names: list[str]) -> list[BaseTool]:
    """Return initialized tool instances for a list of permitted tool names."""
    all_tools = get_default_tools()
    return [all_tools[name] for name in allowed_tool_names if name in all_tools]


__all__ = [
    "BaseTool",
    "CalculatorTool",
    "OrderLookupTool",
    "RefundTool",
    "ToolError",
    "ToolExecutionError",
    "ToolInputValidationError",
    "WebSearchTool",
    "get_default_tools",
    "get_tools_for_task",
]
