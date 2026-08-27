"""Enrich news scores + detect market events for all companies."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.database import async_session_factory
from app.models.company import Company
from app.models.news import CompanyNews, News
from app.services.event_detection import EventIntelligenceEngine
from app.services.materiality import compute_effective_weight, compute_materiality, time_decay
from app.services.sentiment import SentimentAnalyzer


async def run() -> None:
    a = SentimentAnalyzer()
    async with async_session_factory() as session:
        news = (await session.execute(select(News))).scalars().all()
        companies = {c.id: c for c in (await session.execute(select(Company))).scalars().all()}
        for n in news:
            s = a.analyze_news(n.summary or n.title or "", n.source or "", "")
            n.sentiment = s["sentiment"]
            n.relevance_score = s["relevance_score"]
            n.credibility_score = s["credibility_score"]
            n.magnitude_score = s["magnitude"]
            n.impact_score = s["impact_score"]
            n.confidence_score = s["confidence_score"]
            m = compute_materiality("NEWS", abs(s["sentiment"]), s["confidence_score"])
            n.materiality_score = m
            n.effective_weight = compute_effective_weight(
                s["relevance_score"], s["credibility_score"], m,
                time_decay(n.published_at, "NEWS", datetime.now(timezone.utc)),
            )
        # Enrich the CompanyNews join rows (per-company relevance + confidence)
        links = (await session.execute(select(CompanyNews))).scalars().all()
        for cn in links:
            company = companies.get(cn.company_id)
            n = next((x for x in news if x.id == cn.news_id), None)
            if not company or not n:
                continue
            rel = a.assess_relevance(n.summary or n.title or "", company.ticker, company.name)
            conf = a.analyze(n.summary or n.title or "")["confidence"]
            cn.relevance_score = rel
            cn.confidence = conf
        await session.commit()
        print(f"Enriched {len(news)} news items + {len(links)} company links")

        engine = EventIntelligenceEngine(session)
        for c in (await session.execute(select(Company))).scalars().all():
            events = await engine.detect_events_from_news(c.id, hours=24 * 30)
            print(f"{c.ticker}: {len(events)} events")


if __name__ == "__main__":
    asyncio.run(run())