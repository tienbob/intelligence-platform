"""
Pydantic schemas for alerts (Section 42).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class AlertCreateRequest(BaseModel):
    """POST /api/v1/alerts/ request (Section 42)."""

    ticker: Optional[str] = None
    alert_type: str
    severity: str = "medium"
    message: str
    data: Optional[dict[str, Any]] = None


class AlertResponse(BaseModel):
    """Lean alert — only fields rendered by the FE feed."""

    id: int
    ticker: Optional[str] = None
    alert_type: str
    severity: str = "medium"
    message: str

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    alerts: list[AlertResponse]