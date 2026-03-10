from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.intelligence_fusion_service import (
    AUTH_CLAIMS_HEADER,
    AUTH_DEFAULT_AUDIENCE,
    AUTH_SIGNATURE_HEADER,
    ClearanceLevel,
    ConflictOut,
    InMemoryReplayGuard,
    IntelObservationIn,
    IngestResult,
    JsonLogFormatter,
    PostgresFusionRepository,
    Settings,
    build_auth_claim_headers,
    create_app,
    clearance_allows,
    haversine_distance_m,
)

TEST_AUTH_SECRET = "test-shared-secret"
TEST_AUTH_SECRET_SECONDARY = "test-shared-secret-secondary"


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.conflicts: list[ConflictOut] = []
        self.last_conflict_clearance: ClearanceLevel | None = None

    async def ingest_observation(self, observation, actor_user_id, actor_clearance):
        self.calls.append(
            {
                "observation": observation,
                "actor_user_id": actor_user_id,
                "actor_clearance": actor_clearance,
            }
        )
        return IngestResult(
            observation_id=uuid4(),
            conflict_flagged=False,
            message="ok",
        )

    async def pending_conflicts_for_clearance(
        self,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
        limit: int = 100,
    ):
        self.last_conflict_clearance = actor_clearance
        return self.conflicts[:limit]


class DenyRepository:
    async def ingest_observation(self, observation, actor_user_id, actor_clearance):
        raise PermissionError("Authenticated actor is not provisioned.")

    async def pending_conflicts_for_clearance(
        self,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
        limit: int = 100,
    ):
        raise PermissionError("Authenticated actor is inactive.")


def make_payload(classification: str = "SECRET") -> dict[str, Any]:
    return {
        "target_id": "TARGET-123",
        "source_id": "HOOK-ALPHA",
        "source_type": "REST_HOOK",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "classification_marking": classification,
        "confidence": 0.92,
        "coordinate": {"lat": 28.6139, "lon": 77.2090},
        "unit_type": "HOSTILE",
        "payload": {"signal": "test"},
    }


def make_settings(**kwargs: Any) -> Settings:
    defaults: dict[str, Any] = {
        "auth_shared_secret_primary": TEST_AUTH_SECRET,
        "auth_require_persistent_replay_guard": False,
        "api_rate_limit_require_persistent": False,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def make_auth_headers(
    clearance: ClearanceLevel = ClearanceLevel.TOP_SECRET,
    user_id: str | None = None,
    issued_at: int | None = None,
    shared_secret: str = TEST_AUTH_SECRET,
    jti: str | None = None,
    audience: str = AUTH_DEFAULT_AUDIENCE,
) -> dict[str, str]:
    return build_auth_claim_headers(
        user_id=user_id or str(uuid4()),
        clearance=clearance,
        shared_secret=shared_secret,
        issued_at=issued_at,
        jti=jti,
        audience=audience,
    )


def make_request(app, path: str, method: str = "GET") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def get_route_endpoint(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route {path} not found")


def test_clearance_policy_matrix():
    assert clearance_allows(ClearanceLevel.TOP_SECRET, ClearanceLevel.SECRET)
    assert clearance_allows(ClearanceLevel.SECRET, ClearanceLevel.SECRET)
    assert not clearance_allows(ClearanceLevel.CONFIDENTIAL, ClearanceLevel.SECRET)
    assert not clearance_allows(ClearanceLevel.UNCLASSIFIED, ClearanceLevel.CONFIDENTIAL)


def test_haversine_distance_is_reasonable():
    # Delhi to Mumbai is roughly ~1,150 km geodesic.
    distance = haversine_distance_m(28.6139, 77.2090, 19.0760, 72.8777)
    assert 1100000 <= distance <= 1300000


def test_clearance_middleware_rejects_lower_clearance():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        response = client.post(
            "/v1/ingest/hook",
            headers=make_auth_headers(clearance=ClearanceLevel.CONFIDENTIAL),
            json=make_payload(classification="SECRET"),
        )
        assert response.status_code == 403
        assert "Insufficient clearance" in response.json()["detail"]


def test_protected_routes_require_signed_gateway_claims():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        response = client.post(
            "/v1/ingest/hook",
            headers={},
            json=make_payload(classification="SECRET"),
        )
        assert response.status_code == 401
        assert AUTH_CLAIMS_HEADER in response.json()["detail"]


def test_ingest_enforces_max_body_size_limit():
    app = create_app(
        settings=make_settings(max_ingest_bytes=64),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with TestClient(app) as client:
        payload = make_payload(classification="SECRET")
        payload["payload"] = {"blob": "X" * 512}
        response = client.post(
            "/v1/ingest/hook",
            headers=make_auth_headers(clearance=ClearanceLevel.TOP_SECRET),
            json=payload,
        )
        assert response.status_code == 413


def test_ingest_enforces_max_body_size_limit_for_chunked_bodies():
    app = create_app(
        settings=make_settings(max_ingest_bytes=128),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    raw_payload = json.dumps(make_payload(classification="SECRET")).encode("utf-8")

    def chunked_body():
        midpoint = len(raw_payload) // 2
        yield raw_payload[:midpoint]
        yield raw_payload[midpoint:]

    with TestClient(app) as client:
        response = client.post(
            "/v1/ingest/hook",
            headers={
                **make_auth_headers(clearance=ClearanceLevel.TOP_SECRET),
                "Content-Type": "application/json",
            },
            content=chunked_body(),
        )
        assert response.status_code == 413


def test_hook_ingest_calls_repository_with_valid_clearance():
    repo = FakeRepository()
    app = create_app(settings=make_settings(), repository=repo, enable_mqtt=False)
    user_id = str(uuid4())

    with TestClient(app) as client:
        response = client.post(
            "/v1/ingest/hook",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=user_id,
            ),
            json=make_payload(classification="SECRET"),
        )
        assert response.status_code == 200
        assert len(repo.calls) == 1
        assert repo.calls[0]["actor_user_id"] == user_id
        assert repo.calls[0]["actor_clearance"] == ClearanceLevel.TOP_SECRET


def test_ingest_returns_403_when_repository_denies_actor():
    app = create_app(settings=make_settings(), repository=DenyRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        response = client.post(
            "/v1/ingest/hook",
            headers=make_auth_headers(clearance=ClearanceLevel.TOP_SECRET),
            json=make_payload(classification="SECRET"),
        )
        assert response.status_code == 403
        assert "not provisioned" in response.json()["detail"].lower()


def test_ingest_rejects_missing_actor_identity_state():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    request = make_request(app, "/v1/ingest/hook", method="POST")
    request.state.user_clearance = ClearanceLevel.TOP_SECRET
    endpoint = get_route_endpoint(app, "/v1/ingest/hook")
    observation = IntelObservationIn.model_validate(make_payload(classification="SECRET"))

    with pytest.raises(HTTPException, match="Missing validated actor identity"):
        asyncio.run(endpoint(observation, request))


def test_pending_conflicts_endpoint():
    repo = FakeRepository()
    repo.conflicts = [
        ConflictOut(
            conflict_id=UUID("11111111-1111-1111-1111-111111111111"),
            target_id="TARGET-1",
            left_observation_id=UUID("22222222-2222-2222-2222-222222222222"),
            right_observation_id=UUID("33333333-3333-3333-3333-333333333333"),
            classification_marking=ClearanceLevel.SECRET,
            distance_meters=1450.5,
            status="PENDING_MANUAL_REVIEW",
            conflict_reason="Coordinate disagreement",
            created_at=datetime.now(timezone.utc),
        )
    ]

    app = create_app(settings=make_settings(), repository=repo, enable_mqtt=False)
    with TestClient(app) as client:
        response = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(clearance=ClearanceLevel.SECRET),
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["target_id"] == "TARGET-1"
        assert body[0]["classification_marking"] == "SECRET"
        assert repo.last_conflict_clearance == ClearanceLevel.SECRET


def test_pending_conflicts_returns_403_when_repository_denies_actor():
    app = create_app(settings=make_settings(), repository=DenyRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        response = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(clearance=ClearanceLevel.TOP_SECRET),
        )
        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()


def test_pending_conflicts_rejects_missing_actor_identity_state():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    request = make_request(app, "/v1/conflicts/pending")
    request.state.user_clearance = ClearanceLevel.TOP_SECRET
    endpoint = get_route_endpoint(app, "/v1/conflicts/pending")

    with pytest.raises(HTTPException, match="Missing validated actor identity"):
        asyncio.run(endpoint(request, limit=10))


def test_pending_conflicts_requires_authenticated_claims():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        response = client.get("/v1/conflicts/pending?limit=10")
        assert response.status_code == 401
        assert AUTH_CLAIMS_HEADER in response.json()["detail"]


def test_rejects_tampered_auth_signature():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        headers = make_auth_headers(clearance=ClearanceLevel.TOP_SECRET)
        headers[AUTH_SIGNATURE_HEADER] = "0" * 64
        response = client.get("/v1/conflicts/pending?limit=10", headers=headers)
        assert response.status_code == 401
        assert "signature" in response.json()["detail"].lower()


def test_rejects_stale_auth_claims_timestamp():
    app = create_app(
        settings=make_settings(auth_max_skew_seconds=5),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with TestClient(app) as client:
        headers = make_auth_headers(
            clearance=ClearanceLevel.TOP_SECRET,
            issued_at=int(time.time()) - 60,
        )
        response = client.get("/v1/conflicts/pending?limit=10", headers=headers)
        assert response.status_code == 401
        assert "timestamp" in response.json()["detail"].lower()


def test_rejects_replayed_auth_claims_jti():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        headers = make_auth_headers(
            clearance=ClearanceLevel.TOP_SECRET,
            jti="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        first = client.get("/v1/conflicts/pending?limit=10", headers=headers)
        second = client.get("/v1/conflicts/pending?limit=10", headers=headers)
        assert first.status_code == 200
        assert second.status_code == 401
        assert "replay" in second.json()["detail"].lower()


def test_accepts_secondary_rotated_shared_secret():
    app = create_app(
        settings=make_settings(auth_shared_secret_secondary=TEST_AUTH_SECRET_SECONDARY),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with TestClient(app) as client:
        response = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                shared_secret=TEST_AUTH_SECRET_SECONDARY,
            ),
        )
        assert response.status_code == 200


def test_rejects_wrong_auth_claim_audience():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)
    with TestClient(app) as client:
        response = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                audience="other-service",
            ),
        )
        assert response.status_code == 400
        assert "audience" in response.json()["detail"].lower()


def test_rejects_oversized_auth_claim_header():
    app = create_app(
        settings=make_settings(auth_max_claims_bytes=256),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    oversized_claims = "A" * 1024
    with TestClient(app) as client:
        response = client.get(
            "/v1/conflicts/pending?limit=10",
            headers={
                AUTH_CLAIMS_HEADER: oversized_claims,
                AUTH_SIGNATURE_HEADER: "0" * 64,
            },
        )
        assert response.status_code == 400
        assert "maximum allowed size" in response.json()["detail"].lower()


def test_rate_limiter_enforces_v1_limits():
    actor_user_id = str(uuid4())
    app = create_app(
        settings=make_settings(
            api_rate_limit_requests=1,
            api_rate_limit_window_seconds=60,
        ),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with TestClient(app) as client:
        first = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=actor_user_id,
            ),
        )
        second = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=actor_user_id,
            ),
        )
        assert first.status_code == 200
        assert second.status_code == 429
        assert "rate limit" in second.json()["detail"].lower()


def test_rate_limiter_is_scoped_per_actor_identity():
    first_actor_user_id = str(uuid4())
    second_actor_user_id = str(uuid4())
    app = create_app(
        settings=make_settings(
            api_rate_limit_requests=1,
            api_rate_limit_window_seconds=60,
        ),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with TestClient(app) as client:
        first_actor = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=first_actor_user_id,
            ),
        )
        second_actor = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=second_actor_user_id,
            ),
        )
        assert first_actor.status_code == 200
        assert second_actor.status_code == 200


def test_rate_limiter_can_be_disabled():
    actor_user_id = str(uuid4())
    app = create_app(
        settings=make_settings(
            api_rate_limit_enabled=False,
            api_rate_limit_requests=1,
            api_rate_limit_window_seconds=60,
        ),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with TestClient(app) as client:
        first = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=actor_user_id,
            ),
        )
        second = client.get(
            "/v1/conflicts/pending?limit=10",
            headers=make_auth_headers(
                clearance=ClearanceLevel.TOP_SECRET,
                user_id=actor_user_id,
            ),
        )
        assert first.status_code == 200
        assert second.status_code == 200


def test_startup_fails_when_persistent_rate_limiter_required_without_pool():
    app = create_app(
        settings=make_settings(
            api_rate_limit_enabled=True,
            api_rate_limit_require_persistent=True,
        ),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with pytest.raises(RuntimeError, match="Persistent API rate limiter is required"):
        with TestClient(app):
            pass


def test_startup_fails_without_persistent_replay_guard_when_required():
    app = create_app(
        settings=make_settings(auth_require_persistent_replay_guard=True),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with pytest.raises(RuntimeError, match="Persistent replay guard is required"):
        with TestClient(app):
            pass


def test_startup_rejects_inmemory_replay_guard_when_persistent_required():
    app = create_app(
        settings=make_settings(auth_require_persistent_replay_guard=True),
        repository=FakeRepository(),
        enable_mqtt=False,
        replay_guard=InMemoryReplayGuard(ttl_seconds=300),
    )
    with pytest.raises(RuntimeError, match="InMemoryReplayGuard is not allowed"):
        with TestClient(app):
            pass


def test_startup_fails_when_no_auth_shared_secret_configured():
    app = create_app(
        settings=make_settings(
            auth_shared_secret_primary="",
            auth_shared_secret_secondary="",
        ),
        repository=FakeRepository(),
        enable_mqtt=False,
    )
    with pytest.raises(RuntimeError, match="At least one authentication shared secret"):
        with TestClient(app):
            pass


def test_startup_fails_when_mqtt_tls_required_but_disabled():
    app = create_app(
        settings=make_settings(
            mqtt_require_tls=True,
            mqtt_tls_enabled=False,
            mqtt_require_auth=True,
            mqtt_username="service-user",
            mqtt_password="service-pass",
        ),
        repository=FakeRepository(),
        enable_mqtt=True,
    )
    with pytest.raises(RuntimeError, match="MQTT secure transport is required"):
        with TestClient(app):
            pass


def test_startup_fails_when_mqtt_auth_required_but_missing_credentials():
    app = create_app(
        settings=make_settings(
            mqtt_require_tls=False,
            mqtt_tls_enabled=False,
            mqtt_require_auth=True,
            mqtt_username="",
            mqtt_password="",
        ),
        repository=FakeRepository(),
        enable_mqtt=True,
    )
    with pytest.raises(RuntimeError, match="MQTT authentication is required"):
        with TestClient(app):
            pass


def test_signed_claims_drive_identity_and_legacy_headers_are_ignored():
    repo = FakeRepository()
    actor_user_id = str(uuid4())
    app = create_app(settings=make_settings(), repository=repo, enable_mqtt=False)

    with TestClient(app) as client:
        headers = make_auth_headers(
            clearance=ClearanceLevel.TOP_SECRET,
            user_id=actor_user_id,
        )
        headers["X-User-Id"] = str(uuid4())
        headers["X-User-Clearance"] = ClearanceLevel.UNCLASSIFIED.value
        response = client.post(
            "/v1/ingest/hook",
            headers=headers,
            json=make_payload(classification="SECRET"),
        )
        assert response.status_code == 200
        assert len(repo.calls) == 1
        assert repo.calls[0]["actor_user_id"] == actor_user_id
        assert repo.calls[0]["actor_clearance"] == ClearanceLevel.TOP_SECRET


def test_lifespan_initializes_repository_and_closes_pool(monkeypatch):
    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake_pool = FakePool()
    calls: list[dict[str, Any]] = []

    async def fake_create_pool(**kwargs):
        calls.append(kwargs)
        return fake_pool

    monkeypatch.setattr(
        "backend.intelligence_fusion_service.asyncpg.create_pool",
        fake_create_pool,
    )
    app = create_app(
        settings=make_settings(
            pg_dsn="postgresql://test/test",
            max_ingest_bytes=1024,
            api_rate_limit_enabled=False,
        ),
        repository=None,
        enable_mqtt=False,
        replay_guard=InMemoryReplayGuard(ttl_seconds=300),
    )

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert isinstance(app.state.repository, PostgresFusionRepository)
        assert app.state.pool is fake_pool

    assert app.state.stop_event.is_set()
    assert fake_pool.closed is True
    assert calls and calls[0]["dsn"] == "postgresql://test/test"


def test_lifespan_skips_pool_creation_when_repository_is_injected(monkeypatch):
    async def fail_create_pool(**kwargs):
        raise AssertionError("create_pool should not be called when repository is injected.")

    monkeypatch.setattr(
        "backend.intelligence_fusion_service.asyncpg.create_pool",
        fail_create_pool,
    )
    repo = FakeRepository()
    app = create_app(settings=make_settings(), repository=repo, enable_mqtt=False)

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert app.state.repository is repo
        assert app.state.pool is None

    assert app.state.stop_event.is_set()


def test_lifespan_respects_settings_mqtt_enabled(monkeypatch):
    def fail_create_task(_coro):
        raise AssertionError("MQTT worker should not be created when MQTT is disabled.")

    monkeypatch.setattr("backend.intelligence_fusion_service.asyncio.create_task", fail_create_task)
    repo = FakeRepository()
    app = create_app(settings=make_settings(mqtt_enabled=False), repository=repo)

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert app.state.repository is repo

    assert app.state.stop_event.is_set()


def test_metrics_endpoint_exposes_prometheus_metrics_and_request_id():
    app = create_app(settings=make_settings(), repository=FakeRepository(), enable_mqtt=False)

    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.headers["X-Request-ID"]

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "shakti_http_requests_total" in metrics.text
        assert "shakti_http_request_duration_seconds" in metrics.text
        assert "shakti_db_operations_total" in metrics.text


def test_json_log_formatter_emits_structured_payload():
    formatter = JsonLogFormatter()
    record = logging.makeLogRecord(
        {
            "name": "shakti.intelligence_fusion",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "request_completed",
            "request_id": "req-123",
            "status_code": 200,
        }
    )

    payload = json.loads(formatter.format(record))
    assert payload["message"] == "request_completed"
    assert payload["request_id"] == "req-123"
    assert payload["status_code"] == 200
    assert payload["level"] == "INFO"


def test_settings_rejects_invalid_mqtt_service_user_id():
    with pytest.raises(ValueError, match="actor_user_id must be a valid UUID"):
        Settings(mqtt_service_user_id="not-a-uuid")


def test_settings_rejects_invalid_auth_max_skew_seconds():
    with pytest.raises(ValueError, match="AUTH_MAX_SKEW_SECONDS must be a positive integer"):
        Settings(auth_max_skew_seconds=0)


def test_settings_rejects_invalid_auth_replay_ttl_seconds():
    with pytest.raises(ValueError, match="AUTH_REPLAY_TTL_SECONDS must be a positive integer"):
        Settings(auth_replay_ttl_seconds=0)


def test_settings_rejects_invalid_auth_max_claims_bytes():
    with pytest.raises(ValueError, match="AUTH_MAX_CLAIMS_BYTES must be at least 256 bytes"):
        Settings(auth_max_claims_bytes=255)


def test_settings_rejects_invalid_api_rate_limit_requests():
    with pytest.raises(ValueError, match="API_RATE_LIMIT_REQUESTS must be a positive integer"):
        Settings(api_rate_limit_requests=0)


def test_settings_rejects_invalid_api_rate_limit_window_seconds():
    with pytest.raises(
        ValueError, match="API_RATE_LIMIT_WINDOW_SECONDS must be a positive integer"
    ):
        Settings(api_rate_limit_window_seconds=0)


def test_settings_rejects_invalid_mqtt_tls_reload_check_seconds():
    with pytest.raises(
        ValueError, match="MQTT_TLS_RELOAD_CHECK_SECONDS must be a positive integer"
    ):
        Settings(mqtt_tls_reload_check_seconds=0)


def test_settings_rejects_partial_mqtt_client_cert_configuration():
    with pytest.raises(
        ValueError, match="MQTT_TLS_CERT_FILE and MQTT_TLS_KEY_FILE must be provided together"
    ):
        Settings(mqtt_tls_cert_file="/tmp/client.crt", mqtt_tls_key_file="")


def test_settings_rejects_invalid_log_level():
    with pytest.raises(ValueError, match="LOG_LEVEL must be a valid Python logging level"):
        Settings(log_level="LOUD")


def test_settings_rejects_invalid_db_slow_query_threshold():
    with pytest.raises(ValueError, match="DB_SLOW_QUERY_THRESHOLD_MS must be a positive number"):
        Settings(db_slow_query_threshold_ms=0)
