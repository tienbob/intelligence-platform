"""
Integration tests against a throwaway, fully-migrated Postgres.

Run via scripts/integration_test.sh (which starts pgvector, applies Alembic
to head, and points DATABASE_URL here). Registered with the ``integration``
marker so the default hermetic unit suite skips this directory.
"""

import pytest

# NB: actual tests live in test_schema_upserts.py; this module only holds the
# shared fixtures for the throwaway-DB session lifecycle.
