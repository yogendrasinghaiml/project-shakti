from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import ssl
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

try:
    from asyncio_mqtt import Client as MQTTClient
    from asyncio_mqtt import MqttError
except Exception:  # pragma: no cover - optional dependency during local scaffolding
    MQTTClient = None

    class MqttError(Exception):
        pass


logger = logging.getLogger("shakti.intelligence_fusion")
logging.basicConfig(level=logging.INFO)


class ClearanceLevel(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"
    TOP_SECRET = "TOP_SECRET"


class SourceType(str, Enum):
    REST_HOOK = "REST_HOOK"
    MQTT_SENSOR = "MQTT_SENSOR"


CLEARANCE_RANK: dict[ClearanceLevel, int] = {
    ClearanceLevel.UNCLASSIFIED: 10,
    ClearanceLevel.CONFIDENTIAL: 20,
    ClearanceLevel.SECRET: 30,
    ClearanceLevel.TOP_SECRET: 40,
}
SYSTEM_ACTOR_UUID = "00000000-0000-0000-0000-000000000000"
AUTH_CLAIMS_HEADER = "X-Auth-Claims"
AUTH_SIGNATURE_HEADER = "X-Auth-Signature"
AUTH_DEFAULT_AUDIENCE = "shakti-intelligence-fusion"


def clearance_allows(
    user_clearance: ClearanceLevel, data_classification: ClearanceLevel
) -> bool:
    return CLEARANCE_RANK[user_clearance] >= CLEARANCE_RANK[data_classification]


def max_clearance_level(
    left: ClearanceLevel, right: ClearanceLevel
) -> ClearanceLevel:
    if CLEARANCE_RANK[left] >= CLEARANCE_RANK[right]:
        return left
    return right


def normalize_actor_user_id(actor_user_id: str) -> str:
    try:
        return str(UUID(actor_user_id))
    except ValueError as exc:
        raise ValueError("actor_user_id must be a valid UUID.") from exc


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius_m = 6371000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * radius_m * asin(sqrt(a))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def sign_auth_claims(claims_b64: str, shared_secret: str) -> str:
    if not shared_secret:
        raise ValueError("AUTH_SHARED_SECRET must be configured to sign auth claims.")
    return hmac.new(
        shared_secret.encode("utf-8"),
        claims_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def build_auth_claim_headers(
    *,
    user_id: str,
    clearance: ClearanceLevel,
    shared_secret: str,
    issued_at: int | None = None,
    jti: str | None = None,
    audience: str = AUTH_DEFAULT_AUDIENCE,
) -> dict[str, str]:
    normalized_user_id = normalize_actor_user_id(user_id)
    normalized_jti = str(UUID(jti)) if jti else str(uuid4())
    payload = {
        "user_id": normalized_user_id,
        "clearance": clearance.value,
        "iat": int(time.time()) if issued_at is None else int(issued_at),
        "jti": normalized_jti,
        "aud": audience,
    }
    claims_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    claims_b64 = _b64url_encode(claims_json.encode("utf-8"))
    signature = sign_auth_claims(claims_b64, shared_secret)
    return {
        AUTH_CLAIMS_HEADER: claims_b64,
        AUTH_SIGNATURE_HEADER: signature,
    }


def verify_auth_claims(
    *,
    claims_b64: str,
    signature: str,
    shared_secrets: tuple[str, ...],
    max_skew_seconds: int,
    expected_audience: str,
    max_claims_bytes: int,
    now_ts: int | None = None,
) -> tuple[str, ClearanceLevel, str]:
    if not shared_secrets:
        raise ValueError("No active authentication secrets are configured.")
    if len(claims_b64) > max_claims_bytes:
        raise ValueError("Authentication claims header exceeds maximum allowed size.")
    if len(signature) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in signature):
        raise ValueError("Invalid authentication signature format.")

    signature_valid = False
    for shared_secret in shared_secrets:
        expected_signature = sign_auth_claims(claims_b64, shared_secret)
        if hmac.compare_digest(signature, expected_signature):
            signature_valid = True
            break
    if not signature_valid:
        raise ValueError("Invalid authentication signature.")

    try:
        claims_raw_bytes = _b64url_decode(claims_b64)
        if len(claims_raw_bytes) > max_claims_bytes:
            raise ValueError("Authentication claims payload exceeds maximum allowed size.")
        claims_raw = claims_raw_bytes.decode("utf-8")
        claims = json.loads(claims_raw)
    except (ValueError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Invalid authentication claims format.") from exc

    if not isinstance(claims, dict):
        raise ValueError("Invalid authentication claims payload.")

    try:
        actor_user_id = normalize_actor_user_id(str(claims["user_id"]))
        user_clearance = ClearanceLevel(str(claims["clearance"]))
        issued_at = int(claims["iat"])
        jti = str(UUID(str(claims["jti"])))
        audience = str(claims["aud"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Missing or invalid authentication claims fields.") from exc
    if audience != expected_audience:
        raise ValueError("Invalid authentication audience.")

    current_ts = int(time.time()) if now_ts is None else now_ts
    if abs(current_ts - issued_at) > max_skew_seconds:
        raise ValueError("Authentication claims timestamp outside allowed skew.")

    return actor_user_id, user_clearance, jti


class ReplayGuard(Protocol):
    async def mark_jti_seen(self, jti: str) -> bool:
        ...

    async def close(self) -> None:
        ...


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool:
        ...

    async def close(self) -> None:
        ...


class InMemoryReplayGuard:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, int] = {}

    def _prune(self, now_ts: int) -> None:
        expired = [jti for jti, expiry_ts in self._entries.items() if expiry_ts <= now_ts]
        for jti in expired:
            self._entries.pop(jti, None)

    async def mark_jti_seen(self, jti: str) -> bool:
        now_ts = int(time.time())
        self._prune(now_ts)
        if jti in self._entries:
            return False
        self._entries[jti] = now_ts + self.ttl_seconds
        return True

    async def close(self) -> None:
        self._entries.clear()


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._entries: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        async with self._lock:
            existing = self._entries.get(key, [])
            pruned = [ts for ts in existing if ts > window_start]
            if len(pruned) >= self.max_requests:
                self._entries[key] = pruned
                return False
            pruned.append(now)
            self._entries[key] = pruned
            return True

    async def close(self) -> None:
        async with self._lock:
            self._entries.clear()


class PostgresRateLimiter:
    def __init__(self, pool: asyncpg.Pool, max_requests: int, window_seconds: int) -> None:
        self.pool = pool
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def ensure_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_rate_limit_guard (
                  principal_key TEXT NOT NULL,
                  window_start TIMESTAMPTZ NOT NULL,
                  request_count INTEGER NOT NULL CHECK (request_count >= 0),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  PRIMARY KEY (principal_key, window_start)
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_rate_limit_guard_window_start
                ON api_rate_limit_guard (window_start)
                """
            )

    async def allow(self, key: str) -> bool:
        now_ts = time.time()
        current_window_ts = int(now_ts // self.window_seconds) * self.window_seconds
        window_start = datetime.fromtimestamp(current_window_ts, tz=timezone.utc)
        expire_before = window_start - timedelta(seconds=self.window_seconds)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM api_rate_limit_guard WHERE window_start < $1",
                    expire_before,
                )
                row = await conn.fetchrow(
                    """
                    SELECT request_count
                    FROM api_rate_limit_guard
                    WHERE principal_key = $1
                      AND window_start = $2
                    FOR UPDATE
                    """,
                    key,
                    window_start,
                )
                if row is None:
                    await conn.execute(
                        """
                        INSERT INTO api_rate_limit_guard (
                          principal_key,
                          window_start,
                          request_count
                        )
                        VALUES ($1, $2, 1)
                        """,
                        key,
                        window_start,
                    )
                    return True

                request_count = int(row["request_count"])
                if request_count >= self.max_requests:
                    return False

                await conn.execute(
                    """
                    UPDATE api_rate_limit_guard
                    SET request_count = request_count + 1,
                        updated_at = NOW()
                    WHERE principal_key = $1
                      AND window_start = $2
                    """,
                    key,
                    window_start,
                )
                return True

    async def close(self) -> None:
        return None


class PostgresReplayGuard:
    def __init__(self, pool: asyncpg.Pool, ttl_seconds: int) -> None:
        self.pool = pool
        self.ttl_seconds = ttl_seconds

    async def ensure_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_claim_replay_guard (
                  jti UUID PRIMARY KEY,
                  expires_at TIMESTAMPTZ NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_auth_claim_replay_guard_expires_at
                ON auth_claim_replay_guard (expires_at)
                """
            )

    async def mark_jti_seen(self, jti: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM auth_claim_replay_guard WHERE expires_at <= NOW()"
                )
                inserted = await conn.fetchval(
                    """
                    INSERT INTO auth_claim_replay_guard (jti, expires_at)
                    VALUES ($1::uuid, $2)
                    ON CONFLICT (jti) DO NOTHING
                    RETURNING 1
                    """,
                    jti,
                    datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
                )
                return inserted == 1

    async def close(self) -> None:
        return None


def load_shared_secrets_from_file(path: str) -> tuple[str, str]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("AUTH_SHARED_SECRETS_FILE is unreadable or invalid JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError("AUTH_SHARED_SECRETS_FILE must contain a JSON object.")

    primary_raw = data.get("primary", "")
    secondary_raw = data.get("secondary", "")
    primary = str(primary_raw).strip() if primary_raw is not None else ""
    secondary = str(secondary_raw).strip() if secondary_raw is not None else ""
    return primary, secondary


class Coordinate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class IntelObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    source_id: str = Field(min_length=1, max_length=128)
    source_type: SourceType
    observed_at: AwareDatetime
    classification_marking: ClearanceLevel
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    coordinate: Coordinate
    unit_type: str = Field(default="UNKNOWN", min_length=3, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    sector_code: str | None = Field(default=None, max_length=64)


class IngestResult(BaseModel):
    observation_id: UUID
    conflict_flagged: bool
    conflict_id: UUID | None = None
    message: str


class ConflictOut(BaseModel):
    conflict_id: UUID
    target_id: str
    left_observation_id: UUID
    right_observation_id: UUID
    classification_marking: ClearanceLevel
    distance_meters: float
    status: str
    conflict_reason: str
    created_at: datetime


@dataclass
class Settings:
    pg_dsn: str = os.getenv(
        "PG_DSN",
        "postgresql://shakti:shakti@127.0.0.1:5432/shakti",
    )
    mqtt_host: str = os.getenv("MQTT_HOST", "127.0.0.1")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_topic: str = os.getenv("MQTT_TOPIC", "shakti/intel/#")
    mqtt_username: str = os.getenv("MQTT_USERNAME", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_require_auth: bool = (
        os.getenv("MQTT_REQUIRE_AUTH", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    mqtt_tls_enabled: bool = (
        os.getenv("MQTT_TLS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    mqtt_require_tls: bool = (
        os.getenv("MQTT_REQUIRE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    mqtt_tls_reload_check_seconds: int = int(
        os.getenv("MQTT_TLS_RELOAD_CHECK_SECONDS", "15")
    )
    mqtt_tls_ca_file: str = os.getenv("MQTT_TLS_CA_FILE", "")
    mqtt_tls_cert_file: str = os.getenv("MQTT_TLS_CERT_FILE", "")
    mqtt_tls_key_file: str = os.getenv("MQTT_TLS_KEY_FILE", "")
    conflict_threshold_m: float = float(os.getenv("CONFLICT_THRESHOLD_M", "250.0"))
    max_ingest_bytes: int = int(os.getenv("MAX_INGEST_BYTES", "65536"))
    api_rate_limit_enabled: bool = (
        os.getenv("API_RATE_LIMIT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    api_rate_limit_require_persistent: bool = (
        os.getenv("API_RATE_LIMIT_REQUIRE_PERSISTENT", "true").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    api_rate_limit_requests: int = int(os.getenv("API_RATE_LIMIT_REQUESTS", "120"))
    api_rate_limit_window_seconds: int = int(os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60"))
    mqtt_service_user_id: str = os.getenv(
        "MQTT_SERVICE_USER_ID", "00000000-0000-0000-0000-000000000000"
    )
    mqtt_service_clearance: ClearanceLevel = ClearanceLevel(
        os.getenv("MQTT_SERVICE_CLEARANCE", "TOP_SECRET")
    )
    auth_shared_secret_primary: str = os.getenv(
        "AUTH_SHARED_SECRET_PRIMARY",
        os.getenv("AUTH_SHARED_SECRET", ""),
    )
    auth_shared_secret_secondary: str = os.getenv("AUTH_SHARED_SECRET_SECONDARY", "")
    auth_shared_secrets_file: str = os.getenv("AUTH_SHARED_SECRETS_FILE", "")
    auth_expected_audience: str = os.getenv(
        "AUTH_EXPECTED_AUDIENCE",
        AUTH_DEFAULT_AUDIENCE,
    )
    auth_max_skew_seconds: int = int(os.getenv("AUTH_MAX_SKEW_SECONDS", "300"))
    auth_replay_ttl_seconds: int = int(os.getenv("AUTH_REPLAY_TTL_SECONDS", "900"))
    auth_max_claims_bytes: int = int(os.getenv("AUTH_MAX_CLAIMS_BYTES", "4096"))
    auth_require_persistent_replay_guard: bool = (
        os.getenv("AUTH_REQUIRE_PERSISTENT_REPLAY_GUARD", "true").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    auth_active_shared_secrets: tuple[str, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        if self.max_ingest_bytes < 1:
            raise ValueError("MAX_INGEST_BYTES must be a positive integer.")
        if self.api_rate_limit_requests < 1:
            raise ValueError("API_RATE_LIMIT_REQUESTS must be a positive integer.")
        if self.api_rate_limit_window_seconds < 1:
            raise ValueError("API_RATE_LIMIT_WINDOW_SECONDS must be a positive integer.")
        if self.mqtt_tls_reload_check_seconds < 1:
            raise ValueError("MQTT_TLS_RELOAD_CHECK_SECONDS must be a positive integer.")
        if self.auth_max_skew_seconds < 1:
            raise ValueError("AUTH_MAX_SKEW_SECONDS must be a positive integer.")
        if self.auth_replay_ttl_seconds < 1:
            raise ValueError("AUTH_REPLAY_TTL_SECONDS must be a positive integer.")
        if self.auth_max_claims_bytes < 256:
            raise ValueError("AUTH_MAX_CLAIMS_BYTES must be at least 256 bytes.")
        if not self.auth_expected_audience.strip():
            raise ValueError("AUTH_EXPECTED_AUDIENCE must not be empty.")
        if bool(self.mqtt_tls_cert_file.strip()) != bool(self.mqtt_tls_key_file.strip()):
            raise ValueError(
                "MQTT_TLS_CERT_FILE and MQTT_TLS_KEY_FILE must be provided together."
            )

        if self.auth_shared_secrets_file:
            file_primary, file_secondary = load_shared_secrets_from_file(
                self.auth_shared_secrets_file
            )
            if file_primary:
                self.auth_shared_secret_primary = file_primary
            if file_secondary:
                self.auth_shared_secret_secondary = file_secondary

        active_secrets = []
        for secret in (self.auth_shared_secret_primary, self.auth_shared_secret_secondary):
            normalized = secret.strip()
            if normalized and normalized not in active_secrets:
                active_secrets.append(normalized)
        self.auth_active_shared_secrets = tuple(active_secrets)

        self.mqtt_service_user_id = normalize_actor_user_id(self.mqtt_service_user_id)


class FusionRepository(Protocol):
    async def ingest_observation(
        self,
        observation: IntelObservationIn,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
    ) -> IngestResult:
        ...

    async def pending_conflicts_for_clearance(
        self,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
        limit: int = 100,
    ) -> list[ConflictOut]:
        ...


class PostgresFusionRepository:
    def __init__(self, pool: asyncpg.Pool, conflict_threshold_m: float = 250.0) -> None:
        self.pool = pool
        self.conflict_threshold_m = conflict_threshold_m

    async def _validate_actor(
        self,
        conn: asyncpg.Connection,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
    ) -> str:
        actor_uuid = normalize_actor_user_id(actor_user_id)
        actor_row = await conn.fetchrow(
            """
            SELECT clearance_level, is_active
            FROM users
            WHERE user_id = $1
            """,
            actor_uuid,
        )
        if actor_row is None:
            raise PermissionError("Authenticated actor is not provisioned.")

        if not bool(actor_row["is_active"]):
            raise PermissionError("Authenticated actor is inactive.")

        provisioned_clearance = ClearanceLevel(str(actor_row["clearance_level"]))
        if CLEARANCE_RANK[actor_clearance] > CLEARANCE_RANK[provisioned_clearance]:
            raise PermissionError(
                "Authenticated actor clearance claim exceeds provisioned clearance."
            )
        return actor_uuid

    async def ingest_observation(
        self,
        observation: IntelObservationIn,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
    ) -> IngestResult:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                actor_uuid = await self._validate_actor(
                    conn=conn,
                    actor_user_id=actor_user_id,
                    actor_clearance=actor_clearance,
                )
                await conn.execute(
                    "SELECT set_config('app.user_clearance', $1, true)",
                    actor_clearance.value,
                )
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    observation.target_id,
                )

                await conn.execute(
                    """
                    INSERT INTO targets (target_id, unit_type, canonical_classification, metadata, last_modified_by)
                    VALUES ($1, $2, $3, '{}'::jsonb, $4)
                    ON CONFLICT (target_id) DO UPDATE SET
                      unit_type = EXCLUDED.unit_type,
                      canonical_classification = CASE
                        WHEN clearance_to_rank(targets.canonical_classification) >= clearance_to_rank(EXCLUDED.canonical_classification)
                        THEN targets.canonical_classification
                        ELSE EXCLUDED.canonical_classification
                      END,
                      last_modified_by = EXCLUDED.last_modified_by
                    """,
                    observation.target_id,
                    observation.unit_type,
                    observation.classification_marking.value,
                    actor_uuid,
                )

                previous = await conn.fetchrow(
                    """
                    SELECT
                      observation_id,
                      source_id,
                      classification_marking,
                      ST_Y(location::geometry) AS lat,
                      ST_X(location::geometry) AS lon
                    FROM intel_observations
                    WHERE target_id = $1
                      AND source_id <> $2
                    ORDER BY observed_at DESC
                    LIMIT 1
                    """,
                    observation.target_id,
                    observation.source_id,
                )

                observation_id = await conn.fetchval(
                    """
                    INSERT INTO intel_observations (
                      target_id,
                      source_id,
                      source_type,
                      classification_marking,
                      confidence,
                      observed_at,
                      location,
                      payload,
                      last_modified_by
                    )
                    VALUES (
                      $1, $2, $3, $4, $5, $6,
                      ST_SetSRID(ST_MakePoint($7, $8), 4326),
                      $9::jsonb,
                      $10
                    )
                    RETURNING observation_id
                    """,
                    observation.target_id,
                    observation.source_id,
                    observation.source_type.value,
                    observation.classification_marking.value,
                    observation.confidence,
                    observation.observed_at,
                    observation.coordinate.lon,
                    observation.coordinate.lat,
                    json.dumps(observation.payload),
                    actor_uuid,
                )

                if previous is None:
                    return IngestResult(
                        observation_id=observation_id,
                        conflict_flagged=False,
                        message="Ingested observation with no prior conflicting source.",
                    )

                distance_m = haversine_distance_m(
                    lat1=float(previous["lat"]),
                    lon1=float(previous["lon"]),
                    lat2=observation.coordinate.lat,
                    lon2=observation.coordinate.lon,
                )

                if distance_m <= self.conflict_threshold_m:
                    return IngestResult(
                        observation_id=observation_id,
                        conflict_flagged=False,
                        message="Ingested observation. Coordinate agreement within threshold.",
                    )

                conflict_reason = (
                    "Coordinate disagreement detected for same target_id across sources. "
                    f"distance_m={distance_m:.3f}, threshold_m={self.conflict_threshold_m:.3f}"
                )
                previous_classification = ClearanceLevel(str(previous["classification_marking"]))
                conflict_classification = max_clearance_level(
                    previous_classification,
                    observation.classification_marking,
                )

                conflict_id = await conn.fetchval(
                    """
                    INSERT INTO coordinate_conflicts (
                      target_id,
                      left_observation_id,
                      right_observation_id,
                      distance_meters,
                      classification_marking,
                      status,
                      conflict_reason,
                      last_modified_by
                    )
                    VALUES ($1, $2, $3, $4, $5, 'PENDING_MANUAL_REVIEW', $6, $7)
                    RETURNING conflict_id
                    """,
                    observation.target_id,
                    previous["observation_id"],
                    observation_id,
                    distance_m,
                    conflict_classification.value,
                    conflict_reason,
                    actor_uuid,
                )

                return IngestResult(
                    observation_id=observation_id,
                    conflict_flagged=True,
                    conflict_id=conflict_id,
                    message="Conflict flagged for manual review.",
                )

    async def pending_conflicts_for_clearance(
        self,
        actor_user_id: str,
        actor_clearance: ClearanceLevel,
        limit: int = 100,
    ) -> list[ConflictOut]:
        safe_limit = max(1, min(limit, 500))
        async with self.pool.acquire() as conn:
            await self._validate_actor(
                conn=conn,
                actor_user_id=actor_user_id,
                actor_clearance=actor_clearance,
            )
            await conn.execute(
                "SELECT set_config('app.user_clearance', $1, true)",
                actor_clearance.value,
            )
            rows = await conn.fetch(
                """
                SELECT
                  conflict_id,
                  target_id,
                  left_observation_id,
                  right_observation_id,
                  classification_marking,
                  distance_meters,
                  status,
                  conflict_reason,
                  created_at
                FROM coordinate_conflicts
                WHERE status = 'PENDING_MANUAL_REVIEW'
                ORDER BY created_at DESC
                LIMIT $1
                """,
                safe_limit,
            )
            return [ConflictOut(**dict(row)) for row in rows]


def create_app(
    settings: Settings | None = None,
    repository: FusionRepository | None = None,
    enable_mqtt: bool = True,
    replay_guard: ReplayGuard | None = None,
) -> FastAPI:
    cfg = settings or Settings()

    def build_mqtt_tls_context() -> ssl.SSLContext | None:
        if not cfg.mqtt_tls_enabled:
            return None
        try:
            tls_context = ssl.create_default_context(
                cafile=cfg.mqtt_tls_ca_file or None
            )
            if cfg.mqtt_tls_cert_file and cfg.mqtt_tls_key_file:
                tls_context.load_cert_chain(
                    certfile=cfg.mqtt_tls_cert_file,
                    keyfile=cfg.mqtt_tls_key_file,
                )
            return tls_context
        except Exception as exc:  # pragma: no cover - environment-dependent filesystem/TLS errors
            raise RuntimeError(f"Failed to initialize MQTT TLS context: {exc}") from exc

    def mqtt_tls_material_fingerprint() -> str:
        if not cfg.mqtt_tls_enabled:
            return ""
        digest = hashlib.sha256()
        for file_path in (
            cfg.mqtt_tls_ca_file,
            cfg.mqtt_tls_cert_file,
            cfg.mqtt_tls_key_file,
        ):
            normalized = file_path.strip()
            if not normalized:
                continue
            try:
                stats = Path(normalized).stat()
            except OSError as exc:
                raise RuntimeError(
                    f"Failed to read MQTT TLS material metadata for {normalized}: {exc}"
                ) from exc
            digest.update(normalized.encode("utf-8"))
            digest.update(str(stats.st_size).encode("ascii"))
            digest.update(str(stats.st_mtime_ns).encode("ascii"))
        return digest.hexdigest()

    async def mqtt_ingest_worker(app: FastAPI) -> None:
        if MQTTClient is None:
            logger.warning(
                "MQTT worker disabled: asyncio-mqtt is not installed in this environment."
            )
            return

        mqtt_kwargs: dict[str, Any] = {}
        if cfg.mqtt_username:
            mqtt_kwargs["username"] = cfg.mqtt_username
        if cfg.mqtt_password:
            mqtt_kwargs["password"] = cfg.mqtt_password

        while not app.state.stop_event.is_set():
            try:
                tls_fingerprint = mqtt_tls_material_fingerprint()
                tls_context = build_mqtt_tls_context()
                connect_kwargs = dict(mqtt_kwargs)
                if tls_context is not None:
                    connect_kwargs["tls_context"] = tls_context
                async with MQTTClient(cfg.mqtt_host, cfg.mqtt_port, **connect_kwargs) as client:
                    async with client.filtered_messages(cfg.mqtt_topic) as messages:
                        await client.subscribe(cfg.mqtt_topic)
                        logger.info(
                            "MQTT worker connected to %s:%s topic=%s",
                            cfg.mqtt_host,
                            cfg.mqtt_port,
                            cfg.mqtt_topic,
                        )
                        messages_iter = messages.__aiter__()
                        while not app.state.stop_event.is_set():
                            try:
                                message = await asyncio.wait_for(
                                    messages_iter.__anext__(),
                                    timeout=cfg.mqtt_tls_reload_check_seconds,
                                )
                            except asyncio.TimeoutError:
                                if (
                                    cfg.mqtt_tls_enabled
                                    and mqtt_tls_material_fingerprint() != tls_fingerprint
                                ):
                                    logger.info(
                                        "MQTT TLS material changed; reconnecting to apply rotated certificates."
                                    )
                                    break
                                continue
                            except StopAsyncIteration:
                                break
                            if app.state.stop_event.is_set():
                                break
                            try:
                                payload = json.loads(message.payload.decode("utf-8"))
                                payload.setdefault("source_type", SourceType.MQTT_SENSOR.value)
                                observation = IntelObservationIn.model_validate(payload)
                                result = await app.state.repository.ingest_observation(
                                    observation=observation,
                                    actor_user_id=cfg.mqtt_service_user_id,
                                    actor_clearance=cfg.mqtt_service_clearance,
                                )
                                logger.info(
                                    "MQTT observation ingested. target_id=%s conflict=%s",
                                    observation.target_id,
                                    result.conflict_flagged,
                                )
                                if (
                                    cfg.mqtt_tls_enabled
                                    and mqtt_tls_material_fingerprint() != tls_fingerprint
                                ):
                                    logger.info(
                                        "MQTT TLS material changed during stream; reconnecting."
                                    )
                                    break
                            except (ValidationError, json.JSONDecodeError) as exc:
                                logger.error("MQTT payload validation failed: %s", exc)
                            except Exception as exc:  # pragma: no cover - runtime safety net
                                logger.exception("MQTT ingestion failed: %s", exc)
            except MqttError as exc:
                logger.warning("MQTT connection lost, retrying in 3s: %s", exc)
                await asyncio.sleep(3)
            except Exception as exc:  # pragma: no cover - runtime safety net
                logger.exception("MQTT worker runtime error, retrying in 3s: %s", exc)
                await asyncio.sleep(3)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = cfg
        app.state.repository = repository
        app.state.pool = None
        app.state.replay_guard = replay_guard
        app.state.rate_limiter = None
        app.state.stop_event = asyncio.Event()
        app.state.mqtt_task = None

        if app.state.repository is None:
            pool = await asyncpg.create_pool(
                dsn=cfg.pg_dsn,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            app.state.pool = pool
            app.state.repository = PostgresFusionRepository(
                pool=pool,
                conflict_threshold_m=cfg.conflict_threshold_m,
            )
            logger.info("Connected to PostgreSQL for Intelligence Fusion service.")

        if not cfg.auth_active_shared_secrets:
            raise RuntimeError(
                "At least one authentication shared secret must be configured "
                "(AUTH_SHARED_SECRET_PRIMARY or AUTH_SHARED_SECRET_SECONDARY)."
            )
        if cfg.api_rate_limit_enabled:
            if app.state.pool is not None:
                pg_rate_limiter = PostgresRateLimiter(
                    pool=app.state.pool,
                    max_requests=cfg.api_rate_limit_requests,
                    window_seconds=cfg.api_rate_limit_window_seconds,
                )
                await pg_rate_limiter.ensure_schema()
                app.state.rate_limiter = pg_rate_limiter
            else:
                if cfg.api_rate_limit_require_persistent:
                    raise RuntimeError(
                        "Persistent API rate limiter is required but no PostgreSQL pool is available."
                    )
                logger.warning(
                    "Using in-memory API rate limiter because no PostgreSQL pool is available."
                )
                app.state.rate_limiter = InMemoryRateLimiter(
                    max_requests=cfg.api_rate_limit_requests,
                    window_seconds=cfg.api_rate_limit_window_seconds,
                )
        if enable_mqtt:
            if cfg.mqtt_require_tls and not cfg.mqtt_tls_enabled:
                raise RuntimeError(
                    "MQTT secure transport is required but MQTT_TLS_ENABLED is false."
                )
            if cfg.mqtt_require_auth and (
                not cfg.mqtt_username.strip() or not cfg.mqtt_password.strip()
            ):
                raise RuntimeError(
                    "MQTT authentication is required but MQTT_USERNAME/MQTT_PASSWORD are not configured."
                )

        if cfg.auth_require_persistent_replay_guard and isinstance(
            app.state.replay_guard, InMemoryReplayGuard
        ):
            raise RuntimeError(
                "Persistent replay guard is required; InMemoryReplayGuard is not allowed."
            )

        if app.state.replay_guard is None:
            if app.state.pool is not None:
                pg_replay_guard = PostgresReplayGuard(
                    pool=app.state.pool,
                    ttl_seconds=cfg.auth_replay_ttl_seconds,
                )
                await pg_replay_guard.ensure_schema()
                app.state.replay_guard = pg_replay_guard
            else:
                if cfg.auth_require_persistent_replay_guard:
                    raise RuntimeError(
                        "Persistent replay guard is required but no PostgreSQL pool or "
                        "external replay_guard is available."
                    )
                logger.warning(
                    "Using in-memory replay guard because no PostgreSQL pool is available."
                )
                app.state.replay_guard = InMemoryReplayGuard(
                    ttl_seconds=cfg.auth_replay_ttl_seconds
                )

        if enable_mqtt:
            app.state.mqtt_task = asyncio.create_task(mqtt_ingest_worker(app))

        try:
            yield
        finally:
            app.state.stop_event.set()
            mqtt_task = app.state.mqtt_task
            if mqtt_task:
                mqtt_task.cancel()
                try:
                    await mqtt_task
                except asyncio.CancelledError:
                    pass

            pool = app.state.pool
            if pool:
                await pool.close()
            replay_guard_instance = app.state.replay_guard
            if replay_guard_instance:
                await replay_guard_instance.close()
            rate_limiter_instance = app.state.rate_limiter
            if rate_limiter_instance:
                await rate_limiter_instance.close()

    app = FastAPI(
        title="SHAKTI Intelligence Fusion Service",
        version="1.1.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.repository = repository
    app.state.pool = None
    app.state.replay_guard = replay_guard
    app.state.rate_limiter = None
    app.state.stop_event = asyncio.Event()
    app.state.mqtt_task = None

    def auth_error_response(status_code: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": detail})

    async def validate_gateway_identity(
        request: Request,
    ) -> tuple[str, ClearanceLevel, str] | JSONResponse:
        if not cfg.auth_active_shared_secrets:
            return auth_error_response(
                status_code=503,
                detail="No active authentication shared secrets are configured.",
            )

        claims_b64 = request.headers.get(AUTH_CLAIMS_HEADER)
        signature = request.headers.get(AUTH_SIGNATURE_HEADER)
        if not claims_b64 or not signature:
            return auth_error_response(
                status_code=401,
                detail=(
                    f"Missing {AUTH_CLAIMS_HEADER} or {AUTH_SIGNATURE_HEADER} header for "
                    "authenticated API access."
                ),
            )

        try:
            return verify_auth_claims(
                claims_b64=claims_b64,
                signature=signature,
                shared_secrets=cfg.auth_active_shared_secrets,
                max_skew_seconds=cfg.auth_max_skew_seconds,
                expected_audience=cfg.auth_expected_audience,
                max_claims_bytes=cfg.auth_max_claims_bytes,
            )
        except ValueError as exc:
            message = str(exc)
            if message in {
                "Invalid authentication signature.",
                "Authentication claims timestamp outside allowed skew.",
            }:
                return auth_error_response(status_code=401, detail=message)
            return auth_error_response(status_code=400, detail=message)

    async def read_body_with_limit(request: Request) -> bytes | JSONResponse:
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                declared_size = int(content_length_header)
            except ValueError:
                return auth_error_response(
                    status_code=400,
                    detail="Invalid Content-Length header.",
                )
            if declared_size < 0:
                return auth_error_response(
                    status_code=400,
                    detail="Invalid Content-Length header.",
                )
            if declared_size > cfg.max_ingest_bytes:
                return auth_error_response(
                    status_code=413,
                    detail=(
                        "Request body exceeds MAX_INGEST_BYTES security limit. "
                        f"max={cfg.max_ingest_bytes}"
                    ),
                )

        body_chunks: list[bytes] = []
        body_size = 0
        while True:
            message = await request._receive()  # noqa: SLF001 - bounded stream read for security
            if message["type"] == "http.disconnect":
                return auth_error_response(
                    status_code=400,
                    detail="Client disconnected before request body was fully received.",
                )
            if message["type"] != "http.request":
                continue

            chunk = message.get("body", b"")
            body_size += len(chunk)
            if body_size > cfg.max_ingest_bytes:
                return auth_error_response(
                    status_code=413,
                    detail=(
                        "Request body exceeds MAX_INGEST_BYTES security limit. "
                        f"max={cfg.max_ingest_bytes}"
                    ),
                )
            body_chunks.append(chunk)

            if not message.get("more_body", False):
                break

        raw_body = b"".join(body_chunks)
        request._body = raw_body  # noqa: SLF001 - preserve body for downstream parser
        return raw_body

    @app.middleware("http")
    async def clearance_middleware(request: Request, call_next):
        if request.url.path.startswith("/v1/"):
            identity = await validate_gateway_identity(request)
            if isinstance(identity, JSONResponse):
                return identity
            actor_user_id, user_clearance, jti = identity
            rate_limiter_instance = app.state.rate_limiter
            if rate_limiter_instance is not None:
                principal_key = f"user:{actor_user_id}"
                if not await rate_limiter_instance.allow(principal_key):
                    return auth_error_response(
                        status_code=429,
                        detail="Rate limit exceeded for API access.",
                    )
            replay_guard_instance = app.state.replay_guard
            if replay_guard_instance is None:
                return auth_error_response(
                    status_code=503,
                    detail="Replay protection is unavailable.",
                )
            if not await replay_guard_instance.mark_jti_seen(jti):
                return auth_error_response(
                    status_code=401,
                    detail="Authentication token replay detected.",
                )
            request.state.actor_user_id = actor_user_id
            request.state.user_clearance = user_clearance

            if request.method in {"POST", "PUT", "PATCH"} and request.url.path.startswith(
                "/v1/ingest"
            ):
                raw_body = await read_body_with_limit(request)
                if isinstance(raw_body, JSONResponse):
                    return raw_body
                if not raw_body:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "Request body is required."},
                    )
                if len(raw_body) > cfg.max_ingest_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                "Request body exceeds MAX_INGEST_BYTES security limit. "
                                f"max={cfg.max_ingest_bytes}"
                            )
                        },
                    )
                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                    data_classification = ClearanceLevel(payload["classification_marking"])
                except (ValueError, KeyError, json.JSONDecodeError):
                    return JSONResponse(
                        status_code=422,
                        content={"detail": "classification_marking must be present and valid."},
                    )

                if not clearance_allows(user_clearance, data_classification):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": (
                                "Insufficient clearance: "
                                f"{user_clearance.value} cannot ingest {data_classification.value} data."
                            )
                        },
                    )

        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

    @app.post("/v1/ingest/hook", response_model=IngestResult)
    async def ingest_hook(observation: IntelObservationIn, request: Request) -> IngestResult:
        if observation.source_type != SourceType.REST_HOOK:
            raise HTTPException(
                status_code=422,
                detail="REST hook endpoint only accepts source_type=REST_HOOK.",
            )

        user_clearance = getattr(request.state, "user_clearance", None)
        if user_clearance is None:
            raise HTTPException(status_code=401, detail="Missing validated user clearance.")
        actor_user_id = getattr(request.state, "actor_user_id", None)
        if actor_user_id is None:
            raise HTTPException(status_code=401, detail="Missing validated actor identity.")

        try:
            result = await app.state.repository.ingest_observation(
                observation=observation,
                actor_user_id=actor_user_id,
                actor_clearance=user_clearance,
            )
            return result
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/v1/conflicts/pending", response_model=list[ConflictOut])
    async def get_pending_conflicts(request: Request, limit: int = 100) -> list[ConflictOut]:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")

        user_clearance = getattr(request.state, "user_clearance", None)
        if user_clearance is None:
            raise HTTPException(status_code=401, detail="Missing validated user clearance.")
        actor_user_id = getattr(request.state, "actor_user_id", None)
        if actor_user_id is None:
            raise HTTPException(status_code=401, detail="Missing validated actor identity.")

        try:
            return await app.state.repository.pending_conflicts_for_clearance(
                actor_user_id=actor_user_id,
                actor_clearance=user_clearance,
                limit=limit,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return app


app = create_app()
