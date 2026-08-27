"""
Framework tests: canonical Entity Resolution service.

Equivalence contract being verified:

    Stock legacy normalization          Framework resolution
    ------------------------            ------------------------
    normalize_ticker("NASDAQ:AAPL")     resolve(EntityRef(stock/company, "NASDAQ:AAPL"))
    normalize_ticker("aapl")       →    resolve(EntityRef(stock/company, "aapl"))
              "AAPL"                              "AAPL"

Same inputs → same outputs. This is the general → domain consumption
pattern's regression net.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.entity_resolution import (  # noqa: E402
    EntityResolutionService,
    get_entity_resolution_service,
    register_normalizer,
    reset_entity_resolution_service,
)
from app.domains.stock.normalization.companies import (  # noqa: E402
    normalize_company_name,
    normalize_ticker,
)
from app.shared.entities import EntityRef  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ── Legacy Stock behavior (golden reference) ────────────────────

def test_stock_normalize_ticker_reference_cases():
    assert normalize_ticker("NASDAQ:AAPL") == "AAPL"
    assert normalize_ticker("AAPL.US") == "AAPL"
    assert normalize_ticker("aapl") == "AAPL"


def test_framework_matches_legacy_for_tickers():
    svc = get_entity_resolution_service()
    for raw in ("NASDAQ:AAPL", "AAPL.US", "aapl", " AAPL ", "msft"):
        expected = normalize_ticker(raw)
        actual = run(svc.resolve(
            EntityRef(domain="stock", entity_type="company", entity_id=raw)
        ))
        assert actual.entity_id == expected, f"{raw!r}: {actual.entity_id} != {expected}"


# ── Framework default (unchanged generic behavior) ──────────────

def test_default_normalization_unchanged():
    svc = EntityResolutionService()  # fresh instance: no registrations
    # short alpha symbols uppercase
    assert run(svc.resolve(
        EntityRef(domain="hr", entity_type="candidate", entity_id=" abc ")
    )).entity_id == "ABC"
    # longer IDs untouched apart from strip
    long_id = "candidate-12345"
    assert run(svc.resolve(
        EntityRef(domain="hr", entity_type="candidate", entity_id=long_id)
    )).entity_id == long_id


# ── Registration semantics ──────────────────────────────────────

def test_registration_scoped_to_domain_and_type():
    reset_entity_resolution_service()
    svc = get_entity_resolution_service()
    # Restore Stock's production normalizer afterwards — the reset wipes
    # the registration made at domain-import time, and the service is a
    # process-wide singleton other tests rely on.
    from app.domains.stock.normalization.companies import normalize_ticker

    try:
        svc.register_normalizer("stock", lambda eid: eid.split(":")[-1], entity_type="company")

        out = run(svc.resolve(
            EntityRef(domain="stock", entity_type="company", entity_id="NYSE:T")
        ))
        assert out.entity_id == "T"

        # other entity types in same domain keep default behavior
        out2 = run(svc.resolve(
            EntityRef(domain="stock", entity_type="event", entity_id="e-99")
        ))
        assert out2.entity_id == "e-99"
    finally:
        svc.register_normalizer("stock", normalize_ticker, entity_type="company")


def test_chained_normalizers_last_registered_runs_first():
    svc = EntityResolutionService()
    svc.register_normalizer("x", lambda eid: eid.upper())
    svc.register_normalizer("x", lambda eid: f"[{eid}]")
    ref = run(svc.resolve(EntityRef(domain="x", entity_type="t", entity_id="abc")))
    assert ref.entity_id == "[ABC]"


# ── Linking ─────────────────────────────────────────────────────

def test_link_relationship_inference():
    svc = EntityResolutionService()
    src = EntityRef(domain="stock", entity_type="company", entity_id="AAPL")
    links = run(svc.link(src, [
        EntityRef(domain="stock", entity_type="company", entity_id="MSFT"),
        EntityRef(domain="stock", entity_type="news", entity_id="n1"),
        EntityRef(domain="hr", entity_type="candidate", entity_id="c1"),
    ]))
    assert links["same_type"] == [EntityRef("stock", "company", "MSFT")]
    assert links["related"] == [EntityRef("stock", "news", "n1")]
    assert links["cross_domain"] == [EntityRef("hr", "candidate", "c1")]


# ── Company name normalization reference cases ──────────────────

def test_normalize_company_name_reference():
    assert normalize_company_name("Apple Inc.") == "apple"
    assert normalize_company_name("Microsoft Corp") == "microsoft"


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