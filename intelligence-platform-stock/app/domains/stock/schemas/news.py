"""
Pydantic schemas for news and event API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NewsResponse(BaseModel):
    id: int
    source: str
    title: str
    url: Optional[str] = None
    published_at: datetime
    summary: Optional[str] = None
    sentiment: Optional[float] = None
    relevance_score: Optional[float] = None
    impact_score: Optional[float] = None
    confidence_score: Optional[float] = None
    credibility_score: Optional[float] = None
    materiality_score: Optional[float] = None
    effective_weight: Optional[float] = None

    model_config = {"from_attributes": True}


class NewsListResponse(BaseModel):
    news: list[NewsResponse]
    total: int


class MarketEventResponse(BaseModel):
    id: int
    company_id: Optional[int] = None
    event_type: str
    event_date: datetime
    impact: Optional[str] = None
    impact_score: Optional[float] = None
    confidence: Optional[float] = None
    materiality_score: Optional[float] = None
    effective_weight: Optional[float] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    events: list[MarketEventResponse]
    total: int