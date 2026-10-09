"""Framework observation boundary over worker-persisted Stock data."""
from datetime import datetime, timezone
from typing import Any

from app.core.database import async_session_factory
from app.domains.stock.normalization.companies import EntityResolver
from app.domains.stock.snapshots import StockSnapshotReader
from app.shared.entities import EntityRef, Observation


class PersistedStockProvider:
    provider_name = 'stock_database'

    def __init__(self, session_factory=None, reader_factory=None):
        self._sessions = session_factory or async_session_factory
        self._reader = reader_factory or StockSnapshotReader

    async def fetch(self, entity_ref: EntityRef) -> list[Observation]:
        if entity_ref.domain != 'stock' or entity_ref.entity_type != 'company':
            raise ValueError('Persisted stock data requires a stock company reference')
        async with self._sessions() as session:
            company = await EntityResolver(session).resolve(ticker=entity_ref.entity_id)
            if company is None:
                raise LookupError(f'No persisted company for {entity_ref.entity_id}')
            reader = self._reader(session)
            snapshots: dict[str, Any] = {
                'company': {field: getattr(company, field, None) for field in ('ticker', 'name', 'sector', 'industry', 'market_cap')},
            }
            for section in ('market', 'technical', 'fundamental', 'news', 'event', 'risk', 'anomaly'):
                snapshots[f'{section}_snapshot'] = await getattr(reader, f'build_{section}_snapshot')(company.id)
            snapshots['macro_snapshot'] = await reader.macro_engine.get_macro_snapshot()
            captured_at = datetime.now(timezone.utc)
            return [Observation(entity_ref=entity_ref, observed_at=captured_at,
                                source=self.provider_name, kind=kind, data=data)
                    for kind, data in snapshots.items()]
