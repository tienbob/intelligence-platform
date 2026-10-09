"""Build Stock intelligence context from typed, persisted observations.

Snapshot calculations belong to StockSnapshotReader and the domain scoring
engines. This adapter selects and assembles those results without database
access, provider calls, or inventing values for missing data.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from app.shared.entities import EntityRef, Evidence, IntelligenceContext, Observation


class StockContextBuilder:
    sections = ('market', 'technical', 'fundamental', 'news', 'event', 'macro', 'risk', 'anomaly')

    async def build(self, entity_ref: EntityRef, evidence: list[Evidence],
                    observations: list[Observation], rag_context: dict[str, Any],
                    **kwargs: Any) -> IntelligenceContext:
        if any(o.entity_ref != entity_ref for o in observations):
            raise ValueError('Stock context contains observations for another entity')
        company = self._latest(observations, 'company') or {'ticker': entity_ref.entity_id}
        snapshots = {'company': company}
        for section in self.sections:
            snapshots[f'{section}_snapshot'] = getattr(self, f'_build_{section}_snapshot')(observations)
        missing = [f'{section}_snapshot' for section in ('market', 'technical', 'fundamental', 'risk')
                   if not snapshots[f'{section}_snapshot']]
        fundamentals = snapshots['fundamental_snapshot']
        if not fundamentals.get('metrics') and not fundamentals.get('latest_statement') and 'fundamental_snapshot' not in missing:
            missing.append('fundamental_snapshot')
        return IntelligenceContext(
            entity={**company, 'domain': entity_ref.domain, 'entity_type': entity_ref.entity_type},
            evidence=evidence, observations=observations, rag_context=rag_context,
            domain_snapshots=snapshots,
            metadata={'ticker': entity_ref.entity_id, 'context_version': '3.0', 'missing_snapshots': missing},
        )

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                return StockContextBuilder._timestamp(datetime.fromisoformat(value.replace('Z', '+00:00')))
            except ValueError:
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    @classmethod
    def _latest(cls, observations: list[Observation], kind: str) -> dict[str, Any] | None:
        candidates = [o for o in observations if o.kind == kind]
        if not candidates:
            return None
        return dict(max(candidates, key=lambda o: cls._timestamp(o.observed_at)).data)

    @classmethod
    def _build_market_snapshot(cls, observations: list[Observation]) -> dict[str, Any]:
        stored = cls._latest(observations, 'market_snapshot')
        if stored is not None:
            return stored
        bars = [o for o in observations if o.kind in ('price', 'prices', 'ohlcv') and o.data.get('close') is not None]
        bars.sort(key=lambda o: cls._timestamp(o.data.get('timestamp') or o.observed_at), reverse=True)
        bars = bars[:30]
        if not bars:
            quote = cls._latest(observations, 'quote')
            return {'latest_price': quote.get('price'), 'latest_volume': quote.get('volume')} if quote else {}
        latest = bars[0].data
        previous = bars[1].data.get('close') if len(bars) > 1 else None
        highs = [o.data['high'] for o in bars if o.data.get('high') is not None]
        lows = [o.data['low'] for o in bars if o.data.get('low') is not None]
        volumes = [o.data['volume'] for o in bars if o.data.get('volume') is not None]
        return {'latest_price': latest['close'], 'latest_volume': latest.get('volume'),
                'latest_date': cls._timestamp(latest.get('timestamp') or bars[0].observed_at).isoformat(),
                'price_change_1d': (latest['close'] - previous) / previous if previous else None,
                'price_high_30d': max(highs) if highs else None,
                'price_low_30d': min(lows) if lows else None,
                'avg_volume_30d': sum(volumes) / len(volumes) if volumes else None}

    @classmethod
    def _build_technical_snapshot(cls, observations):
        stored = cls._latest(observations, 'technical_snapshot')
        return stored if stored is not None else cls._latest(observations, 'technical_indicator') or {}

    @classmethod
    def _build_fundamental_snapshot(cls, observations):
        stored = cls._latest(observations, 'fundamental_snapshot')
        if stored is not None:
            return stored
        metrics = cls._latest(observations, 'financial_metric') or {}
        statements = [o for o in observations if o.kind == 'financial_statement']
        statement = max(statements, key=lambda o: cls._timestamp(o.data.get('period')), default=None)
        return {'metrics': metrics, 'latest_statement': dict(statement.data) if statement else {}} if metrics or statement else {}

    @classmethod
    def _build_news_snapshot(cls, observations):
        stored = cls._latest(observations, 'news_snapshot')
        if stored is not None:
            return stored
        news = sorted([o for o in observations if o.kind == 'news'],
                      key=lambda o: cls._timestamp(o.data.get('published_at') or o.observed_at), reverse=True)
        return {'recent_news': [{**o.data, 'source': o.data.get('source') or o.source} for o in news[:10]], 'news_count': len(news)}

    @classmethod
    def _build_event_snapshot(cls, observations):
        stored = cls._latest(observations, 'event_snapshot')
        if stored is not None:
            return stored
        events = sorted([o for o in observations if o.kind == 'event'],
                        key=lambda o: cls._timestamp(o.data.get('date') or o.observed_at), reverse=True)
        return {'recent_events': [dict(o.data) for o in events[:10]], 'event_count': len(events)}

    @classmethod
    def _build_macro_snapshot(cls, observations):
        stored = cls._latest(observations, 'macro_snapshot')
        if stored is not None:
            return stored
        indicators = {}
        for o in sorted(observations, key=lambda o: cls._timestamp(o.observed_at)):
            if o.kind == 'macro' and o.data.get('value') is not None:
                metric = o.data.get('metric') or o.data.get('series')
                if metric:
                    indicators[str(metric)] = o.data['value']
        return {'indicators': indicators} if indicators else {}

    @classmethod
    def _build_risk_snapshot(cls, observations):
        stored = cls._latest(observations, 'risk_snapshot')
        return stored if stored is not None else cls._latest(observations, 'risk_metric') or {}

    @classmethod
    def _build_anomaly_snapshot(cls, observations):
        stored = cls._latest(observations, 'anomaly_snapshot')
        return stored if stored is not None else cls._latest(observations, 'anomaly') or {}
