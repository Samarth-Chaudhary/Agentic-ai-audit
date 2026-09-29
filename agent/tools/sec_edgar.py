"""SEC EDGAR XBRL financial research tool for AI Agent Governance.

Reads authentic corporate financial statements from SEC EDGAR filings via the public XBRL API.
"""

from __future__ import annotations

from typing import Any

from agent.data.edgar_loader import EdgarDataLoader
from agent.tools.base import BaseTool, ToolExecutionError


class SecEdgarTool(BaseTool):
    """Tool for querying authentic corporate financial facts from SEC EDGAR XBRL filings."""

    def __init__(self, data_loader: EdgarDataLoader | None = None) -> None:
        self.loader = data_loader or EdgarDataLoader()

    @property
    def name(self) -> str:
        return "sec_edgar_research"

    @property
    def description(self) -> str:
        return (
            "Query authentic US SEC EDGAR corporate filings and XBRL company facts for public companies "
            "(e.g. AAPL, MSFT, AMZN, GOOGL, TSLA). Returns filed revenue, net income, operating income, "
            "total assets, and R&D expenses with accession numbers and filing dates."
        )

    @property
    def data_source(self) -> str:
        return "sec_edgar_xbrl_api"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["ticker", "metric"],
            "properties": {
                "ticker": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Stock ticker symbol (e.g. 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'TSLA').",
                },
                "metric": {
                    "type": "string",
                    "enum": ["revenue", "net_income", "operating_income", "total_assets", "rnd_expense", "overview"],
                    "description": "Financial metric to retrieve.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "default": 2023,
                    "description": "Fiscal year (e.g. 2023, 2022). Defaults to 2023.",
                },
            },
            "additionalProperties": False,
        }

    def execute(
        self,
        ticker: str,
        metric: str,
        fiscal_year: int = 2023,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute query against SEC EDGAR XBRL facts."""
        clean_ticker = str(ticker).strip().upper()
        clean_metric = str(metric).strip().lower()

        try:
            if clean_metric == "overview":
                return self.loader.get_company_overview(clean_ticker, fiscal_year=fiscal_year)
            return self.loader.query_financial_metric(clean_ticker, clean_metric, fiscal_year=fiscal_year)
        except Exception as e:
            raise ToolExecutionError(f"SEC EDGAR query failed: {e}") from e
