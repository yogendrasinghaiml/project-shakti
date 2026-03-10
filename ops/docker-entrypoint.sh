#!/bin/sh
set -eu

python - <<'PY'
import asyncio
import os
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg


def load_text_value(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip()


def load_text_value_from_env_or_file(name: str, default: str = "") -> str:
    raw_value = os.environ.get(name)
    raw_file = os.environ.get(f"{name}_FILE")
    value = raw_value.strip() if raw_value is not None else ""
    file_path = raw_file.strip() if raw_file is not None else ""

    if value and file_path:
        raise RuntimeError(f"{name} and {name}_FILE cannot both be set.")
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"{name}_FILE is unreadable: {file_path}") from exc
    if raw_value is None:
        return default
    return value


PG_DSN = load_text_value_from_env_or_file(
    "PG_DSN",
    "postgresql://shakti:shakti@postgres:5432/shakti",
)
WAIT_TIMEOUT_SECONDS = float(load_text_value("SHAKTI_DB_WAIT_TIMEOUT_SECONDS", "60"))
CONNECT_TIMEOUT_SECONDS = float(load_text_value("SHAKTI_DB_CONNECT_TIMEOUT_SECONDS", "3"))
APPLY_SCHEMA = load_text_value("SHAKTI_APPLY_SCHEMA_ON_BOOT", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SCHEMA_PATH = Path(
    load_text_value("SHAKTI_SCHEMA_PATH", "/app/db/phase2_schema_postgres_postgis.sql")
)


def redact_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if not parts.scheme or parts.hostname is None:
        return dsn
    auth_prefix = ""
    if parts.username:
        auth_prefix = f"{parts.username}:***@"
    host = parts.hostname
    port = f":{parts.port}" if parts.port is not None else ""
    return urlunsplit(
        (
            parts.scheme,
            f"{auth_prefix}{host}{port}",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


async def wait_for_database() -> None:
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last_error = "unknown error"
    redacted_dsn = redact_dsn(PG_DSN)
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(PG_DSN, timeout=CONNECT_TIMEOUT_SECONDS)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception as exc:
            last_error = str(exc).replace(PG_DSN, redacted_dsn)
            await asyncio.sleep(1)
    raise RuntimeError(
        f"PostgreSQL at {redacted_dsn} did not become ready within {WAIT_TIMEOUT_SECONDS:g}s: {last_error}"
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
