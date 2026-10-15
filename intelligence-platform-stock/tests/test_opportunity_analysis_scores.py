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


def test_coverage_follows_selected_score_without_borrowing_screening_data():
    score = screening()
    score.validation_issues = {'data_quality': {'financial_inputs': {'reporting_period': '2026-06-30'}}}
    deep_dive = analysis()
    assert _opportunity_from_rows(score, COMPANY, deep_dive, None).data_quality is None
    deep_dive.llm_analysis['_score_snapshot']['validation_issues'] = {
        'data_quality': {'financial_inputs': {'reporting_period': '2025-12-31'}}}
    assert _opportunity_from_rows(score, COMPANY, deep_dive, None).data_quality['financial_inputs']['reporting_period'] == '2025-12-31'
    assert _opportunity_from_rows(score, COMPANY, None, None).data_quality['financial_inputs']['reporting_period'] == '2026-06-30'


def test_ticker_search_normalizes_literal_text_and_preserves_pagination(monkeypatch):
    import asyncio
    from app.domains.stock.api import investments
    from sqlalchemy.dialects import postgresql
    from unittest.mock import AsyncMock
    monkeypatch.setattr(investments, 'get_actor', lambda request: None)
    monkeypatch.setattr(investments, 'visible_to_actor', lambda column, actor: column == 1)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    asyncio.run(investments.get_investment_opportunities(None, min_score=0, sector=None,
        ticker=' aa%_ ', limit=5, offset=10, db=db))
    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert 'AA/%/_' in compiled.params.values()
    assert 'LIKE' in str(compiled)
    assert statement._limit_clause.value == 5
    assert statement._offset_clause.value == 10


def test_opportunities_only_select_deep_dives_completed_today_utc(monkeypatch):
    import asyncio
    from datetime import timedelta
    from unittest.mock import AsyncMock
    from sqlalchemy.dialects import postgresql
    from app.domains.stock.api import investments
    class Clock:
        @staticmethod
        def now(tz): return NOW.replace(hour=12)
    monkeypatch.setattr(investments, 'datetime', Clock)
    monkeypatch.setattr(investments, 'get_actor', lambda request: None)
    monkeypatch.setattr(investments, 'visible_to_actor', lambda column, actor: column == 1)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    asyncio.run(investments.get_investment_opportunities(None, min_score=0, sector=None,
        ticker=None, limit=5, offset=0, db=db))
    compiled = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert 'analyses.completed_at >=' in sql
    assert 'analyses.completed_at <' in sql
    assert NOW in compiled.params.values()
    assert NOW + timedelta(days=1) in compiled.params.values()
    assert 'ORDER BY analyses.completed_at DESC' in sql


def test_daily_selection_executes_against_rows_at_midnight_boundaries():
    from datetime import timedelta
    from sqlalchemy import create_engine, select, text
    from app.domains.stock.api.investments import completed_today
    from app.domains.stock.models.analysis import Analysis
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE analyses (id INTEGER, company_id INTEGER, status TEXT, completed_at DATETIME, updated_at DATETIME)'))
        times = [NOW - timedelta(microseconds=1), NOW, NOW + timedelta(hours=23), NOW + timedelta(days=1)]
        for i, timestamp in enumerate(times):
            connection.execute(text('INSERT INTO analyses VALUES (:id, 7, :status, :completed, :updated)'),
                dict(id=i, status='completed', completed=timestamp.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S.%f'),
                     updated=NOW.replace(hour=12).strftime('%Y-%m-%d %H:%M:%S.%f')))
        query = select(Analysis.id).where(Analysis.company_id == 7, Analysis.status == 'completed', completed_today(NOW)).order_by(Analysis.completed_at.desc()).limit(1)
        assert connection.execute(query).scalar_one() == 2
        connection.execute(text('DELETE FROM analyses WHERE id IN (1, 2)'))
        # Yesterday's result modified today and tomorrow's result are excluded.
        assert connection.execute(query).scalar_one_or_none() is None
        row = _opportunity_from_rows(screening(), COMPANY, None, None)
        assert row.score_source == 'screening' and row.score == 40
        assert row.analysis_id is None
    engine.dispose()
