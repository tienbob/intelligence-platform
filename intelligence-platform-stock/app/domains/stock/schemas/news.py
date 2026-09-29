"""
Pydantic schemas for news and event API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NewsResponse(BaseModel):
    """Full news detail — only fields rendered by NewsDetail."""

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


class NewsListItem(BaseModel):
    """Lean list row — only fields rendered by the News feed."""

    id: int
    source: str
    title: str
    published_at: datetime
    summary: Optional[str] = None
    sentiment: Optional[float] = None

    model_config = {"from_attributes": True}


class NewsListResponse(BaseModel):
    news: list[NewsListItem]


class MarketEventResponse(BaseModel):
    """Full event detail — only fields rendered by EventDetail/Event pages."""

    id: int
    ticker: Optional[str] = None
    event_type: str
    event_date: datetime
    impact: Optional[str] = None
    impact_score: Optional[float] = None
    confidence: Optional[float] = None
    materiality_score: Optional[float] = None
    effective_weight: Optional[float] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class EventListItem(BaseModel):
    """Lean list row — only fields rendered by the Events table / timeline."""

    id: int
    ticker: Optional[str] = None
    event_type: str
    event_date: datetime
    impact: Optional[str] = None
    impact_score: Optional[float] = None
    confidence: Optional[float] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    events: list[EventListItem]