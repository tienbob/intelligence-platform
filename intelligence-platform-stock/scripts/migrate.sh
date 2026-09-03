#!/bin/bash
set -euo pipefail

echo "Running Alembic migrations..."

alembic upgrade head

echo "Migration step completed."