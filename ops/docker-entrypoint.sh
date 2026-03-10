#!/bin/sh
set -eu

python - <<'PY'
import asyncio
import os
import time
from pathlib import Path

import asyncpg


PG_DSN = os.environ.get("PG_DSN", "postgresql://shakti:shakti@postgres:5432/shakti")
WAIT_TIMEOUT_SECONDS = float(os.environ.get("SHAKTI_DB_WAIT_TIMEOUT_SECONDS", "60"))
CONNECT_TIMEOUT_SECONDS = float(os.environ.get("SHAKTI_DB_CONNECT_TIMEOUT_SECONDS", "3"))
APPLY_SCHEMA = os.environ.get("SHAKTI_APPLY_SCHEMA_ON_BOOT", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SCHEMA_PATH = Path(
    os.environ.get("SHAKTI_SCHEMA_PATH", "/app/db/phase2_schema_postgres_postgis.sql")
)


async def wait_for_database() -> None:
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last_error = "unknown error"
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(PG_DSN, timeout=CONNECT_TIMEOUT_SECONDS)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception as exc:
            last_error = str(exc)
            await asyncio.sleep(1)
    raise RuntimeError(
        f"PostgreSQL at {PG_DSN} did not become ready within {WAIT_TIMEOUT_SECONDS:g}s: {last_error}"
    )


async def apply_schema() -> None:
    if not APPLY_SCHEMA:
        return
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = await asyncpg.connect(PG_DSN, timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        await conn.execute(schema_sql)
    finally:
        await conn.close()


async def main() -> None:
    await wait_for_database()
    await apply_schema()


asyncio.run(main())
PY

exec uvicorn backend.intelligence_fusion_service:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
