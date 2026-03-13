#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.intelligence_fusion_service import (
    ClearanceLevel,
    SYSTEM_ACTOR_UUID,
    build_auth_claim_headers,
)


def ensure_fields(payload: dict[str, Any], required: set[str], endpoint: str) -> None:
    missing = sorted(required.difference(payload.keys()))
    if missing:
        raise RuntimeError(f"{endpoint} missing fields: {', '.join(missing)}")


async def run_smoke(base_url: str, shared_secret: str, user_id: str) -> None:
    timeout = httpx.Timeout(8.0)

    def auth_headers() -> dict[str, str]:
        return build_auth_claim_headers(
            user_id=user_id,
            clearance=ClearanceLevel.TOP_SECRET,
            shared_secret=shared_secret,
        )

    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        health = await client.get("/healthz")
        health.raise_for_status()
        health_body = health.json()
        if not isinstance(health_body, dict):
            raise RuntimeError("/healthz returned non-object payload.")
        ensure_fields(health_body, {"status", "time"}, "/healthz")

        conflicts = await client.get("/v1/conflicts/pending?limit=10", headers=auth_headers())
        conflicts.raise_for_status()
        conflicts_body = conflicts.json()
        if not isinstance(conflicts_body, list):
            raise RuntimeError("/v1/conflicts/pending did not return a list.")
        if conflicts_body:
            if not isinstance(conflicts_body[0], dict):
                raise RuntimeError("/v1/conflicts/pending list item is not an object.")
            ensure_fields(
                conflicts_body[0],
                {
                    "conflict_id",
                    "target_id",
                    "classification_marking",
                    "distance_meters",
                    "status",
                    "created_at",
                },
                "/v1/conflicts/pending",
            )

        observations = await client.get("/v1/observations/recent?limit=10", headers=auth_headers())
        observations.raise_for_status()
        observations_body = observations.json()
        if not isinstance(observations_body, list):
            raise RuntimeError("/v1/observations/recent did not return a list.")
        if observations_body:
            if not isinstance(observations_body[0], dict):
                raise RuntimeError("/v1/observations/recent list item is not an object.")
            ensure_fields(
                observations_body[0],
                {
                    "observation_id",
                    "target_id",
                    "source_id",
                    "classification_marking",
                    "observed_at",
                    "lat",
                    "lon",
                    "unit_type",
                },
                "/v1/observations/recent",
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Frontend path smoke checks for API endpoints used by the React UI."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--shared-secret", required=True)
    parser.add_argument("--user-id", default=SYSTEM_ACTOR_UUID)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    asyncio.run(run_smoke(args.base_url, args.shared_secret, args.user_id))
    print("Frontend API path smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
