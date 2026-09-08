"""Valuation scoring: FCF-yield clamp + band-saturation diagnostic.

Pins the existing band arithmetic (P/E 5-40, P/S 0.5-10, P/B 0.5-5,
inverted; FCF yield x10) while fixing one correctness defect: the FCF
yield component had no lower clamp, so a negative FCF yield produced a
negative component and could push the valuation average below the
scorer's own 0-100 component invariant (business Rule 2 in
_validate_business_rules).

The saturation diagnostic is observability only: two or more components
pegged at a band boundary (P/E 40 and P/E 400 are both exactly 0) mean
the fixed absolute bands saturate for this company. The score itself is
intentionally unchanged — band recalibration is a product decision.
"""

import pytest

from app.domains.stock.scoring.investment_scoring import (
    InvestmentScoringEngine,
)


def _components(pe, ps, pb, fcf_yield):
    return InvestmentScoringEngine._valuation_component_scores(
        pe, ps, pb, fcf_yield
    )


def test_negative_fcf_yield_cannot_produce_negative_component():
    components, average = _components(None, None, None, -0.05)

    assert components == {"fcf_yield": 0.0}
    assert average == 0.0


def test_negative_fcf_yield_cannot_drag_average_below_zero():
    # Saturated P/B (0) + clamped negative FCF yield (0): the average must
    # stay inside the 0-100 component contract.
    components, average = _components(None, None, 15.2, -0.04)

    assert components["pb"] == 0.0
    assert components["fcf_yield"] == 0.0
    assert average == 0.0
    assert all(0.0 <= value <= 100.0 for value in components.values())


def test_large_positive_fcf_yield_still_caps_at_100():
    components, _ = _components(None, None, None, 15.0)

    assert components["fcf_yield"] == 100.0


def test_existing_valuation_band_math_unchanged():
    # AAPL row verified live against the pre-patch scorer: P/E 36.5 -> 10,
    # P/S 10.1 -> 0 (clamped), P/B 43.7 -> 0 (clamped), FCF 2.9% -> 0.29.
    components, average = _components(36.5, 10.1, 43.7, 0.029)

    assert components["pe"] == pytest.approx(10.0)
    assert components["ps"] == 0.0
    assert components["pb"] == 0.0
    assert components["fcf_yield"] == pytest.approx(0.29)
    assert average == pytest.approx(2.5725)

    # Interior band points and the neutral-missing behavior are untouched.
    assert InvestmentScoringEngine._normalize(
        20, 5, 40, invert=True
    ) == pytest.approx(57.142857, rel=1e-6)
    assert InvestmentScoringEngine._normalize(5, 5, 40, invert=True) == 100.0
    assert InvestmentScoringEngine._normalize(None, 5, 40) == 50.0
    assert InvestmentScoringEngine._score_valuation_snapshot({}) == 50.0
    assert InvestmentScoringEngine._score_valuation_snapshot(None) == 50.0


def test_healthy_valuation_mix_scores_midband_without_diagnostic():
    components, average = _components(12.0, 2.0, 3.0, 0.05)

    assert 0.0 < average < 100.0
    assert (
        InvestmentScoringEngine._valuation_saturation_issue(components)
        is None
    )


def test_saturated_valuation_components_produce_diagnostic():
    # TSLA-shaped row: all three ratios far outside their bands.
    components, average = _components(187.4, 10.5, 15.2, None)

    assert components == {"pe": 0.0, "ps": 0.0, "pb": 0.0}
    assert average == 0.0

    issue = InvestmentScoringEngine._valuation_saturation_issue(components)

    assert issue is not None
    assert issue.startswith("valuation_components_saturated")
    assert "pe: 0" in issue
    assert "ps: 0" in issue
    assert "pb: 0" in issue
    assert "3 of 3" in issue
    assert "score unchanged" in issue


def test_single_saturated_component_is_below_diagnostic_threshold():
    # Only P/B present and saturated: one boundary hit is not
    # boundary-dominated.
    components, average = _components(None, None, 43.7, None)

    assert components == {"pb": 0.0}
    assert average == 0.0
    assert (
        InvestmentScoringEngine._valuation_saturation_issue(components)
        is None
    )


def test_saturation_diagnostic_requires_two_boundary_hits():
    has_issue = InvestmentScoringEngine._valuation_saturation_issue

    assert has_issue({}) is None
    assert has_issue(None) is None
    assert has_issue({"pe": 10.0, "ps": 44.4}) is None

    # 100-boundary hits count too (cheap-side saturation).
    issue = has_issue({"pe": 100.0, "ps": 100.0})

    assert issue is not None
    assert "pe: 100" in issue
    assert "ps: 100" in issue


def test_saturation_diagnostic_never_mutates_components():
    components, _ = _components(187.4, 10.5, 15.2, 0.29)

    snapshot = dict(components)

    InvestmentScoringEngine._valuation_saturation_issue(components)

    assert components == snapshot