#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
repo_root_str = str(REPO_ROOT)
if repo_root_str not in sys.path:
    sys.path.insert(0, repo_root_str)

from backend.intelligence_fusion_service import ClearanceLevel, build_auth_claim_headers


@dataclass
class RequestResult:
    operation: str
    status_code: int
    duration_ms: float
    ok: bool
    error: str | None = None


def percentile_ms(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    if percentile <= 0:
        return min(samples)
    if percentile >= 100:
        return max(samples)
    sorted_samples = sorted(samples)
    rank = (percentile / 100) * (len(sorted_samples) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_samples) - 1)
    if low == high:
        return sorted_samples[low]
    weight = rank - low
    return sorted_samples[low] * (1 - weight) + sorted_samples[high] * weight


def summarize(results: list[RequestResult]) -> dict[str, Any]:
    total = len(results)
    successes = sum(1 for item in results if item.ok)
    failures = total - successes
    durations = [item.duration_ms for item in results]
    status_codes: dict[str, int] = {}
    for item in results:
        key = str(item.status_code)
        status_codes[key] = status_codes.get(key, 0) + 1

    return {
        "total_requests": total,
        "successes": successes,
        "failures": failures,
        "success_rate_pct": (successes / total * 100) if total else 0.0,
        "error_rate_pct": (failures / total * 100) if total else 0.0,
        "p50_ms": percentile_ms(durations, 50),
        "p95_ms": percentile_ms(durations, 95),
        "p99_ms": percentile_ms(durations, 99),
        "max_ms": max(durations) if durations else 0.0,
        "status_codes": status_codes,
    }


def build_ingest_payload(index: int) -> dict[str, Any]:
    pair_index = index // 2
    source_id = "LOAD-SRC-A" if index % 2 == 0 else "LOAD-SRC-B"
    coordinate = {"lat": 28.6139, "lon": 77.2090} if index % 2 == 0 else {"lat": 19.0760, "lon": 72.8777}
    return {
        "target_id": f"LOAD-TARGET-{pair_index}",
        "source_id": source_id,
        "source_type": "REST_HOOK",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "classification_marking": "SECRET",
        "confidence": 0.9,
        "coordinate": coordinate,
        "unit_type": "HOSTILE",
        "payload": {
            "index": index,
            "source": source_id,
        },
    }


async def run_load(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    rng = random.Random(args.seed)
    ingest_requests = int(args.requests * args.ingest_ratio)
    conflict_requests = args.requests - ingest_requests

    operations = ["ingest"] * ingest_requests + ["conflicts"] * conflict_requests
    rng.shuffle(operations)

    clearance = ClearanceLevel(args.clearance)
    timeout = httpx.Timeout(args.request_timeout_seconds)
    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[RequestResult] = []

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=timeout) as client:
        async def run_one(index: int, operation: str) -> None:
            headers = build_auth_claim_headers(
                user_id=args.user_id,
                clearance=clearance,
                shared_secret=args.shared_secret,
                jti=str(uuid4()),
            )

            start = time.perf_counter()
            try:
                async with semaphore:
                    if operation == "ingest":
                        response = await client.post("/v1/ingest/hook", headers=headers, json=build_ingest_payload(index))
                    else:
                        response = await client.get("/v1/conflicts/pending?limit=100", headers=headers)
                elapsed_ms = (time.perf_counter() - start) * 1000
                status_code = response.status_code
                ok = 200 <= status_code < 400
                results.append(
                    RequestResult(
                        operation=operation,
                        status_code=status_code,
                        duration_ms=elapsed_ms,
                        ok=ok,
                    )
                )
            except Exception as exc:  # pragma: no cover - runtime/network dependent
                elapsed_ms = (time.perf_counter() - start) * 1000
                results.append(
                    RequestResult(
                        operation=operation,
                        status_code=0,
                        duration_ms=elapsed_ms,
                        ok=False,
                        error=str(exc),
                    )
                )

        await asyncio.gather(*(run_one(index, operation) for index, operation in enumerate(operations)))

    overall = summarize(results)
    ingest_summary = summarize([item for item in results if item.operation == "ingest"])
    conflicts_summary = summarize([item for item in results if item.operation == "conflicts"])

    violations: list[str] = []
    if overall["success_rate_pct"] < args.min_success_rate_pct:
        violations.append(
            f"success_rate_pct {overall['success_rate_pct']:.2f} < {args.min_success_rate_pct:.2f}"
        )
    if overall["error_rate_pct"] > args.max_error_rate_pct:
        violations.append(
            f"error_rate_pct {overall['error_rate_pct']:.2f} > {args.max_error_rate_pct:.2f}"
        )
    if overall["p95_ms"] > args.max_p95_ms:
        violations.append(f"p95_ms {overall['p95_ms']:.2f} > {args.max_p95_ms:.2f}")
    if overall["p99_ms"] > args.max_p99_ms:
        violations.append(f"p99_ms {overall['p99_ms']:.2f} > {args.max_p99_ms:.2f}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": {
            "base_url": args.base_url,
            "user_id": args.user_id,
            "clearance": args.clearance,
        },
        "config": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "ingest_ratio": args.ingest_ratio,
            "request_timeout_seconds": args.request_timeout_seconds,
            "seed": args.seed,
        },
        "thresholds": {
            "min_success_rate_pct": args.min_success_rate_pct,
            "max_error_rate_pct": args.max_error_rate_pct,
            "max_p95_ms": args.max_p95_ms,
            "max_p99_ms": args.max_p99_ms,
        },
        "summary": {
            "overall": overall,
            "ingest": ingest_summary,
            "conflicts": conflicts_summary,
        },
        "violations": violations,
        "sample_failures": [asdict(item) for item in results if not item.ok][:10],
    }
    return report, violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SHAKTI phase-4 load harness for ingest and conflict retrieval flows."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--shared-secret", default=os.getenv("AUTH_SHARED_SECRET_PRIMARY", ""))
    parser.add_argument(
        "--user-id",
        default="00000000-0000-0000-0000-000000000000",
        help="Actor user_id for signed auth claims.",
    )
    parser.add_argument(
        "--clearance",
        choices=[level.value for level in ClearanceLevel],
        default=ClearanceLevel.TOP_SECRET.value,
    )
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--ingest-ratio", type=float, default=0.7)
    parser.add_argument("--request-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="/tmp/shakti_phase4_load_report.json")
    parser.add_argument("--min-success-rate-pct", type=float, default=95.0)
    parser.add_argument("--max-error-rate-pct", type=float, default=5.0)
    parser.add_argument("--max-p95-ms", type=float, default=1200.0)
    parser.add_argument("--max-p99-ms", type=float, default=2000.0)
    args = parser.parse_args()

    if not args.shared_secret.strip():
        raise SystemExit("--shared-secret is required (or AUTH_SHARED_SECRET_PRIMARY must be set).")
    if args.requests < 1:
        raise SystemExit("--requests must be >= 1.")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1.")
    if not (0 <= args.ingest_ratio <= 1):
        raise SystemExit("--ingest-ratio must be between 0 and 1.")
    if args.request_timeout_seconds <= 0:
        raise SystemExit("--request-timeout-seconds must be > 0.")
    return args


def main() -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)

    args = parse_args()
    report, violations = asyncio.run(run_load(args))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    overall = report["summary"]["overall"]
    print(f"Load report written to {out_path}")
    print(
        "overall: "
        f"requests={overall['total_requests']} "
        f"success_rate_pct={overall['success_rate_pct']:.2f} "
        f"p95_ms={overall['p95_ms']:.2f} "
        f"p99_ms={overall['p99_ms']:.2f}"
    )
    if violations:
        print("Severe threshold violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("All severe thresholds passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
