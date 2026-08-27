"""
Framework tests: provider capability conformance + observation boundary.

Uses synthetic/fake providers where possible (no network, no DB). Verifies:

  - framework_capabilities() honors explicit declarations over duck-typing
  - natural (undeclared) providers are detected via duck-typing
  - each Stock capability adapter satisfies the protocols it declares
  - the generic observation → evidence boundary works domain-agnostically
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.contracts import (  # noqa: E402
    CapabilityProvider,
    EntityDataProvider,
    NewsProvider,
    SearchProvider,
    TimeSeriesProvider,
)
from app.intelligence.observations import (  # noqa: E402
    evidence_from_vendor_records,
    make_observation,
    observations_to_evidence,
)
from app.intelligence.providers import framework_capabilities, has_capability  # noqa: E402
from app.shared.entities import EntityRef  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ── framework_capabilities: declaration over duck-typing ────────

def test_declared_capabilities_are_authoritative():
    class FakeAdapter:
        # base class defines all generic methods → duck-typing would match all
        framework_capabilities = {"time_series"}

        async def fetch(self, *a, **k): return []
        async def get_series(self, *a, **k): return []
        async def search_news(self, *a, **k): return []
        async def get_company_news(self, *a, **k): return []
        async def search(self, *a, **k): return []
        async def health_check(self): return True

    caps = framework_capabilities(FakeAdapter())
    assert caps == {"time_series"}


def test_declared_unknown_caps_are_filtered():
    class Decl:
        capabilities = {"time_series", "terraform", "time_machine"}

    assert framework_capabilities(Decl()) == {"time_series"}


def test_ducktyping_detects_natural_provider_without_declaration():
    class NaturalProvider:
        provider_name = "natural"

        async def fetch(self, entity_ref, **k): return []
        async def health_check(self): return True

    assert framework_capabilities(NaturalProvider()) == {"entity_data"}
    assert has_capability(NaturalProvider(), "entity_data")
    assert not has_capability(NaturalProvider(), "news")


def test_ducktyping_matches_protocol_via_isinstance():
    class TSOnly:
        def get_series(self, *a, **k): return []
# ── Stock capability adapters (real, but no network) ────────────

def test_stock_adapters_satisfy_declared_protocols():
    from app.domains.stock.providers.capabilities import build_capability_providers

    providers = build_capability_providers()

    massive = providers["massive"]
    assert isinstance(massive, CapabilityProvider)          # has health_check
    assert isinstance(massive, EntityDataProvider)
    assert isinstance(massive, TimeSeriesProvider)
    assert isinstance(massive, NewsProvider)
    assert has_capability(massive, "news")

    fmp = providers["fmp"]
    assert isinstance(fmp, CapabilityProvider)
    assert has_capability(fmp, "time_series")
    assert not has_capability(fmp, "news")

    fred = providers["fred"]
    assert isinstance(fred, TimeSeriesProvider)
    assert not has_capability(fred, "entity_data")

    sec = providers["sec"]
    assert isinstance(sec, SearchProvider)
    assert has_capability(sec, "search")
    assert not has_capability(sec, "news")


def test_stock_adapter_health_check_true():
    from app.domains.stock.providers.capabilities import build_capability_providers

    for name, adapter in build_capability_providers().items():
        assert run(adapter.health_check()) is True, name


# ── Observation boundary ────────────────────────────────────────

def test_make_observation_sets_kind_and_source():
    ref = EntityRef(domain="hr", entity_type="candidate", entity_id="c-1")
    obs = make_observation(
        ref, source="workday", data={"name": "Alice"}, kind="employee"
    )
    assert obs.kind == "employee"
    assert obs.source == "workday"
    assert obs.entity_ref == ref
    assert obs.data == {"name": "Alice"}


def test_observations_to_evidence_extracts_conventional_fields():
    obs = make_observation(
        EntityRef("stock", "company", "AAPL"),
        source="massive",
        data={"metric": "pe_ratio", "value": 28.5, "period": "2025Q4"},
        kind="quote",
    )
    ev = observations_to_evidence([obs])[0]
    assert ev.metric == "pe_ratio"
    assert ev.value == 28.5
    assert ev.period == "2025Q4"
    assert ev.source_name == "massive"
    assert ev.confidence == 1.0


def test_observations_to_evidence_falls_back_to_raw_data():
    obs = make_observation(
        EntityRef("stock", "company", "MSFT"),
        source="fmp",
        data={"revenue": 200_000_000},
    )
    ev = observations_to_evidence([obs])[0]
    assert ev.metric is None
    assert ev.value == {"revenue": 200_000_000}
    assert ev.source_name == "fmp"


def test_evidence_from_vendor_records_shortcut():
    records = [
        {"metric": "eps", "value": 6.1},
        {"metric": "revenue", "value": 1e9},
    ]
    out = evidence_from_vendor_records(
        EntityRef("stock", "company", "AAPL"),
        source="fmp",
        records=records,
    )
    assert len(out) == 2
    assert all(e.source_name == "fmp" for e in out)
    assert [e.metric for e in out] == ["eps", "revenue"]


def test_observation_boundary_is_domain_neutral():
    # Same machinery, two different domains → proves generalization.
    stock_obs = make_observation(
        EntityRef("stock", "company", "AAPL"), source="massive",
        data={"metric": "pe", "value": 30}, kind="quote",
    )
    hr_obs = make_observation(
        EntityRef("hr", "candidate", "c-7"), source="workday",
        data={"metric": "years_experience", "value": 9, "period": "2025"}, kind="employee",
    )
    s_ev, h_ev = observations_to_evidence([stock_obs, hr_obs])
    assert s_ev.source_name == "massive" and s_ev.metric == "pe"
    assert h_ev.source_name == "workday" and h_ev.metric == "years_experience"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)

    assert isinstance(TSOnly(), TimeSeriesProvider)
    assert not isinstance(TSOnly(), SearchProvider)