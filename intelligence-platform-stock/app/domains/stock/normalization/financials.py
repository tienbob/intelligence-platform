"""
Financial statement normalization — merges income / balance / cash-flow
from multiple providers into a single canonical FinancialStatement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def normalize_financial_statement(
    income: dict[str, Any] | None = None,
    balance: dict[str, Any] | None = None,
    cashflow: dict[str, Any] | None = None,
    source: str = "FMP",
) -> dict[str, Any]:
    """
    Merge data from three statement types into one canonical record.

    All three should share the same period.
    """
    ref = income or balance or cashflow or {}
    period = ref.get("period", "")
    period_type = ref.get("period_type", "quarterly")
    currency = ref.get("currency", "USD")

    return {
        "period": period,
        "period_type": period_type,
        "currency": currency,
        # Income
        "revenue": (income or {}).get("revenue"),
        "gross_profit": (income or {}).get("gross_profit"),
        "operating_income": (income or {}).get("operating_income"),
        "net_income": (income or {}).get("net_income"),
        "eps": (income or {}).get("eps"),
        # Balance
        "total_assets": (balance or {}).get("total_assets"),
        "total_liabilities": (balance or {}).get("total_liabilities"),
        "total_debt": (balance or {}).get("total_debt"),
        "cash": (balance or {}).get("cash"),
        "shareholders_equity": (balance or {}).get("shareholders_equity"),
        # Cash flow
        "operating_cash_flow": (cashflow or {}).get("operating_cash_flow"),
        "capital_expenditure": (cashflow or {}).get("capital_expenditure"),
        "free_cash_flow": (cashflow or {}).get("free_cash_flow"),
        # Provenance
        "source": source,
        "source_id": ref.get("source_id"),
        "filed_date": ref.get("filed_date"),
    }