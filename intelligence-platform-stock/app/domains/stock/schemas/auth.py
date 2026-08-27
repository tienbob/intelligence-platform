"""
Pydantic schemas for authentication endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """POST /auth/register request."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    """POST /auth/login request."""
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """POST /auth/refresh request."""
    refresh_token: str


class TokenResponse(BaseModel):
    """JWT token pair response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """GET /auth/me response."""
    id: int
    email: str
    name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}