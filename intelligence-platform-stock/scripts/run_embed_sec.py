#!/usr/bin/env python3
"""Run SEC filing embedding with verbose logging."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    import logging

    logging.basicConfig(level=logging.DEBUG)

    from app.core.database import async_session_factory
    from app.domains.stock.scoring.embeddings import EmbeddingIngestionService

    async with async_session_factory() as session:
        svc = EmbeddingIngestionService(session)
        count = await svc.embed_sec_filings(limit=5)
        print(f"Embedded {count} filings")


if __name__ == "__main__":
    asyncio.run(main())
