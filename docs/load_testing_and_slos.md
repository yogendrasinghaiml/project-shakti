# Load Testing And SLO Targets

## Scope

Phase 4 load testing covers:

- `POST /v1/ingest/hook`
- `GET /v1/conflicts/pending`

Harness script:

- `ops/loadtest/run_phase4_load.py`

## Baseline SLO Targets

These are the current baseline targets for staging-grade infrastructure:

- Availability / success rate: `>= 99.0%`
- Error rate: `<= 1.0%`
- p95 latency: `<= 750 ms`
- p99 latency: `<= 1200 ms`

## Severe Regression Gate (CI)

CI uses a lighter profile and fails only on severe regressions:

- Minimum success rate: `95.0%`
- Maximum error rate: `5.0%`
- Maximum p95 latency: `1200 ms`
- Maximum p99 latency: `2000 ms`

## Max Tested Concurrency

Current validated cap in this phase:

- `20` concurrent requests

Raise this value only after updating DB/API sizing and rerunning load profiles.

## Local Runbook

1. Start PostgreSQL test service:

```bash
docker compose -f docker-compose.test.yml up -d postgres
```

2. Apply migrations:

```bash
.venv/bin/python ops/db/migrate.py --dsn postgresql://shakti:shakti@127.0.0.1:55432/shakti up
```

3. Start API in another shell:

```bash
AUTH_SHARED_SECRET_PRIMARY=load-test-secret \
PG_DSN=postgresql://shakti:shakti@127.0.0.1:55432/shakti \
MQTT_ENABLED=false \
API_RATE_LIMIT_ENABLED=false \
.venv/bin/python -m uvicorn backend.intelligence_fusion_service:app --host 127.0.0.1 --port 18080 --no-access-log
```

4. Run harness:

```bash
.venv/bin/python ops/loadtest/run_phase4_load.py \
  --base-url http://127.0.0.1:18080 \
  --shared-secret load-test-secret \
  --requests 300 \
  --concurrency 20 \
  --out /tmp/shakti_phase4_load_report.json
```

5. Inspect report JSON and compare to target SLOs.
