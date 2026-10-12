from datetime import datetime, timezone
from types import SimpleNamespace
from app.domains.stock.api.investments import _opportunity_from_rows

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
COMPANY = SimpleNamespace(ticker='AAPL', sector='Technology')


def screening():
    return SimpleNamespace(overall_score=40, recommendation='CAUTION', timestamp=NOW,
                           scoring_model='screening', scoring_version='1', fundamental_score=35,
                           risk_score=60)


def analysis(value=85):
    return SimpleNamespace(investment_score=value, risk_score=20, risk_snapshot={'volatility': 0.2},
                           analysis_id='own-analysis', status='completed', created_at=NOW,
                           llm_analysis={'_score_snapshot': {'recommendation': 'OPPORTUNITY',
                               'fundamental_score': 90, 'risk_score': 20, 'scoring_model': 'deep-model', 'scoring_version': '2'}})


def test_completed_deep_dive_overrides_score_and_breakdown_as_one_source():
    row = _opportunity_from_rows(screening(), COMPANY, analysis(), SimpleNamespace(risk_score=70, volatility=0.9))
    assert row.score == 85
    assert row.screening_score == 40
    assert row.score_source == 'analysis'
    assert row.recommendation == 'OPPORTUNITY'
    assert row.risk_score == 20
    assert row.volatility == 0.2
    assert row.components[0].value == 90
    assert row.scoring_model == 'deep-model'
    # A historical deep dive without a captured component must not borrow screening values.
    assert row.components[1].value is None


def test_no_analysis_uses_screening_and_preserves_missing_risk():
    row = _opportunity_from_rows(screening(), COMPANY, None, None)
    assert row.score == 40
    assert row.score_source == 'screening'
    assert row.recommendation == 'CAUTION'
    assert row.risk_score is None
    assert row.analysis_id is None


def test_zero_deep_dive_score_is_selected_without_screening_row():
    row = _opportunity_from_rows(None, COMPANY, analysis(0), None)
    assert row.score == 0
    assert row.score_source == 'analysis'
    assert row.screening_score is None
