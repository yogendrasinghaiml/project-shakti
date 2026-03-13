from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
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
MIGRATION_RUNNER = Path(__file__).resolve().parents[2] / "ops" / "db" / "migrate.py"
RUN_INTEGRATION_ENV = "SHAKTI_RUN_INTEGRATION"
DB_READY_TIMEOUT_SECONDS = float(os.getenv("SHAKTI_TEST_DB_READY_TIMEOUT_SECONDS", "10"))
DB_CONNECT_TIMEOUT_SECONDS = float(os.getenv("SHAKTI_TEST_DB_CONNECT_TIMEOUT_SECONDS", "1.5"))

pytestmark = pytest.mark.integration


def _integration_enabled() -> bool:
    return os.getenv(RUN_INTEGRATION_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _run_migration_cli(*args: str) -> None:
    subprocess.run(
        [sys.executable, str(MIGRATION_RUNNER), "--dsn", TEST_PG_DSN, *args],
        check=True,
        capture_output=True,
        text=True,
    )


async def _wait_for_db_ready_async(timeout_seconds: float = DB_READY_TIMEOUT_SECONDS) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(TEST_PG_DSN, timeout=DB_CONNECT_TIMEOUT_SECONDS)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception:
            await asyncio.sleep(0.5)
    raise RuntimeError(
        f"PostgreSQL test database at {TEST_PG_DSN} did not become ready within {timeout_seconds:g}s."
    )


def _run_async(coro):
    return asyncio.run(coro)


async def _reset_and_apply_schema() -> None:
    await _execute(
        """
        DROP SCHEMA IF EXISTS shakti_meta CASCADE;
        DROP SCHEMA IF EXISTS public CASCADE;
        CREATE SCHEMA public;
        GRANT ALL ON SCHEMA public TO CURRENT_USER;
        GRANT ALL ON SCHEMA public TO PUBLIC;
        """
    )
    _run_migration_cli("up")
    _run_migration_cli("drift-check", "--require-up-to-date")


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
    if not _integration_enabled():
        pytest.skip(
            f"Set {RUN_INTEGRATION_ENV}=1 to run live PostgreSQL integration tests.",
            allow_module_level=True,
        )
    try:
        _run_async(_wait_for_db_ready_async())
    except RuntimeError as exc:
        pytest.skip(f"Skipping live PostgreSQL integration tests: {exc}", allow_module_level=True)
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


def test_schema_migration_history_is_recorded():
    rows = _run_async(
        _fetch(
            """
            SELECT version, name
            FROM shakti_meta.schema_migrations
            ORDER BY sequence_id
            """
        )
    )
    assert rows == [
        {"version": "0001", "name": "phase2_foundation"},
        {"version": "0002", "name": "runtime_guards"},
    ]


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


def test_live_api_recent_observations_endpoint_returns_api_backed_events():
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
        headers = build_auth_claim_headers(
            user_id=actor_user_id,
            clearance=ClearanceLevel.TOP_SECRET,
            shared_secret=TEST_AUTH_SECRET,
        )

        ingest = client.post(
            "/v1/ingest/hook",
            headers=headers,
            json={
                "target_id": "LIVE-OBS-TARGET-1",
                "source_id": "SRC-OBS-A",
                "source_type": "REST_HOOK",
                "observed_at": "2026-03-02T00:05:00Z",
                "classification_marking": "SECRET",
                "confidence": 0.88,
                "coordinate": {"lat": 28.6139, "lon": 77.2090},
                "unit_type": "HOSTILE",
                "payload": {"sensor": "obs-a"},
            },
        )
        assert ingest.status_code == 200

        recent = client.get(
            "/v1/observations/recent?limit=20",
            headers=build_auth_claim_headers(
                user_id=actor_user_id,
                clearance=ClearanceLevel.TOP_SECRET,
                shared_secret=TEST_AUTH_SECRET,
            ),
        )
        assert recent.status_code == 200
        items = recent.json()
        assert any(item["target_id"] == "LIVE-OBS-TARGET-1" for item in items)
