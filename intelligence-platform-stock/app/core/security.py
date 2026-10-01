"""
Security utilities (Phase 8, Sections 84-88).

Implements:
- JWT/OAuth2 authentication
- RBAC authorization (USER, ANALYST, ADMIN, SYSTEM)
- API key authentication
- Input validation helpers
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class Role(str, Enum):
    """RBAC roles (Section 85)."""

    USER = "USER"
    ANALYST = "ANALYST"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


# Role hierarchy: higher roles inherit lower role permissions
ROLE_HIERARCHY: dict[Role, set[Role]] = {
    Role.USER: {Role.USER},
    Role.ANALYST: {Role.USER, Role.ANALYST},
    Role.ADMIN: {Role.USER, Role.ANALYST, Role.ADMIN},
    Role.SYSTEM: {Role.USER, Role.ANALYST, Role.ADMIN, Role.SYSTEM},
}


class AuthContext:
    """Authenticated user context."""

    def __init__(
        self,
        subject: str,
        role: Role = Role.USER,
        scopes: list[str] | None = None,
        api_key: str | None = None,
    ):
        self.subject = subject
        self.role = role
        self.scopes = scopes or []
        self.api_key = api_key

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN in ROLE_HIERARCHY[self.role]

    @property
    def is_analyst(self) -> bool:
        return Role.ANALYST in ROLE_HIERARCHY[self.role]

    def has_role(self, required: Role) -> bool:
        """Check if this context has the required role (or higher)."""
        return required in ROLE_HIERARCHY[self.role]


def create_access_token(
    subject: str,
    role: Role = Role.USER,
    scopes: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    import jwt

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if scopes:
        payload["scopes"] = scopes
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, role: Role = Role.USER) -> str:
    """Create a JWT refresh token."""
    import jwt

    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token."""
    import jwt

    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> AuthContext:
    """
    Get the current authenticated user from a JWT bearer token.

    If ``AUTH_ENABLED`` is False, returns an anonymous SYSTEM context.
    """
    if not settings.AUTH_ENABLED:
        return AuthContext(subject="anonymous", role=Role.SYSTEM)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    subject = payload.get("sub", "unknown")
    role_name = payload.get("role", Role.USER.value)
    try:
        role = Role(role_name)
    except ValueError:
        role = Role.USER

    return AuthContext(
        subject=subject,
        role=role,
        scopes=payload.get("scopes"),
    )


def require_role(required: Role):
    """
    Dependency factory that requires a specific role (or higher).

    Usage:
        @router.get("/admin")
        async def admin_endpoint(user: AuthContext = Depends(require_role(Role.ADMIN))):
            ...
    """

    async def _dependency(user: AuthContext = Depends(get_current_user)) -> AuthContext:
        if not user.has_role(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role {required.value} or higher",
            )
        return user

    return _dependency


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify the API key provided in the X-API-Key header.

    If no ``APP_API_KEY`` is configured in settings, the endpoint is open.
    """
    if not getattr(settings, "APP_API_KEY", None):
        return "anonymous"

    expected = getattr(settings, "APP_API_KEY", None)
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key


# ── Internal service-key auth (Rails → Python gateway) ──────────────
#
# The internal `/internal` API is only reachable by trusted services
# (the Rails gateway). It authenticates via the `X-Service-Key` header
# validated against ``INTERNAL_SERVICE_KEY`` (or the legacy APP_API_KEY).
#
# Rails forwards the acting user's identity via `X-User-Id`/`X-User-Role`
# headers so Python can scope requests per user without trusting user JWTs.
#
# Ownership model (global market data + user-bound actions):
#   - GLOBAL (no scoping): companies, prices, financials, news, events,
#     market, investment_scores, backtest_snapshots, alerts.
#   - USER-BOUND: analyses + backtest_runs (+ their child rows via join).
#     ``user_id=NULL`` = system/scheduler legacy row → visible to everyone.
async def verify_internal_service_key(
    api_key: Optional[str] = Security(api_key_header),
    x_service_key: Optional[str] = Security(APIKeyHeader(name="X-Service-Key", auto_error=False)),
) -> dict[str, Optional[str]]:
    """
    Verify the internal service key for the Rails→Python gateway.

    Accepts either the X-Service-Key header or the legacy X-API-Key header.
    Returns a dict of forwarded user identity headers (may be empty).
    """
    expected = getattr(settings, "INTERNAL_SERVICE_KEY", None) or getattr(settings, "APP_API_KEY", None)
    if not expected:
        # No internal key configured — allow (dev mode), matching AUTH_ENABLED=false behavior.
        return {}

    provided = x_service_key or api_key
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal service key",
        )

    return {}


def get_actor(request: Any) -> dict[str, Any]:
    """Extract the acting user forwarded by Rails (`X-User-Id`/`X-User-Role`).

    Returns ``{"user_id": int | None, "role": str}``. ``user_id=None`` means
    anonymous/system context (dev mode or scheduler) — sees system rows only
    via the NULL-inclusive visibility rule.
    """
    user_id: int | None = None
    try:
        raw = request.headers.get("X-User-Id") if request is not None else None
        if raw not in (None, "", "None", "null"):
            user_id = int(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        user_id = None
    try:
        role = request.headers.get("X-User-Role") if request is not None else None
    except AttributeError:
        role = None
    # A missing/blank role must never imply SYSTEM (admin-equivalent) — that
    # would upgrade an identity-less request to full visibility (audit S01).
    # Rails always forwards the acting role; header-less internal callers fall
    # back to the least-privileged role instead.
    return {"user_id": user_id, "role": (role or "USER").upper()}


def is_admin_actor(actor: dict[str, Any] | None) -> bool:
    """ADMIN/SYSTEM roles bypass ownership (support + ops visibility)."""
    return bool(actor) and str(actor.get("role", "")).upper() in {"ADMIN", "SYSTEM"}


def visible_to_actor(column: Any, actor: dict[str, Any] | None) -> Any:
    """SQLAlchemy filter: own rows + system (NULL) rows.

    Admin/SYSTEM (incl. anonymous dev context) see everything; regular users
    see ``column == user_id OR column IS NULL``.
    """
    if actor is None or is_admin_actor(actor):
        return True
    uid = actor.get("user_id")
    if uid is None:
        # No identity and not admin (shouldn't happen — Rails always
        # forwards; defensive): only system rows, never another user's.
        return column.is_(None)
    return (column == uid) | (column.is_(None))


def owns_row(row_user_id: int | None, actor: dict[str, Any] | None) -> bool:
    """Row-level ownership check for single-row GET/DELETE."""
    if actor is None or is_admin_actor(actor):
        return True
    uid = actor.get("user_id")
    if row_user_id is None:
        return True  # system row — visible to everyone
    return uid is not None and row_user_id == uid


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return secrets.token_urlsafe(32)


def validate_identifier(
    value: str,
    pattern: str = r"^[A-Za-z0-9.\-_]{1,100}$",
    label: str = "identifier",
) -> str:
    """Validate a generic entity identifier against a regex pattern.

    This is a domain-neutral validation helper. Domain-specific validation
    (e.g. ticker format, candidate ID format) should be implemented in the
    domain package using this helper or their own logic.

    Args:
        value: The identifier string to validate.
        pattern: Regex pattern the identifier must match.
        label: Human-readable label for error messages.

    Returns:
        The validated (and stripped) identifier.

    Raises:
        HTTPException 422 if the identifier does not match the pattern.
    """
    import re

    value = value.strip()
    if not re.match(pattern, value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {label} format: {value}",
        )
    return value


def validate_date_range(start: datetime, end: datetime) -> None:
    """Validate that start <= end and range is within reasonable bounds."""
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must be before end_date",
        )
    if (end - start).days > 3650:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date range exceeds 10 years",
        )


# ── Idempotency-Key support (Architecture §101) ──────────────────
#
# Idempotency is checked before expensive work and stored after it completes.
# Storage is two-tier (audit F04 remainder):
#   1. Redis (shared, survives restarts/workers) when configured.
#   2. The process-local dict as a transparent fallback (dev, Redis down).
#
# Both tiers use the same namespaced keys (actor + method + path + key +
# body fingerprint), so behaviour is identical whichever tier serves.
# check_idempotency/store_idempotency_result keep their signatures:
# async store falls back to memory synchronously, so callers are unchanged.
_idempotency_store: dict[str, tuple[int, dict[str, Any], float]] = {}

# Outstanding fire-and-forget Redis mirrors (kept alive until they complete).
_idempotency_pending: set = set()


def _idempotency_redis():
    """Shared Redis cache with a dedicated prefix for idempotency records."""
    from app.core.redis_cache import RedisCache

    return RedisCache(
        prefix="mi:idempotency:",
        ttl_seconds=86400,
        enabled=True,  # RedisCache no-ops itself when REDIS_URL is unset
    )


class IdempotencyReplay(Exception):
    """Raised when a request replays a stored idempotent result.

    Carries the ORIGINAL status + payload so the replay response matches the
    first response. Previously the stored body was re-raised as an
    ``HTTPException`` detail, which the envelope middleware turned into
    ``{"error": {"message": <body>}}`` — so a replay returned ``data.detail``
    instead of the original ``data`` payload (audit F04).
    """

    def __init__(self, status_code: int, body: dict[str, Any], key: str):
        self.status_code = status_code
        self.body = body
        self.key = key
        super().__init__(f"Idempotency replay for {key}")


def _idempotency_scope(request: Any) -> str:
    """Actor + method + path namespace for an idempotency key.

    Without the actor part, a key replayed by a different user returned the
    first user's stored response (reproduced in the audit); without the path
    part the same key could collide across endpoints.
    """
    actor = get_actor(request)
    who = f"u{actor.get('user_id')}" if actor.get("user_id") is not None else "anon"
    method = getattr(request, "method", "") or ""
    path = getattr(getattr(request, "url", None), "path", "") or ""
    return f"{who}:{method}:{path}"


async def check_idempotency(request: Any) -> str | None:
    """
    Validate an optional Idempotency-Key header (Architecture §101).

    Returns the namespaced storage key (or ``None`` when no key was supplied)
    so the caller stores its result under the same key. Raises
    ``IdempotencyReplay`` when this (actor, route, key, body) tuple was already
    processed.

    Architecture §101: Idempotency-Key prevents duplicate processing on
    expensive POST endpoints like /analysis/company and /portfolio/optimize.
    """
    import hashlib
    import time

    from fastapi import Request as FastAPIRequest

    if not isinstance(request, FastAPIRequest):
        return None

    raw_key = request.headers.get("Idempotency-Key")
    if not raw_key:
        return None  # No key provided — proceed normally

    # Bind the key to the caller, the operation AND the request body, so a
    # replayed key can never return another user's result and a changed body
    # is treated as a new request (audit F04).
    try:
        body = await request.body()
    except Exception:
        body = b""
    fingerprint = hashlib.sha256(body).hexdigest()[:32]
    key = f"{_idempotency_scope(request)}:{raw_key}:{fingerprint}"

    now = time.monotonic()

    # Clean expired in-memory entries
    expired = [k for k, v in _idempotency_store.items() if v[2] < now]
    for k in expired:
        del _idempotency_store[k]

    # Redis first (shared across workers/restarts), then the local fallback.
    stored = await _idempotency_redis().get(key)
    if stored is not None:
        raise IdempotencyReplay(int(stored["status_code"]), stored["body"], raw_key)

    if key in _idempotency_store:
        status_code, stored_body, _ = _idempotency_store[key]
        raise IdempotencyReplay(status_code, stored_body, raw_key)

    return key


def store_idempotency_result(key: str, status_code: int, body: dict[str, Any], ttl_seconds: int = 86400) -> None:
    """Store the result of an idempotent operation (key from check_idempotency).

    Writes through to Redis when available and always keeps the in-memory
    fallback in sync, so a later Redis outage does not lose recent records.
    """
    import time

    _idempotency_store[key] = (status_code, body, time.monotonic() + ttl_seconds)
    try:
        record = {"status_code": status_code, "body": body}
        asyncio.get_event_loop()
        task = asyncio.ensure_future(
            _idempotency_redis().set(key, record, ttl_seconds=ttl_seconds)
        )
        # Fire-and-forget must not warn on loop shutdown; keep a reference
        # until the write completes.
        _idempotency_pending.add(task)
        task.add_done_callback(_idempotency_pending.discard)
    except RuntimeError:
        pass  # no running loop (tests/sync contexts) — memory store suffices
