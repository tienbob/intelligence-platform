"""
Framework tests: generic evidence core.

Verifies the framework's provenance/attribution engine works generically
without any domain connection. A Stock domain and an HR domain use the
same mechanics.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.evidence import (  # noqa: E402
    EvidenceAttributor,
    EvidencePackage,
    EvidenceService,
    source_id_for,
)


def rag_context(buckets: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {name: items for name, items in buckets.items()}


RAG = {
    "news": [
        {"id": 10, "similarity": 0.91, "metadata": {"published_at": "2026-01-05"}},
        {"id": 11, "similarity": 0.88, "metadata": {}},
    ],
    "filings": [
        {"id": 5, "similarity": 0.76, "metadata": {}},
    ],
}


def test_source_id_for():
    assert source_id_for("news", 42) == "news_42"
    assert source_id_for("employee", "c-7") == "employee_c-7"


def test_register_sources_builds_registry_with_ids():
    attributor = EvidenceAttributor()
    sources = attributor.register_sources(RAG)
    assert len(sources) == 3
    assert {s["entity_type"] for s in sources} == {"news", "filings"}
    assert "news_10" in attributor.source_registry


def test_validate_claim_evidence():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG)
    assert attributor.validate_claim_evidence({"evidence_ids": ["news_10"]}) is True
    assert attributor.validate_claim_evidence({"evidence_ids": []}) is False
    assert attributor.validate_claim_evidence({"evidence_ids": ["unknown_99"]}) is False


def test_enrich_claim_with_sources():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG)
    enriched = attributor.enrich_claim_with_sources(
        {"cause": "growth", "evidence_ids": ["news_10", "missing_1"]}
    )
    assert enriched["cause"] == "growth"
    assert len(enriched["evidence_sources"]) == 1
    assert enriched["evidence_sources"][0]["source_id"] == "news_10"


def test_build_evidence_package_legacy_shape():
    attributor = EvidenceAttributor()
    package = attributor.build_evidence_package(RAG)
    # legacy dict shape consumed by Stock LLM (`result["evidence"]`)
    assert "evidence_sources" in package
    assert package["source_count"] == 3
    assert set(package["source_types"]) == {"news", "filings"}


def test_get_source_metadata_returns_full_record():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG)
    rec = attributor.get_source_metadata("news_10")
    assert rec is not None and rec["entity_id"] == 10


def test_evidence_service_facade():
    svc = EvidenceService()
    svc.register_sources(RAG)
    assert svc.claim_is_supported({"evidence_ids": ["filings_5"]}) is True
    assert svc.claim_is_supported({"evidence_ids": ["x"]}) is False


def test_evidence_package_rich_object():
    svc = EvidenceService()
    package: EvidencePackage = svc.build_package(RAG)
    assert package.source_count == 3
    assert set(package.source_types) == {"news", "filings"}
    assert package.to_dict()["source_count"] == 3


def test_observation_to_evidence_domain_neutral():
    # Same machinery, two domains → generalization proof.
    from app.intelligence.observations import make_observation, observations_to_evidence
    from app.shared.entities import EntityRef

    stock = make_observation(
        EntityRef("stock", "company", "AAPL"), source="massive",
        data={"metric": "pe", "value": 30}, kind="quote",
    )
    hr = make_observation(
        EntityRef("hr", "candidate", "c-7"), source="workday",
        data={"metric": "years_experience", "value": 9}, kind="employee",
    )
    evs = observations_to_evidence([stock, hr])
    assert evs[0].source_name == "massive"
    assert evs[1].source_name == "workday"


# ── Citation-support filter ────────────────────────────────────────

RAG_WITH_CONTENT = {
    "news": [
        {
            "id": 10,
            "similarity": 0.90,
            "metadata": {},
            "content": "Apple reported revenue growth of 16.4% driven by services strength "
                       "and record free cash flow generation this quarter.",
        },
        {
            "id": 11,
            "similarity": 0.85,
            "metadata": {},
            "content": "Apple stock is projected to deliver 12% annualized returns over the "
                       "next four years according to long-term market projections.",
        },
    ],
}


def test_filter_supported_evidence_ids_keeps_backing_source():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG_WITH_CONTENT)
    claim = {
        "claim": "Apple's revenue growth was 16.4%, driven by services strength.",
        "evidence_ids": ["news_10", "news_11"],
    }
    # news_10 shares revenue/growth/services tokens; news_11 is a
    # valid-but-unrelated returns-projection article.
    assert attributor.filter_supported_evidence_ids(claim) == ["news_10"]


def test_filter_supported_evidence_ids_drops_unrelated_citation():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG_WITH_CONTENT)
    claim = {
        "claim": "Free cash flow growth reached 30.8% in the latest quarter.",
        "evidence_ids": ["news_11"],
    }
    assert attributor.filter_supported_evidence_ids(claim) == []


def test_filter_supported_evidence_ids_keeps_citation_when_content_missing():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG)  # metadata-only fixture — no content
    claim = {
        "claim": "Any claim about revenue growth numbers for the company.",
        "evidence_ids": ["news_10"],
    }
    # Too little content to judge → conservative: keep the citation.
    assert attributor.filter_supported_evidence_ids(claim) == ["news_10"]


def test_filter_supported_evidence_ids_short_claim_kept():
    attributor = EvidenceAttributor()
    attributor.register_sources(RAG_WITH_CONTENT)
    claim = {"claim": "Strong", "evidence_ids": ["news_11"]}
    # Claim has fewer than 2 distinctive tokens → keep as-is.
    assert attributor.filter_supported_evidence_ids(claim) == ["news_11"]


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