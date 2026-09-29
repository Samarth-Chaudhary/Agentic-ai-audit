"""SEC EDGAR XBRL data loader and financial research connector.

Pulls real financial facts and 10-K / 10-Q filings directly from the official SEC EDGAR public XBRL API
(https://data.sec.gov/api/xbrl/companyfacts/).
Caches data locally under `data/sec_edgar/` for fast reproducible execution and offline test resilience.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from project.logging import get_logger

logger = get_logger(__name__, component="edgar_loader")

# SEC EDGAR requires a User-Agent header in the format: SampleApp contact@domain.com
SEC_USER_AGENT = "AuditResearchBot/1.0 (contact@governance-audit.org)"

# Standard CIK mappings for major publicly traded corporations
COMPANY_CIKS: dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "TSLA": "0001318605",
}

# Standard GAAP tag aliases
METRIC_TAGS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "total_assets": [
        "Assets",
    ],
    "rnd_expense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
    ],
}


class EdgarDataLoader:
    """Loads and queries authentic corporate financial filings from SEC EDGAR XBRL API."""

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = Path(cache_dir or Path(__file__).resolve().parent.parent.parent / "data" / "sec_edgar")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def resolve_cik(self, ticker_or_cik: str) -> str:
        """Resolve a stock ticker or CIK to a 10-digit zero-padded CIK string."""
        cleaned = ticker_or_cik.strip().upper()
        if cleaned in COMPANY_CIKS:
            return COMPANY_CIKS[cleaned]
        digits = "".join(ch for ch in cleaned if ch.isdigit())
        if digits:
            return digits.zfill(10)
        raise ValueError(f"Unrecognized company ticker or CIK: '{ticker_or_cik}'")

    def fetch_company_facts(self, ticker_or_cik: str, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch full XBRL company facts for a company, caching to disk."""
        cik = self.resolve_cik(ticker_or_cik)
        cache_file = self.cache_dir / f"CIK{cik}.json"

        if not force_refresh and cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read cached SEC EDGAR file {cache_file}: {e}")

        # Fetch live from SEC EDGAR XBRL API
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": SEC_USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Host": "data.sec.gov",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw_data = resp.read()
                # Check for gzip magic header (0x1f, 0x8b)
                if len(raw_data) >= 2 and raw_data[0] == 0x1F and raw_data[1] == 0x8B:
                    import gzip
                    raw_data = gzip.decompress(raw_data)
                data = json.loads(raw_data.decode("utf-8"))
        except Exception as e:
            if cache_file.exists():
                logger.warning(f"SEC EDGAR live fetch failed ({e}); falling back to disk cache.")
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            raise RuntimeError(f"Failed to fetch SEC EDGAR company facts for CIK {cik}: {e}") from e

        # Save to disk cache
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed writing SEC EDGAR cache to {cache_file}: {e}")

        return data

    def query_financial_metric(
        self,
        ticker_or_cik: str,
        metric: str,
        fiscal_year: int,
        form: str = "10-K",
    ) -> dict[str, Any]:
        """Query a specific financial metric for a given fiscal year.

        Returns structured record with exact filed value, accession number, filing date, and source provenance.
        """
        data = self.fetch_company_facts(ticker_or_cik)
        cik = self.resolve_cik(ticker_or_cik)
        entity_name = data.get("entityName", ticker_or_cik.upper())

        norm_metric = metric.strip().lower()
        candidate_tags = METRIC_TAGS.get(norm_metric, [metric])

        gaap_facts = data.get("facts", {}).get("us-gaap", {})

        for tag in candidate_tags:
            if tag not in gaap_facts:
                continue
            units = gaap_facts[tag].get("units", {})
            for unit_key, fact_list in units.items():
                # Filter by fiscal year and form
                matches = [
                    f
                    for f in fact_list
                    if f.get("fy") == fiscal_year and (not form or f.get("form") == form)
                ]
                if matches:
                    # Select latest filing or full year (fp == 'FY')
                    fy_matches = [m for m in matches if m.get("fp") == "FY"]
                    best = fy_matches[-1] if fy_matches else matches[-1]
                    val = best.get("val")
                    accn = best.get("accn", "")
                    filed_date = best.get("filed", "")
                    return {
                        "found": True,
                        "ticker_or_cik": ticker_or_cik.upper(),
                        "cik": cik,
                        "entity_name": entity_name,
                        "metric": norm_metric,
                        "tag": tag,
                        "fiscal_year": fiscal_year,
                        "form": best.get("form", form),
                        "value": val,
                        "unit": unit_key,
                        "formatted_value": f"${val:,.2f}" if unit_key == "USD" and val is not None else str(val),
                        "accession_number": accn,
                        "filing_date": filed_date,
                        "data_source": "sec_edgar_xbrl_api",
                        "edgar_url": f"https://www.sec.gov/edgar/browse/?CIK={cik}",
                        "is_synthetic": False,
                    }

        return {
            "found": False,
            "ticker_or_cik": ticker_or_cik.upper(),
            "cik": cik,
            "entity_name": entity_name,
            "metric": norm_metric,
            "fiscal_year": fiscal_year,
            "form": form,
            "error": f"Metric '{metric}' for fiscal year {fiscal_year} not found in filed XBRL facts.",
            "data_source": "sec_edgar_xbrl_api",
            "is_synthetic": False,
        }

    def get_company_overview(self, ticker_or_cik: str, fiscal_year: int = 2023) -> dict[str, Any]:
        """Produce a comprehensive financial summary of key metrics for a given year."""
        overview: dict[str, Any] = {
            "company": ticker_or_cik.upper(),
            "fiscal_year": fiscal_year,
            "metrics": {},
            "data_source": "sec_edgar_xbrl_api",
            "is_synthetic": False,
        }
        for metric in ["revenue", "net_income", "operating_income", "total_assets", "rnd_expense"]:
            res = self.query_financial_metric(ticker_or_cik, metric, fiscal_year)
            if res.get("found"):
                overview["entity_name"] = res.get("entity_name")
                overview["metrics"][metric] = {
                    "value": res.get("value"),
                    "formatted": res.get("formatted_value"),
                    "tag": res.get("tag"),
                    "accession_number": res.get("accession_number"),
                    "filing_date": res.get("filing_date"),
                }
        return overview
