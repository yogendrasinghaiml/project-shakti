from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from backend.intelligence_fusion_service import (
    ClearanceLevel,
    Settings,
    build_auth_claim_headers,
    create_app,
)

TEST_PG_DSN = os.getenv(
    "SHAKTI_TEST_PG_DSN",
    "postgresql://shakti:shakti@127.0.0.1:55432/shakti",
)
TEST_AUTH_SECRET = "integration-shared-secret"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "db" / "phase2_schema_postgres_postgis.sql"
)


def _run_psql(*args: str) -> None:
    subprocess.run(
        ["psql", TEST_PG_DSN, "-v", "ON_ERROR_STOP=1", *args],
        check=True,
        capture_output=True,
        text=True,
    )


async def _wait_for_db_ready_async(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(TEST_PG_DSN)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError("PostgreSQL test database did not become ready in time.")


def _run_async(coro):
    return asyncio.run(coro)


async def _reset_and_apply_schema() -> None:
    _run_psql("-c", "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    _run_psql("-f", str(SCHEMA_PATH))


async def _fetchval(query: str, *args):
    conn = await asyncpg.connect(TEST_PG_DSN)
    try:
        return await conn.fetchval(query, *args)
    finally:
        await conn.close()


async def _fetch(query: str, *args):
    conn = await asyncpg.connect(TEST_PG_DSN)
    try:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def _execute(query: str, *args) -> None:
    conn = await asyncpg.connect(TEST_PG_DSN)
    try:
        await conn.execute(query, *args)
    finally:
        await conn.close()


async def _seed_user(user_id: str, clearance: ClearanceLevel) -> None:
    conn = await asyncpg.connect(TEST_PG_DSN)
    try:
        await conn.execute(
            """
            INSERT INTO users (
              user_id,
              username,
              display_name,
              is_active,
              clearance_level,
              last_modified_by
            )
            VALUES ($1::uuid, $2, $3, TRUE, $4::clearance_level, $1::uuid)
            ON CONFLICT (user_id) DO UPDATE
            SET clearance_level = EXCLUDED.clearance_level,
                is_active = TRUE
            """,
            user_id,
            f"user-{user_id}",
            "Integration Test User",
            clearance.value,
        )
    finally:
        await conn.close()


def setup_module() -> None:
    _run_async(_wait_for_db_ready_async())
    _run_async(_reset_and_apply_schema())


def test_schema_has_default_sensor_logs_partition():
    bound_expr = _run_async(
        _fetchval(
            """
            SELECT pg_get_expr(c.relpartbound, c.oid)
            FROM pg_class c
            WHERE c.relname = 'sensor_logs_default'
            """
        )
    )
    assert bound_expr == "DEFAULT"


def test_schema_forces_rls_on_sensitive_tables():
    rows = _run_async(
        _fetch(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = ANY($1::text[])
            ORDER BY relname
            """,
            [
                "targets",
                "intel_observations",
                "coordinate_conflicts",
                "sensor_logs",
                "fusion_reports",
                "policy_decisions",
            ],
        )
    )
    assert len(rows) == 6
    for row in rows:
        assert row["relrowsecurity"] is True
        assert row["relforcerowsecurity"] is True


def test_schema_has_persistent_api_rate_limit_guard():
    table_exists = _run_async(
        _fetchval("SELECT to_regclass('public.api_rate_limit_guard') IS NOT NULL")
    )
    index_exists = _run_async(
        _fetchval(
            "SELECT to_regclass('public.idx_api_rate_limit_guard_window_start') IS NOT NULL"
        )
    )
    pk_exists = _run_async(
        _fetchval(
            """
            SELECT EXISTS (
              SELECT 1
              FROM pg_constraint
              WHERE conrelid = 'public.api_rate_limit_guard'::regclass
                AND contype = 'p'
            )
            """
        )
    )
    assert table_exists is True
    assert index_exists is True
    assert pk_exists is True


def test_live_api_enforces_actor_provisioning_and_conflict_flow():
    actor_user_id = str(uuid4())
    _run_async(_seed_user(actor_user_id, ClearanceLevel.TOP_SECRET))

    app = create_app(
        settings=Settings(
            pg_dsn=TEST_PG_DSN,
            auth_shared_secret_primary=TEST_AUTH_SECRET,
            auth_require_persistent_replay_guard=True,
            auth_expected_audience="shakti-intelligence-fusion",
            max_ingest_bytes=65536,
        ),
        repository=None,
        enable_mqtt=False,
    )

    with TestClient(app) as client:
        unprovisioned_headers = build_auth_claim_headers(
            user_id=str(uuid4()),
            clearance=ClearanceLevel.TOP_SECRET,
            shared_secret=TEST_AUTH_SECRET,
        )
        denied = client.post(
            "/v1/ingest/hook",
            headers=unprovisioned_headers,
            json={
                "target_id": "LIVE-TARGET-UNPROVISIONED",
                "source_id": "SRC-A",
                "source_type": "REST_HOOK",
                "observed_at": "2026-03-02T00:00:00Z",
                "classification_marking": "SECRET",
                "confidence": 0.8,
                "coordinate": {"lat": 28.6139, "lon": 77.2090},
                "unit_type": "HOSTILE",
                "payload": {"k": "v"},
            },
        )
        assert denied.status_code == 403
        assert "not provisioned" in denied.json()["detail"].lower()

        headers = build_auth_claim_headers(
            user_id=actor_user_id,
            clearance=ClearanceLevel.TOP_SECRET,
            shared_secret=TEST_AUTH_SECRET,
        )

        first = client.post(
            "/v1/ingest/hook",
            headers=headers,
            json={
                "target_id": "LIVE-TARGET-1",
                "source_id": "SRC-A",
                "source_type": "REST_HOOK",
                "observed_at": "2026-03-02T00:01:00Z",
                "classification_marking": "SECRET",
                "confidence": 0.91,
                "coordinate": {"lat": 28.6139, "lon": 77.2090},
                "unit_type": "HOSTILE",
                "payload": {"sensor": "alpha"},
            },
        )
        assert first.status_code == 200
        assert first.json()["conflict_flagged"] is False

        second = client.post(
            "/v1/ingest/hook",
            headers=build_auth_claim_headers(
                user_id=actor_user_id,
                clearance=ClearanceLevel.TOP_SECRET,
                shared_secret=TEST_AUTH_SECRET,
            ),
            json={
                "target_id": "LIVE-TARGET-1",
                "source_id": "SRC-B",
                "source_type": "REST_HOOK",
                "observed_at": "2026-03-02T00:02:00Z",
                "classification_marking": "SECRET",
                "confidence": 0.83,
                "coordinate": {"lat": 19.0760, "lon": 72.8777},
                "unit_type": "HOSTILE",
                "payload": {"sensor": "bravo"},
            },
        )
        assert second.status_code == 200
        assert second.json()["conflict_flagged"] is True

        conflicts = client.get(
            "/v1/conflicts/pending?limit=50",
            headers=build_auth_claim_headers(
                user_id=actor_user_id,
                clearance=ClearanceLevel.TOP_SECRET,
                shared_secret=TEST_AUTH_SECRET,
            ),
        )
        assert conflicts.status_code == 200
        body = conflicts.json()
        assert any(item["target_id"] == "LIVE-TARGET-1" for item in body)


def test_live_api_uses_persistent_postgres_rate_limiter():
    actor_user_id = str(uuid4())
    _run_async(_seed_user(actor_user_id, ClearanceLevel.TOP_SECRET))
    _run_async(_execute("DELETE FROM api_rate_limit_guard"))

    app = create_app(
        settings=Settings(
            pg_dsn=TEST_PG_DSN,
            auth_shared_secret_primary=TEST_AUTH_SECRET,
            auth_require_persistent_replay_guard=True,
            auth_expected_audience="shakti-intelligence-fusion",
            api_rate_limit_enabled=True,
            api_rate_limit_require_persistent=True,
            api_rate_limit_requests=1,
            api_rate_limit_window_seconds=60,
            max_ingest_bytes=65536,
        ),
        repository=None,
        enable_mqtt=False,
    )

    with TestClient(app) as client:
        first = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=build_auth_claim_headers(
                user_id=actor_user_id,
                clearance=ClearanceLevel.TOP_SECRET,
                shared_secret=TEST_AUTH_SECRET,
            ),
        )
        second = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=build_auth_claim_headers(
                user_id=actor_user_id,
                clearance=ClearanceLevel.TOP_SECRET,
                shared_secret=TEST_AUTH_SECRET,
            ),
        )
        assert first.status_code == 200
        assert second.status_code == 429
