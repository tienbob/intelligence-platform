"""Validate the AAPL analysis detail payload against the live contract.

Extracted from the GET /analysis/a5f09ef0-... response (2026-09-29).
Checks schema conformance (Pydantic) + cross-field invariants using the
project's real config/threshold logic — no DB needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.domains.stock.schemas.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    ConfidenceBreakdown,
    InvestmentRecommendation,
)
from app.domains.stock.config import get_stock_config
from app.domains.stock.scoring.investment_scoring import get_scoring_weights

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


# ── Extracted payload (top-level + nested fields the invariants touch) ──
payload = {
    "analysis_id": "a5f09ef0-3bc6-48e3-a5d9-748d44e84660",
    "status": "completed",
    "ticker": "AAPL",
    "failure_reason": None,
    "request_options": {
        "ticker": "AAPL", "include_news": True, "time_horizon": "medium_term",
        "include_macro": True, "include_technical": True, "include_fundamentals": True,
    },
    "investment_score": 50.486488449011844,
    "risk_score": 40.14100662494437,
    "confidence": 1.0,
    "confidence_breakdown": {"data": 1.0, "quantitative": 1.0, "llm": 0.85, "overall": 0.95},
    "source_backed_claims": [
        {"claim": "Apple carries a premium valuation with a Forward P/E of 36.89 versus the industry average of 20.",
         "source": {"type": "news", "source": "massive", "metric": "forward_pe", "value": 36.89, "period": "2026-09-11"}},
        {"claim": "Apple's new CEO John Ternus took over on September 1, 2026, ahead of a major product launch event on September 9.",
         "source": {"type": "news", "source": "massive", "metric": "ceo_transition", "value": None, "period": "2026-09-01"}},
        {"claim": "Apple's revenue growth was 16.36% and free cash flow growth was 30.77% in the latest fundamental snapshot.",
         "source": {"type": "financial_statement", "source": "FMP", "metric": "revenue_growth", "value": 0.1636, "period": "2026-06-27"}},
    ],
    "analysis": {
        "confidence": 0.85,
        "summary": "Apple Inc. (AAPL) is navigating a significant leadership transition...",
        "investment_thesis": "Apple remains a premier long-term compounder...",
        "market_interpretation": "The stock is trading at $338.40...",
        "bull_case": ["Unrivaled brand loyalty (96%)...", "Expanding high-margin services business...", "Exceptional financial health...", "Successful product diversification..."],
        "bear_case": ["Extremely high premium valuation...", "Perceived lag in the AI race...", "Very low dividend yield of 0.33%...", "Short-term margin pressures..."],
        "catalysts": ["Demonstration of a clear, independent AI strategy...", "Initial sales data and consumer reception...", "Upcoming quarterly earnings release..."],
        "risks": ["Execution risk under new leadership...", "Supply chain disruptions...", "Multiple contraction risk..."],
        "invalidating_conditions": ["Failure of new CEO John Ternus to establish a viable AI roadmap...", "Significant margin compression below 50%...", "A sharp deceleration in revenue or services growth..."],
        "causes": [
            {"cause": "Leadership transition to John Ternus...", "impact": "high", "confidence": 0.85, "evidence_ids": ["news_148", "news_136"]},
            {"cause": "Premium valuation metrics...", "impact": "medium", "confidence": 0.9, "evidence_ids": ["news_208", "news_136"]},
            {"cause": "Strong fundamental performance...", "impact": "high", "confidence": 0.95, "evidence_ids": ["news_273"]},
        ],
        "_score_snapshot": {
            "confidence": 1.0, "risk_score": 40.14100662494437,
            "growth_score": 74.10615451279735, "overall_score": 50.486488449011844,
            "recommendation": "NEUTRAL", "valuation_score": 2.916731403712403,
            "fundamental_score": 76.24065112599015, "data_quality_score": 1.0,
        },
        "source_backed_claims": [
            {"claim": "Apple carries a premium valuation...", "source": {"type": "news", "value": 36.89, "metric": "forward_pe", "period": "2026-09-11", "source": "massive"}},
            {"claim": "Apple's new CEO John Ternus took over...", "source": {"type": "news", "value": "John Ternus", "metric": "ceo_transition", "period": "2026-09-01", "source": "massive"}},
            {"claim": "Apple's revenue growth was 16.36%...", "source": {"type": "financial_statement", "value": 0.1636, "metric": "revenue_growth", "period": "2026-06-27", "source": "FMP"}},
        ],
        "evidence": {"source_count": 7, "evidence_sources": []},
    },
    "recommendation": {
        "score": 50.486488449011844, "confidence": 1.0, "recommendation": "NEUTRAL",
        "reasons": ["Fundamental score: 76", "Valuation score: 3", "Growth score: 74"],
        "risks": ["Risk score: 40"], "invalidating_conditions": [], "recommended_weight": None,
    },
    "created_at": "2026-09-29T07:25:11.085322+00:00",
    "can_manage": True,
}

# ── 1. Schema conformance (Pydantic) ────────────────────────────────
try:
    AnalysisResponse.model_validate(payload)
    check("AnalysisResponse schema conformance", True, "all fields validate against the live model")
except Exception as exc:
    check("AnalysisResponse schema conformance", False, str(exc))

try:
    AnalysisRequest.model_validate(payload["request_options"])
    check("request_options round-trips AnalysisRequest", True)
except Exception as exc:
    check("request_options round-trips AnalysisRequest", False, str(exc))

ConfidenceBreakdown.model_validate(payload["confidence_breakdown"])
InvestmentRecommendation.model_validate(payload["recommendation"])
check("Nested models (ConfidenceBreakdown, InvestmentRecommendation) validate", True)

# ── 2. Recommendation threshold mapping ─────────────────────────────
cfg = get_stock_config()
overall = payload["investment_score"]
expected = None
for rule in sorted(cfg.RECOMMENDATION_THRESHOLDS, key=lambda r: -r["threshold"]):
    if overall >= rule["threshold"]:
        expected = rule["category"]
        break
check(
    f"Recommendation mapping: {overall:.2f} -> {payload['recommendation']['recommendation']}",
    expected == payload["recommendation"]["recommendation"],
    f"config thresholds say {expected}",
)

# ── 3. Confidence-breakdown arithmetic ──────────────────────────────
cb = payload["confidence_breakdown"]
expected_overall = round((cb["data"] + cb["quantitative"] + cb["llm"]) / 3, 4)
check(
    f"Confidence overall = mean(data, quant, llm) = {expected_overall}",
    abs(cb["overall"] - expected_overall) < 1e-9,
)
check(
    "LLM confidence in analysis dict matches breakdown.llm",
    payload["analysis"]["confidence"] == cb["llm"],
)

# ── 4. Score arithmetic (weights from the live config) ─────────────
w = get_scoring_weights()
snap = payload["analysis"]["_score_snapshot"]
F, V, G, R = snap["fundamental_score"], snap["valuation_score"], snap["growth_score"], snap["risk_score"]
remaining = overall - (w["fundamental"] * F + w["valuation"] * V + w["growth"] * G) + w["risk"] * R
tsc_sum = remaining / (w["technical"] + w["sentiment"] + w["catalyst"])
check(
    "Score arithmetic consistent with configured weights",
    0 <= tsc_sum <= 300,
    f"implies technical+sentiment+catalyst sum = {tsc_sum:.2f} (feasible: each in [0,100])",
)

# ── 5. Snapshot columns match top-level fields ─────────────────────
check("_score_snapshot.overall_score == investment_score", snap["overall_score"] == payload["investment_score"])
check("_score_snapshot.risk_score == risk_score", snap["risk_score"] == payload["risk_score"])
check("recommendation.score == investment_score", payload["recommendation"]["score"] == payload["investment_score"])

# ── 6. Evidence citations ───────────────────────────────────────────
available = {"events_258", "events_58", "news_109", "news_136", "news_148", "news_208", "news_273"}
cited = {eid for c in payload["analysis"]["causes"] for eid in c["evidence_ids"]}
check("All cited evidence_ids are valid", cited <= available, f"cited {sorted(cited)}")

# ── 7. Claim consistency (persisted rows vs LLM-embedded) ──────────
top_claims = payload["source_backed_claims"]
llm_claims = payload["analysis"]["source_backed_claims"]
check("Claim counts match (persisted rows vs LLM claims)", len(top_claims) == len(llm_claims))
divergent = [i for i, (a, b) in enumerate(zip(top_claims, llm_claims)) if a["source"]["value"] != b["source"]["value"]]
for i in divergent:
    print(f"NOTE: claim value divergence at index {i}: persisted={top_claims[i]['source']['value']!r} vs llm={llm_claims[i]['source']['value']!r}")

# ── 8. Business-rule sanity (mirrors _validate_business_rules) ──────
check("overall in [0, 100]", 0 <= overall <= 100)
check("risk not disproportionately high vs overall", R <= overall + 50, f"risk={R:.1f} overall={overall:.1f}")

# ── Report ──────────────────────────────────────────────────────────
print()
fails = 0
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    fails += 0 if ok else 1
print()
print(f"{len(results) - fails}/{len(results)} checks passed")
sys.exit(1 if fails else 0)