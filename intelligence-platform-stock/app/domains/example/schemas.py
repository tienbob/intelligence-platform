"""Example domain Pydantic schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ProductAnalysisRequest(BaseModel):
    product_id: str


class ProductAnalysisResponse(BaseModel):
    analysis_id: str
    status: str
    product_id: Optional[str] = None
    score: Optional[float] = None
    confidence: Optional[float] = None
    recommendation: Optional[str] = None
    analysis: Optional[dict[str, Any]] = None