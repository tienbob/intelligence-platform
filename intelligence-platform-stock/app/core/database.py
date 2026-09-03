"""
Database engine and session management.

Uses SQLAlchemy 2.0 async style with asyncpg/psycopg.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from pgvector.asyncpg import register_vector

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=settings.DB_ECHO,
    future=True,
)


def _register_pgvector_codec(dbapi_connection, _connection_record) -> None:
    """Register the pgvector type codec on each pooled asyncpg connection.

    pgvector's SQLAlchemy ``Vector`` column type round-trips through
    asyncpg using a binary codec.  Without this registration, parameterized
    queries with raw ``<=>`` operators (RAG retrieval) fail with:

        invalid input syntax for type vector: "[0.1, 0.2, ...]"
    """

    async def _safe_register(conn):
        try:
            await register_vector(conn)
        except Exception as exc:
            # Log at ERROR level so a failed vector codec registration is
            # visible rather than silently swallowed. This is a core database
            # type — a failure here causes confusing bind errors later.
            logger.error("pgvector codec registration failed: %s", exc)

    dbapi_connection.run_async(_safe_register)


event.listen(engine.sync_engine, "connect", _register_pgvector_codec)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (useful for development / testing)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def verify_embedding_dimensions() -> None:
    """Fail loud on boot if the DB's ``embeddings.embedding`` vector width
    disagrees with ``settings.EMBEDDING_DIMENSIONS``.

    pgvector stores ``atttypmod`` == the declared dimension on a
    ``vector(n)`` column, so comparing ``pg_attribute.atttypmod`` to the
    configured width catches a dimension drift that would otherwise surface
    only as opaque "vector must have N dimensions" errors at write time.

    A missing ``embeddings`` table (fresh DB before migrations / CI) is
    treated as non-fatal — the check only trips when the column exists but
    is the wrong width. See MIGRATION_FIX_PLAN.md §P1.

    Async: runs through the async engine directly. (The previous sync-engine
    implementation raised ``MissingGreenlet`` against the asyncpg engine and
    was silently swallowed by callers — Gate 4.2 fixed that so the mismatch
    actually surfaces instead of being skipped at boot.)
    """
    from sqlalchemy import text

    expected = settings.EMBEDDING_DIMENSIONS

    async with engine.connect() as conn:
        has_table = (
            await conn.execute(text("SELECT to_regclass('embeddings') IS NOT NULL"))
        ).scalar()
        if not has_table:
            logger.warning(
                "embeddings table not found; skipping EMBEDDING_DIMENSIONS check "
                "(likely a fresh DB / test database before migrations)."
            )
            return

        actual = (
            await conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'embeddings'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar()

    if actual is not None and actual != expected:
        raise RuntimeError(
            f"EMBEDDING_DIMENSIONS={expected} but the `embeddings.embedding` "
            f"column is vector({actual}). Run / review the embedding-dimension "
            "migration before starting the service."
        )
    logger.info(
        "Embedding dimension check passed: configured=%d db=%s",
        expected,
        actual,
    )


async def commit_session(session: AsyncSession) -> None:
    """Commit a session with automatic rollback on error.

    Use this helper instead of calling ``session.commit()`` directly to
    ensure the session is rolled back on exceptions and to keep callsites
    concise.
    """
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise