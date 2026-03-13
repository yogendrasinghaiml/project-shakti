#!/bin/sh
set -eu

MIGRATION_MODE="$(printf '%s' "${SHAKTI_DB_MIGRATION_MODE:-auto}" | tr '[:upper:]' '[:lower:]')"
MIGRATION_RUNNER="/app/ops/db/migrate.py"

python "$MIGRATION_RUNNER" wait

case "$MIGRATION_MODE" in
  auto)
    python "$MIGRATION_RUNNER" up
    ;;
  verify)
    python "$MIGRATION_RUNNER" drift-check --require-up-to-date
    ;;
  off)
    ;;
  *)
    echo "Unsupported SHAKTI_DB_MIGRATION_MODE: $MIGRATION_MODE (expected auto|verify|off)" >&2
    exit 1
    ;;
esac

exec uvicorn backend.intelligence_fusion_service:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
