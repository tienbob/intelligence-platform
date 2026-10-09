"""Regressions for missing financial inputs and TSLA citation/scoring failures."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.stock.scoring.investment_scoring import DataQualityEngine, InvestmentScoringEngine
from app.domains.stock.scoring.llm import LLMService
from app.intelligence.evidence.attribution import EvidenceAttributor


def financial_inputs(**overrides):
    values = dict(roe=.01, roa=.0075, net_margin=.03945, debt_equity=.1076,
                  pe_ratio=None, ps_ratio=14., pb_ratio=17., fcf_yield=-.07735,
                  revenue_growth=.255, earnings_growth=-.049, fcf_growth=-8.479)
    return SimpleNamespace(**(values | overrides))


def recent_statement():
    return SimpleNamespace(period=(datetime.now(timezone.utc)-timedelta(days=100)).date().isoformat())


def test_missing_ma_metrics_are_reported_as_fallbacks():
    quality = DataQualityEngine.financial_completeness(None, recent_statement())
    assert quality['overall'] == 0
    assert set(quality['fallback_components']) == {'fundamental', 'valuation', 'growth'}
    assert InvestmentScoringEngine._compute_confidence(
        {'overall': .7, 'sufficient': True, 'financial_inputs': quality}, True) <= .5


def test_tsla_alternative_valuation_inputs_without_pe_are_usable():
    quality = DataQualityEngine.financial_completeness(financial_inputs(), recent_statement())
    assert quality['overall'] == 1
    assert quality['missing_inputs']['valuation'] == ['pe_ratio']
    assert not quality['fallback_components']
    assert InvestmentScoringEngine._compute_confidence(
        {'overall': 1., 'sufficient': True, 'financial_inputs': quality}, True) == .95


def test_stale_reporting_period_and_nonfinite_fields_reduce_quality():
    metrics = financial_inputs(roe=float('nan'), ps_ratio=float('inf'), pb_ratio=-2)
    quality = DataQualityEngine.financial_completeness(metrics, SimpleNamespace(period='2001-06-30'))
    assert quality['overall'] == 0
    assert 'roe' in quality['missing_inputs']['fundamental']
    assert {'ps_ratio', 'pb_ratio'} <= set(quality['missing_inputs']['valuation'])


@pytest.mark.asyncio
async def test_negative_cash_flow_does_not_create_negative_valuation():
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalar_one_or_none=lambda: financial_inputs(ps_ratio=None, pb_ratio=None))))
    engine = InvestmentScoringEngine(session)
    assert await engine._score_valuation(4) == 0
    assert engine._bounded_score(-5) == 0
    assert engine._bounded_score(140) == 100


@pytest.mark.asyncio
async def test_snapshot_citation_is_available_and_unrelated_cause_is_flagged():
    unrelated = ('Tesla has been a headline fixture again, with a mix of robotaxi expansion, '
                 'regulatory scrutiny on Full Self Driving in Europe, and fresh attention on '
                 'its role in AI and energy storage. With the stock at about US$375 and a mixed '
                 'return pattern, investors wonder whether sales support the valuation.')
    bad = 'Growing speculative interest and overnight stock gains driven by record Cybercab registrations in Texas and FSD expansion efforts in Europe.'
    good = 'Tesla added 150 Cybercab registrations in Texas, lifting the total to 319 from 169.'
    output = dict(summary='Summary', market_interpretation='Interpretation', bull_case=[], bear_case=[],
                  investment_thesis='Thesis', confidence=.75,
                  causes=[dict(cause=bad, impact='medium', confidence=.8, evidence_ids=['news_695']),
                          dict(cause=good, impact='high', confidence=.8, evidence_ids=['snapshot_news_42'])])
    engine = SimpleNamespace(chat_json=AsyncMock(return_value=(output, 5)), build_meta=lambda **kw: kw)
    service = LLMService(api_key='test')
    service._get_client = AsyncMock()
    service._get_engine = lambda: engine
    attributor = EvidenceAttributor()
    rag = {'news': [{'id':695, 'content':unrelated}]}
    attributor.register_sources(rag)
    context = {'rag_context':rag, 'news_snapshot':{'recent_news':[
        {'id':42, 'title':'Cybercab registrations', 'summary':good, 'source':'finnhub'}]}}
    result = await service.analyze('test prompt', context, evidence_attributor=attributor)
    assert 'snapshot_news_42' in context['available_evidence_ids']
    assert len(result['causes']) == 1
    assert result['causes'][0]['cause'] == good
    assert result['citation_warnings'][0]['claim'] == bad
    assert result['evidence']['source_count'] == 2


def test_multiple_passages_can_jointly_support_a_cause():
    attributor = EvidenceAttributor()
    attributor.register_sources({'news':[
        {'id':606,'content':"Tesla's earnings estimate revisions declined by 4.2% for the current quarter and 5.1% for the fiscal year. Zacks Rank #4 (Sell) suggests underperformance. Revenue forecasts remain positive."},
        {'id':628,'content':"Tesla's Forward P/E ratio of 210.49 significantly exceeds the industry average of 15.63. It carries a Zacks Rank #4 (Sell), suggesting valuation concerns."}]})
    cause = dict(cause='Downward revisions in earnings estimates and concerns over an extremely high forward P/E ratio (exceeding 150x) leading to a Zacks Rank #4 (Sell).', evidence_ids=['news_606','news_628'])
    assert attributor.filter_supported_evidence_ids(cause) == ['news_606','news_628']
