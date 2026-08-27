"""Temporary verification script for market overview data."""

import asyncio
import json

from app.domains.stock.api.market import get_market_overview
from app.core.database import async_session_factory
from app.domains.stock.ingestion.macro import MacroIngestion


async def main() -> None:
    # First, run macro ingestion to ensure economic_indicators has data.
    async with async_session_factory() as session:
        macro = MacroIngestion(session)
        results = await macro.ingest_all_indicators()
        print("Macro ingestion results:", results)

    # Now fetch the market overview.
    async with async_session_factory() as session:
        result = await get_market_overview(session)
        print(json.dumps({
            "market": result.market,
            "indices": result.indices,
            "top_movers_count": len(result.top_movers),
            "major_events_count": len(result.major_events),
            "macro_environment": {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in result.macro_environment.items()},
        }, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())