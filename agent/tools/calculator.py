"""Safe AST-based arithmetic calculator tool for AI Agent Governance.

SAFE EXECUTION: Uses an explicit abstract syntax tree (AST) grammar evaluator.
Never uses unsafe python eval() or exec().
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

from agent.tools.base import BaseTool

# Supported binary arithmetic operators
SAFE_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Supported unary operators
SAFE_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class SafeExpressionEvaluator(ast.NodeVisitor):
    """Safely evaluates numeric mathematical expressions without arbitrary code execution."""

    def visit(self, node: ast.AST) -> int | float:
        method_name = f"visit_{node.__class__.__name__}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported syntax expression element: '{node.__class__.__name__}'.")

    def visit_Expression(self, node: ast.Expression) -> int | float:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> int | float:
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"Only numeric constants are allowed, got {type(node.value).__name__}.")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> int | float:
        op_type = type(node.op)
        if op_type not in SAFE_UNARY_OPERATORS:
            raise ValueError(f"Unsupported unary operator: '{op_type.__name__}'.")
        operand = self.visit(node.operand)
        return SAFE_UNARY_OPERATORS[op_type](operand)

    def visit_BinOp(self, node: ast.BinOp) -> int | float:
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported binary operator: '{op_type.__name__}'.")

        left = self.visit(node.left)
        right = self.visit(node.right)

        # Guard against extreme exponents to prevent DoS
        if op_type is ast.Pow and (abs(right) > 100 or abs(left) > 1e6):
            raise OverflowError("Exponentiation operands exceed safety limits.")

        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ZeroDivisionError("Division or modulo by zero.")

        return SAFE_OPERATORS[op_type](left, right)


class CalculatorTool(BaseTool):
    """Tool for performing safe mathematical operations."""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return (
            "Perform safe mathematical calculations and arithmetic expressions "
            "(e.g., '120.00 * 0.15' or '45.50 + 12.00'). Evaluates purely numeric syntax."
        )

    @property
    def data_source(self) -> str:
        return "local_calculator_utility"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["expression"],
            "properties": {
                "expression": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Mathematical expression string to evaluate (e.g. '(120 - 45) * 1.08').",
                }
            },
            "additionalProperties": False,
        }

    def execute(self, expression: str, **kwargs: Any) -> dict[str, Any]:
        """Safely evaluate arithmetic expression using AST visitor."""
        clean_expr = str(expression).strip()
        if not clean_expr:
            return {
                "success": False,
                "expression": expression,
                "error": "Expression cannot be empty.",
                "result": None,
            }

        try:
            tree = ast.parse(clean_expr, mode="eval")
            evaluator = SafeExpressionEvaluator()
            result = evaluator.visit(tree)
            # Round floats to 4 decimals for clean reporting
            formatted_result = round(result, 4) if isinstance(result, float) else result
            return {
                "success": True,
                "expression": clean_expr,
                "result": formatted_result,
                "data_source": self.data_source,
                "backend": "safe_ast_calculator",
            }
        except ZeroDivisionError:
            return {
                "success": False,
                "expression": clean_expr,
                "error": "Division by zero is undefined.",
                "result": None,
            }
        except OverflowError:
            return {
                "success": False,
                "expression": clean_expr,
                "error": "Numeric calculation overflowed safety bounds.",
                "result": None,
            }
        except Exception as e:
            return {
                "success": False,
                "expression": clean_expr,
                "error": f"Invalid or unsafe arithmetic expression: {e!s}",
                "result": None,
            }
