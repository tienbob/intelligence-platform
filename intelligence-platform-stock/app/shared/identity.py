"""Application-owned identity & access primitives.

Ownership (docs/TABLE_OWNERSHIP.md): ``users`` / ``user_companies`` are
**application-owned** — semantic owner is the application/auth layer (the
Rails gateway enforces assignments and forwards acting-user identity via
``X-User-Id``). The Python service never writes these tables and contains no
authorization rules; it only resolves read-scope for data endpoints.

This module lives in ``app/shared`` (not ``app/intelligence``, not a domain)
because identity is neither framework- nor domain-owned.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin

__all__ = [
    "REQUESTER_HEADER",
    "UserCompany",
    "company_is_scoped",
    "requester_company_ids",
    "requester_id_from_headers",
    "requester_scope",
    "scope_company_query",
    "scoped_where",
]


class UserCompany(Base, TimestampMixin):
    """Junction granting a user visibility of one tracked company.

    users ──< user_companies >── companies
    """

    __tablename__ = "user_companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<UserCompany(user_id={self.user_id}, company_id={self.company_id})>"


REQUESTER_HEADER = "X-User-Id"


def requester_id_from_headers(headers: Any) -> int | None:
    """Extract the acting user id from gateway-forwarded headers.

    Rails sets ``X-User-Id`` on every proxied call (absent when auth is
    disabled / anonymous). Returns ``None`` when absent or non-numeric.
    """
    raw = headers.get(REQUESTER_HEADER) if headers is not None else None
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


async def requester_company_ids(
    session: Any,
    user_id: int | None,
) -> set[int] | None:
    """Company ids visible to ``user_id``.

    Returns ``None`` when ``user_id`` is None (unscoped/system context →
    caller may show everything, matching anonymous dev mode).
    """
    if user_id is None:
        return None
    rows = await session.execute(
        select(UserCompany.company_id).where(UserCompany.user_id == user_id)
    )
    return {row[0] for row in rows.all()}


async def requester_scope(request: Any, session: Any) -> set[int] | None:
    """Convenience: resolve a request's granted company-id set in one call.

    Reads ``X-User-Id`` from ``request.headers``, then loads the caller's
    ``user_companies`` grants. Returns ``None`` for unscoped/system callers
    (anonymous or auth-disabled), matching ``requester_company_ids``.
    """
    return await requester_company_ids(
        session, requester_id_from_headers(request.headers if request else None)
    )


def scoped_where(query: Any, column: Any, company_ids: set[int] | None):
    """Apply access scope to an arbitrary company-keyed ``column``.

    - scope ``None``  → unscoped (system/anonymous context), unchanged query
    - empty set       → force-zero rows (user exists but no grants)

    Works for any SQLAlchemy column that references a company id (e.g.
    ``Analysis.company_id``, ``Alert.company_id``, ``MarketEvent.company_id``),
    not just ``Company.id``.
    """
    if company_ids is None:
        return query
    if not company_ids:
        return query.where(column == -1)
    return query.where(column.in_(company_ids))


def company_is_scoped(company_id: int | None, company_ids: set[int] | None) -> bool:
    """True when a single ``company_id`` is visible to the caller's scope.

    - scope ``None``            → unscoped (system/anonymous) → visible
    - otherwise                 → visible only if in the granted set
    """
    if company_ids is None:
        return True
    return company_id is not None and company_id in company_ids


def scope_company_query(query: Any, model: type, company_ids: set[int] | None):
    """Apply access scope to a Company query.

    - scope ``None``  → unscoped (system/anonymous context), unchanged query
    - empty set       → force-zero rows (user exists but no grants)

    Thin wrapper over :func:`scoped_where` for ``Company.id`` (kept for
    backward compatibility; new callers should use ``scoped_where`` directly).
    """
    return scoped_where(query, model.id, company_ids)
