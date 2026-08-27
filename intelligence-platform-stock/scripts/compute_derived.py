"""Compute & store derived data (technical indicators + financial metrics) for all companies.

Usage:
    python -m scripts.compute_derived
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.company import Company
from app.services.fundamental_analysis import FundamentalAnalysisEngine
from app.services.technical_analysis import TechnicalAnalysisEngine


async def run() -> None:
    async with async_session_factory() as session:
        companies = (await session.execute(select(Company))).scalars().all()
        for c in companies:
            try:
                t = await TechnicalAnalysisEngine(session).calculate_indicators(c.id)
                print(f"{c.ticker}: technical={'OK' if t else 'insufficient'}")
            except Exception as e:
                print(f"{c.ticker}: technical ERROR {e}")
        for c in companies:
            try:
                m = await FundamentalAnalysisEngine(session).calculate_and_store(c.id)
                print(f"{c.ticker}: metrics={'OK' if m else 'insufficient'}")
            except Exception as e:
                print(f"{c.ticker}: metrics ERROR {e}")


if __name__ == "__main__":
    asyncio.run(run())