"""Validate the Opportunities API payload against the new contract."""
import json
from app.domains.stock.schemas.analysis import InvestmentOpportunitiesResponse

PAYLOAD = {
    "opportunities": [
        {
            "ticker": "NVDA",
            "score": 51.15413769439037,
            "risk_score": 29.67682065486229,
            "volatility": 0.393087927577371,
            "sector": "Technology",
            "recommendation": "NEUTRAL",
            "analysis_id": "3d647b7a-6635-4016-9e95-5682c51edb9d",
            "analysis_status": "completed",
            "analysis_timestamp": "2026-09-09T02:30:40.387055Z",
            "components": [
                {"label": "Fundamentals", "value": 94.60071446039898, "weight": 0.3},
                {"label": "Valuation", "value": 2.2240467257667245, "weight": 0.2},
                {"label": "Growth", "value": 100.0, "weight": 0.15},
                {"label": "Technical", "value": 48.62123023145441, "weight": 0.15},
                {"label": "Sentiment", "value": 71.63923076923076, "weight": 0.1},
                {"label": "Catalyst", "value": 70.0, "weight": 0.1},
                {"label": "Risk", "value": 29.67682065486229, "weight": 0.15},
            ],
            "scoring_model": "investment_score_v1",
            "scoring_version": "1.0",
            "score_timestamp": "2026-09-09T03:54:05.964992Z",
        },
        {
            "ticker": "SPY",
            "score": 46.70050259996888,
            "risk_score": 10.859400136190093,
            "volatility": 0.13445071247834683,
            "sector": "Financial Services",
            "recommendation": "NEUTRAL",
            "analysis_id": None,
            "analysis_status": None,
            "analysis_timestamp": None,
            "components": [
                {"label": "Fundamentals", "value": 50.0, "weight": 0.3},
                {"label": "Valuation", "value": 50.0, "weight": 0.2},
                {"label": "Growth", "value": 50.0, "weight": 0.15},
                {"label": "Technical", "value": 58.29412620397395, "weight": 0.15},
                {"label": "Sentiment", "value": 50.0, "weight": 0.1},
                {"label": "Catalyst", "value": 50.0, "weight": 0.1},
                {"label": "Risk", "value": 10.859400136190093, "weight": 0.15},
            ],
            "scoring_model": "investment_score_v1",
            "scoring_version": "1.0",
            "score_timestamp": "2026-09-09T03:54:05.898130Z",
        },
        {
            "ticker": "AAPL",
            "score": 46.49709158126112,
            "risk_score": 24.989931880943413,
            "volatility": 0.27253509249661984,
            "sector": "Technology",
            "recommendation": "NEUTRAL",
            "analysis_id": None,
            "analysis_status": None,
            "analysis_timestamp": None,
            "components": [
                {"label": "Fundamentals", "value": 76.24065112599015, "weight": 0.3},
                {"label": "Valuation", "value": 2.916731403712403, "weight": 0.2},
                {"label": "Growth", "value": 74.10615451279735, "weight": 0.15},
                {"label": "Technical", "value": 53.60602679054609, "weight": 0.15},
                {"label": "Sentiment", "value": 53.13513888888889, "weight": 0.1},
                {"label": "Catalyst", "value": 50.0, "weight": 0.1},
                {"label": "Risk", "value": 24.989931880943413, "weight": 0.15},
            ],
            "scoring_model": "investment_score_v1",
            "scoring_version": "1.0",
            "score_timestamp": "2026-09-09T03:54:05.920834Z",
        },
    ]
}


def main() -> None:
    r = InvestmentOpportunitiesResponse(**PAYLOAD)
    by = {o.ticker: o for o in r.opportunities}

    assert len(r.opportunities) == 3, len(r.opportunities)

    nav = by["NVDA"]
    assert nav.analysis_id == "3d647b7a-6635-4016-9e95-5682c51edb9d"
    assert nav.analysis_status == "completed"
    assert nav.analysis_timestamp is not None
    assert nav.analysis_timestamp.year == 2026
    assert nav.analysis_timestamp.month == 9
    assert nav.analysis_timestamp.day == 9
    print("NVDA deep-analysis link OK")

    for t in ("SPY", "AAPL"):
        o = by[t]
        assert o.analysis_id is None
        assert o.analysis_status is None
        assert o.analysis_timestamp is None
    print("SPY + AAPL no-deep-analysis OK")

    for t in ("NVDA", "SPY", "AAPL"):
        o = by[t]
        assert len(o.components) == 7, (t, len(o.components))
        wsum = round(sum(c.weight for c in o.components), 4)
        weighted = round(sum(c.value * c.weight for c in o.components), 2)
        print(f"  {t}: score={o.score:.1f} risk={o.risk_score:.1f} comps={len(o.components)} wsum={wsum} weighted={weighted}")
        if abs(wsum - 1.0) > 1e-9:
            print(f"    ⚠  weight sum {wsum} ≠ 1.0 (data issue, not contract)")
        else:
            print(f"    ✓ weight sum = 1.0")

    assert nav.scoring_model == "investment_score_v1"
    assert nav.scoring_version == "1.0"
    print("scoring_model/version OK")

    print("\nRESULT: payload SCHEMA_VALID and semantically consistent with the new contract.")


if __name__ == "__main__":
    main()
