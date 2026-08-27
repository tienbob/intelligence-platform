#!/bin/bash
set -euo pipefail

echo "Checking database migration state..."

ACTION=$(python - <<'PY'
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def check():
    engine = create_async_engine(os.environ["DATABASE_URL"])

    try:
        async with engine.connect() as conn:
            alembic_exists = (
                await conn.execute(
                    text("SELECT to_regclass('public.alembic_version')")
                )
            ).scalar() is not None

            if alembic_exists:
                count = (
                    await conn.execute(
                        text("SELECT COUNT(*) FROM alembic_version")
                    )
                ).scalar()

                if count and count > 0:
                    return "upgrade"

            companies_exists = (
                await conn.execute(
                    text("SELECT to_regclass('public.companies')")
                )
            ).scalar() is not None

            if companies_exists:
                return "stamp"

            return "upgrade"

    finally:
        await engine.dispose()


print(asyncio.run(check()))
PY
)

case "$ACTION" in
  stamp)
    echo "Existing Rails schema detected."
    echo "Stamping Alembic at head..."
    alembic stamp head
    ;;

  upgrade)
    echo "Running Alembic migrations..."
    alembic upgrade head
    ;;

  *)
    echo "ERROR: Unknown migration action: $ACTION"
    exit 1
    ;;
esac

echo "Migration step completed."