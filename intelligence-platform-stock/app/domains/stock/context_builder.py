"""
Stock domain context builder — builds structured context for LLM analysis.

Adapts the original ContextBuilder from market-intelligence/app/services/context_builder.py
to the domain-neutral IntelligenceContext format.

When migrating, copy the original implementation and adapt the build() method
to return an IntelligenceContext instead of a raw dict.
"""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef, Evidence, IntelligenceContext, Observation


class StockContextBuilder:
    """
    Builds structured intelligence context for stock analysis.

    Sections:
        - Market snapshot (price, volume, 30d range)
        - Technical snapshot (SMA, RSI, MACD, Bollinger, volatility)
        - Fundamental snapshot (P/E, ROE, margins, growth, debt)
        - News snapshot (recent headlines, sentiment)
        - Event snapshot (market events, catalysts)
        - Macro snapshot (interest rates, economic indicators)
        - Risk snapshot (volatility, drawdown, event risk)
        - RAG context (similar historical events)
    """

    async def build(
        self,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
        **kwargs: Any,
    ) -> IntelligenceContext:
        """
        Build the full intelligence context for a stock entity.

        Args:
            entity_ref: Reference to the company entity (e.g., ticker "AAPL")
            evidence: Collected evidence from providers
            observations: Normalized observations
            rag_context: RAG retrieval results
            **kwargs: Additional domain-specific parameters

        Returns:
            IntelligenceContext ready for LLM consumption
        """
        # TODO: Migrate the original ContextBuilder logic here.
        # The original implementation is in:
        #   market-intelligence/app/services/context_builder.py
        #
        # Key adaptation: instead of accepting a SQLAlchemy session and Company model,
        # accept EntityRef + observations + evidence. The original methods like
        # build_market_snapshot(), build_technical_snapshot(), etc. should be
        # adapted to work with the observations list.

        ticker = entity_ref.entity_id

        context = IntelligenceContext(
            entity={
                "ticker": ticker,
                "domain": entity_ref.domain,
                "entity_type": entity_ref.entity_type,
            },
            evidence=evidence,
            observations=observations,
            rag_context=rag_context,
            domain_snapshots={
                "market_snapshot": self._build_market_snapshot(observations),
                "technical_snapshot": self._build_technical_snapshot(observations),
                "fundamental_snapshot": self._build_fundamental_snapshot(observations),
                "news_snapshot": self._build_news_snapshot(observations),
                "event_snapshot": self._build_event_snapshot(observations),
                "macro_snapshot": self._build_macro_snapshot(observations),
                "risk_snapshot": self._build_risk_snapshot(observations),
            },
            metadata={
                "ticker": ticker,
                "context_version": "2.0",
            },
        )

        return context

    # ── Snapshot builders (placeholder — migrate from original) ──

    @staticmethod
    def _build_market_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build market data snapshot from observations."""
        # TODO: Migrate from original ContextBuilder.build_market_snapshot()
        price_obs = [o for o in observations if o.source in ("fmp", "massive")]
        if not price_obs:
            return {}
        latest = price_obs[-1].data if price_obs else {}
        return {
            "latest_price": latest.get("close"),
            "latest_volume": latest.get("volume"),
            "source": "provider_observations",
        }

    @staticmethod
    def _build_technical_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build technical indicator snapshot."""
        # TODO: Migrate from original ContextBuilder.build_technical_snapshot()
        return {
            "sma_20": None,
            "sma_50": None,
            "rsi_14": None,
            "macd": None,
            "note": "Technical indicators computed by domain scoring engine",
        }

    @staticmethod
    def _build_fundamental_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build fundamental data snapshot."""
        # TODO: Migrate from original ContextBuilder.build_fundamental_snapshot()
        return {
            "pe_ratio": None,
            "roe": None,
            "revenue_growth": None,
            "note": "Fundamental metrics computed by domain scoring engine",
        }

    @staticmethod
    def _build_news_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build recent news snapshot."""
        news_obs = [o for o in observations if o.source in ("massive", "finnhub")]
        return {
            "recent_news": [
                {"title": o.data.get("title", ""), "source": o.source}
                for o in news_obs[:10]
            ],
            "news_count": len(news_obs),
        }

    @staticmethod
    def _build_event_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build recent events snapshot."""
        return {"recent_events": [], "event_count": 0}

    @staticmethod
    def _build_risk_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build risk metrics snapshot."""
        return {
            "risk_score": None,
            "volatility": None,
            "note": "Risk metrics computed by domain scoring engine",
        }
    @staticmethod
    def _build_macro_snapshot(observations: list[Observation]) -> dict[str, Any]:
        """Build macroeconomic snapshot from macro observations."""
        # TODO: Migrate from original ContextBuilder.build_macro_snapshot()
        macro_obs = [
            o
            for o in observations
            if o.source == "fred" or o.kind == "macro"
        ]
        data: dict[str, Any] = {}
        for o in macro_obs:
            metric = (
                o.data.get("metric")
                or o.data.get("series")
                or f"{o.source}:{o.kind}"
            )
            value = o.data.get("value")
            if value is not None:
                data[str(metric)] = value
        return {
            "indicators": data,
            "note": "Macro indicators sourced from provider observations",
        }
