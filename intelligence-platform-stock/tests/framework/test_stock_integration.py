"""
Framework tests: Stock DomainModule integration (Phase 8).

Verifies that:
  1. Every manifest accessor returns a real, consumable object (no
     placeholder markers).
  2. InvestmentScoringStrategy delegates to the production engine and
     maps InvestmentScore rows faithfully (unit-tested with fakes).
  3. The framework execution path resolves entities through the generic
     service.

Run with pytest (monkeypatch fixture required for the scoring tests).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.shared.entities import EntityRef  # noqa: E402


def _domain():
    from app.domains.stock.manifest import StockDomain

    return StockDomain()


# ── Manifest contract reality ────────────────────────────────────

def test_manifest_providers_are_real_objects():
    providers = _domain().get_providers()
    assert set(providers) == {"fmp", "finnhub", "fred", "sec", "massive"}
    for name, provider in providers.items():
        assert provider is not None, f"provider '{name}' is None"


def test_manifest_normalizers_are_real_callables():
    normalizers = _domain().get_normalizers()
    expected = {
        "company_ticker", "company_name",
        "price", "financial", "news", "event",
    }
    assert set(normalizers) == expected
    for name, norm in normalizers.items():
        assert callable(norm), f"normalizer '{name}' is not callable"


def test_manifest_normalizers_actually_normalize():
    normalizers = _domain().get_normalizers()
    assert normalizers["company_ticker"]("nasdaq:aapl") == "AAPL"
    assert (
        normalizers["company_name"]("Apple Inc.")
        == "apple"
    )


def test_manifest_context_builder_is_real_and_concrete():
    builder = _domain().get_context_builder()
    assert callable(getattr(builder, "build", None))
    src = type(builder).__module__
    assert "stock" in src


def test_manifest_scoring_strategy_has_no_placeholder():
    from app.domains.stock.scoring.scoring_strategy import InvestmentScoringStrategy

    strategy = _domain().get_scoring_strategy()
    assert isinstance(strategy, InvestmentScoringStrategy)
    # The old placeholder returned a 'note' explaining non-migration;
    # ensure the class no longer contains any stub text.
    import inspect

    source = inspect.getsource(InvestmentScoringStrategy)
    assert "Placeholder" not in source
    assert "not yet migrated" not in source
    assert "InvestmentScoringEngine" in source


def test_manifest_prompts_registry_loads_templates():
    registry = _domain().get_prompts()
    names = registry.names()
    assert "company_analysis" in names
    prompt = registry.get("company_analysis")
    assert isinstance(prompt, str) and len(prompt) > 50


# ── Scoring strategy delegation (fakes, no DB) ───────────────────

class _FakeScoreRow:
    id = 101
    overall_score = 62.4
    confidence = 0.83
    recommendation = "HOLD"
    fundamental_score = 70.0
    valuation_score = 55.0
    growth_score = 60.0
    technical_score = 45.0
    sentiment_score = 58.0
    catalyst_score = 52.0
    risk_score = 24.9
    scoring_model = "weighted_v1"
    scoring_version = "1.0"


class _FakeCompany:
    id = 42


class _FakeResolver:
    def __init__(self, session):
        pass

    async def resolve(self, ticker=None, **kw):
        assert ticker == "AAPL"
        return _FakeCompany()


class _FakeEngine:
    def __init__(self, session):
        pass

    async def calculate_score(self, company_id):
        assert company_id == 42
        return _FakeScoreRow()


class _FakeSessionCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _patch(monkeypatch):
    import app.domains.stock.normalization.companies as companies_mod
    import app.domains.stock.scoring.investment_scoring as inv_mod
    import app.domains.stock.scoring.scoring_strategy as strategy_mod

    monkeypatch.setattr(
        strategy_mod, "async_session_factory", lambda: _FakeSessionCM()
    )
    monkeypatch.setattr(companies_mod, "EntityResolver", _FakeResolver)
    monkeypatch.setattr(inv_mod, "InvestmentScoringEngine", _FakeEngine)


def test_scoring_strategy_maps_engine_row_faithfully(monkeypatch):
    _patch(monkeypatch)
    from app.domains.stock.scoring.scoring_strategy import InvestmentScoringStrategy

    result = asyncio.run(
        InvestmentScoringStrategy().score(
            EntityRef("stock", "company", "AAPL"), None, {}
        )
    )
    assert result["score"] == 62.4
    assert result["confidence"] == 0.83
    assert result["recommendation"] == "HOLD"
    assert result["components"]["fundamental"] == 70.0
    assert result["components"]["risk"] == 24.9
    assert set(result["components"]) == {
        "fundamental", "valuation", "growth", "technical",
        "sentiment", "catalyst", "risk",
    }
    assert result["metadata"]["score_id"] == 101
    assert result["scoring_model"] == "weighted_v1"
    assert result["scoring_version"] == "1.0"


def test_scoring_strategy_raises_for_unknown_ticker(monkeypatch):
    class _NoCompanyResolver(_FakeResolver):
        async def resolve(self, ticker=None, **kw):
            return None

    import app.domains.stock.normalization.companies as companies_mod
    import app.domains.stock.scoring.scoring_strategy as strategy_mod

    monkeypatch.setattr(
        strategy_mod, "async_session_factory", lambda: _FakeSessionCM()
    )
    monkeypatch.setattr(companies_mod, "EntityResolver", _NoCompanyResolver)

    from app.domains.stock.scoring.scoring_strategy import InvestmentScoringStrategy

    raised = False
    try:
        asyncio.run(
            InvestmentScoringStrategy().score(
                EntityRef("stock", "company", "NOPE"), None, {}
            )
        )
    except LookupError as exc:
        raised = True
        assert "NOPE" in str(exc)
    assert raised, "expected LookupError for unknown ticker"


# ── Framework path entity resolution ─────────────────────────────

def test_framework_path_resolves_entity_via_generic_service():
    from app.domains.stock.framework_path import resolve_entity

    # Importing stock normalization registers normalize_ticker with the
    # generic entity-resolution service.
    import app.domains.stock.normalization.companies  # noqa: F401

    ref = asyncio.run(resolve_entity("nasdaq:aapl"))
    assert ref.domain == "stock"
    assert ref.entity_type == "company"
    assert ref.entity_id == "AAPL"
