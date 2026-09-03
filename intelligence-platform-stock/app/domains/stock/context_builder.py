"""
Stock domain context builder — builds structured context for LLM analysis.

Adapts the original ContextBuilder (scoring/context_builder.py) to the
domain-neutral IntelligenceContext format. Instead of accepting a SQLAlchemy
session, this builder extracts data from pipeline Observations collected by
the generic provider ``fetch()`` protocol (kinds: price_quote, news,
financials, balance_sheet, cash_flow, ratios, profile, macro, insider,
institutional).
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.shared.entities import EntityRef, Evidence, IntelligenceContext, Observation

logger = get_logger(__name__)


def _by_kind(observations: list[Observation], *kinds: str) -> list[Observation]:
    return [o for o in observations if o.kind in kinds]


class StockContextBuilder:
    """
    Builds structured intelligence context for stock analysis.

    Sections:
        - Market snapshot (price, volume, change)
        - Technical snapshot (momentum derived from quotes)
        - Fundamental snapshot (revenue, margins, growth from statements)
        - News snapshot (recent headlines)
        - Event snapshot (insider/institutional activity)
        - Macro snapshot (FRED indicators)
        - Risk snapshot (engine-owned; noted in context)
    """

    async def build(
        self,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
        **kwargs: Any,
    ) -> IntelligenceContext:
        """Build the full intelligence context for a stock entity."""
        ticker = entity_ref.entity_id

        quotes = _by_kind(observations, "price_quote")
        news = _by_kind(observations, "news")
        financials = _by_kind(observations, "financials")
        balances = _by_kind(observations, "balance_sheet")
        cashflows = _by_kind(observations, "cash_flow")
        ratios = _by_kind(observations, "ratios")
        profiles = _by_kind(observations, "profile")
        macro = _by_kind(observations, "macro")
        insider = _by_kind(observations, "insider")
        institutional = _by_kind(observations, "institutional")

        profile: dict[str, Any] = {}
        if profiles and isinstance(profiles[0].data, dict):
            profile = profiles[0].data

        context = IntelligenceContext(
            entity={
                "id": ticker,
                "ticker": ticker,
                "name": profile.get("name") or profile.get("companyName") or ticker,
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "market_cap": profile.get("marketCap"),
                "domain": entity_ref.domain,
                "entity_type": entity_ref.entity_type,
            },
            evidence=evidence,
            observations=observations,
            rag_context=rag_context,
            domain_snapshots={
                "market_snapshot": self._build_market_snapshot(quotes),
                "technical_snapshot": self._build_technical_snapshot(quotes),
                "fundamental_snapshot": self._build_fundamental_snapshot(
                    financials, balances, cashflows, ratios
                ),
                "news_snapshot": self._build_news_snapshot(news),
                "event_snapshot": self._build_event_snapshot(insider, institutional),
                "macro_snapshot": self._build_macro_snapshot(macro),
                "risk_snapshot": self._build_risk_snapshot(),
            },
            metadata={
                "ticker": ticker,
                "context_version": "2.0",
            },
        )

        logger.info(
            "Built full context for %s (obs=%d, evidence=%d, rag=%s)",
            ticker,
            len(observations),
            len(evidence),
            bool(rag_context),
        )
        return context

    # ── Snapshot builders (data extracted from observations) ─────────

    @staticmethod
    def _build_market_snapshot(quote_obs: list[Observation]) -> dict[str, Any]:
        """Market snapshot from the latest provider quote."""
        if not quote_obs:
            return {}
        q = quote_obs[0].data if isinstance(quote_obs[0].data, dict) else {}
        return {
            "latest_price": q.get("price") or q.get("close"),
            "latest_volume": q.get("volume"),
            "price_change_1d_pct": q.get("change_percent"),
            "latest_date": q.get("timestamp"),
            "source": quote_obs[0].source,
        }

    @staticmethod
    def _build_technical_snapshot(quote_obs: list[Observation]) -> dict[str, Any]:
        """Technical snapshot — derives 1d momentum from quotes.

        Detailed indicators (SMA/RSI/MACD) are owned by the domain scoring
        engine (InvestmentScoringEngine); the context supplies only what the
        LLM can reason about directly from provider data.
        """
        q = quote_obs[0].data if quote_obs and isinstance(quote_obs[0].data, dict) else {}
        return {
            "momentum_1d_pct": q.get("change_percent"),
            "note": (
                "Detailed technical indicators (SMA/RSI/MACD) are computed "
                "by the domain scoring engine and reflected in the score."
            ),
        }

    @staticmethod
    def _build_fundamental_snapshot(
        financials: list[Observation],
        balances: list[Observation],
        cashflows: list[Observation],
        ratios: list[Observation],
    ) -> dict[str, Any]:
        """Fundamental snapshot from income/balance/cash-flow statements."""
        snap: dict[str, Any] = {}

        latest_income: dict[str, Any] = {}
        prev_income: dict[str, Any] | None = None
        if financials and isinstance(financials[0].data, list):
            rows = [r for r in financials[0].data if isinstance(r, dict)]
            if rows and "revenue" in rows[0]:
                # FMP-style: newest-first statement rows
                latest_income = rows[0]
                prev_income = rows[1] if len(rows) > 1 else None
            elif rows:
                # SEC-style concept rows: {"concept": ..., "value": ...}
                concepts: dict[str, Any] = {}
                for r in rows:
                    concepts.setdefault(r.get("concept"), r.get("value"))
                latest_income = {
                    "revenue": concepts.get("revenue"),
                    "net_income": concepts.get("net_income"),
                }

        if latest_income:
            revenue = latest_income.get("revenue")
            net_income = latest_income.get("net_income")
            gross_profit = latest_income.get("gross_profit")
            snap.update(
                {
                    "revenue": revenue,
                    "net_income": net_income,
                    "gross_margin": (
                        round(gross_profit / revenue, 4)
                        if revenue and gross_profit
                        else None
                    ),
                    "net_margin": (
                        round(net_income / revenue, 4)
                        if revenue and net_income
                        else None
                    ),
                }
            )
            if prev_income and prev_income.get("revenue") and revenue:
                snap["revenue_growth_yoy"] = round(
                    (revenue - prev_income["revenue"]) / prev_income["revenue"], 4
                )

        if balances and isinstance(balances[0].data, list):
            rows = [r for r in balances[0].data if isinstance(r, dict)]
            if rows and "total_assets" in rows[0]:
                b = rows[0]
                snap.update(
                    {
                        "total_assets": b.get("total_assets"),
                        "total_debt": b.get("total_debt"),
                        "shareholders_equity": b.get("shareholders_equity"),
                        "cash": b.get("cash"),
                    }
                )
            elif rows:
                concepts: dict[str, Any] = {}
                for r in rows:
                    concepts.setdefault(r.get("concept"), r.get("value"))
                snap.update(
                    {
                        "total_assets": concepts.get("total_assets"),
                        "total_debt": concepts.get("total_debt"),
                        "shareholders_equity": concepts.get("shareholders_equity"),
                    }
                )

        if cashflows and isinstance(cashflows[0].data, list):
            rows = [r for r in cashflows[0].data if isinstance(r, dict)]
            if rows:
                c = rows[0]
                snap.update(
                    {
                        "operating_cash_flow": c.get("operating_cash_flow"),
                        "free_cash_flow": c.get("free_cash_flow"),
                    }
                )

        if ratios and isinstance(ratios[0].data, list):
            rows = [r for r in ratios[0].data if isinstance(r, dict)]
            if rows:
                r0 = rows[0]
                snap.update(
                    {
                        "pe_ratio": r0.get("priceEarningsRatio"),
                        "roe": r0.get("returnOnEquity"),
                        "debt_to_equity": r0.get("debtEquityRatio"),
                    }
                )

        return snap

    @staticmethod
    def _build_news_snapshot(news_obs: list[Observation]) -> dict[str, Any]:
        """News snapshot from provider news observations."""
        articles: list[dict[str, Any]] = []
        for obs in news_obs:
            items = obs.data if isinstance(obs.data, list) else [obs.data]
            for a in items:
                if isinstance(a, dict) and a.get("title"):
                    articles.append(
                        {
                            "title": a.get("title", ""),
                            "summary": (a.get("summary") or "")[:280],
                            "source": obs.source,
                            "published_at": a.get("published_at"),
                            "url": a.get("url"),
                            "sentiment": a.get("sentiment"),
                        }
                    )
        return {
            "recent_news": articles[:10],
            "news_count": len(articles),
        }

    @staticmethod
    def _build_event_snapshot(
        insider: list[Observation], institutional: list[Observation]
    ) -> dict[str, Any]:
        """Event snapshot from insider/institutional activity."""
        events: list[dict[str, Any]] = []
        for obs in insider:
            items = obs.data if isinstance(obs.data, list) else []
            for t in items[:5]:
                if isinstance(t, dict):
                    events.append(
                        {
                            "type": "insider_transaction",
                            "insider": t.get("insider_name"),
                            "transaction_type": t.get("transaction_type"),
                            "shares": t.get("shares"),
                            "date": t.get("transaction_date"),
                        }
                    )
        for obs in institutional:
            items = obs.data if isinstance(obs.data, list) else []
            for o in items[:5]:
                if isinstance(o, dict):
                    events.append(
                        {
                            "type": "institutional_ownership_change",
                            "institution": o.get("institution"),
                            "percent_change": o.get("percent_change"),
                            "date": o.get("filing_date"),
                        }
                    )
        return {"recent_events": events, "event_count": len(events)}

    @staticmethod
    def _build_macro_snapshot(macro_obs: list[Observation]) -> dict[str, Any]:
        """Macro snapshot from FRED indicator observations."""
        data: dict[str, Any] = {}
        for obs in macro_obs:
            items = obs.data if isinstance(obs.data, list) else [obs.data]
            for item in items:
                if isinstance(item, dict):
                    metric = item.get("indicator") or item.get("series")
                    value = item.get("value")
                    if metric and value is not None:
                        data[str(metric)] = value
        return {
            "indicators": data,
            "note": "Macro indicators sourced from provider observations",
        }

    @staticmethod
    def _build_risk_snapshot() -> dict[str, Any]:
        """Risk snapshot — engine-owned; noted in context."""
        return {
            "risk_score": None,
            "volatility": None,
            "note": (
                "Risk metrics computed by domain scoring engine "
                "and reflected in the score components."
            ),
        }
