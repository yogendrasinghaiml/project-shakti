# Project Shakti

Minimal multi-surface SHAKTI repo containing:

- A hardened FastAPI intelligence-fusion service in `backend/intelligence_fusion_service.py`
- Versioned Postgres/PostGIS migrations in `db/migrations/`
- Tactical map helper code in `frontend/TacticalMapView.tsx` and `frontend/tactical_helpers.ts`

## Local Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-ci.txt
npm install
```

## Verification

Default verification runs frontend tests plus backend unit/integration-safe pytest collection:

```bash
npm test
```

Backend-only checks:

```bash
npm run lint:backend
npm run typecheck:backend
npm run test:backend
```

Frontend build checks:

```bash
npm run typecheck:frontend
npm run build:frontend
npm run audit:frontend
```

Live Postgres integration tests are opt-in and require a reachable database at `SHAKTI_TEST_PG_DSN`:

```bash
docker compose -f docker-compose.test.yml up -d postgres
npm run test:backend:integration
```

By default, the live integration module skips cleanly when the database stack is not available.

## Containers

Run the API and PostgreSQL together:

```bash
cp .env.example .env
docker compose up --build
```

This stack waits for PostgreSQL, auto-applies pending migrations in local mode, disables MQTT by default for local runs, and serves the API at `http://127.0.0.1:8000/healthz`.

## Database Migrations

Run migrations directly from your host:

```bash
python ops/db/migrate.py status
python ops/db/migrate.py up
python ops/db/migrate.py drift-check --require-up-to-date
python ops/db/migrate.py down --steps 1
```

By default, local Docker uses `SHAKTI_DB_MIGRATION_MODE=auto` so pending migrations are applied automatically at startup.

## Staging

Use the staging override plus the published GHCR image:

```bash
cp ops/staging/staging.env.example .env.staging
POSTGRES_PASSWORD=replace-with-a-real-password \
AUTH_SHARED_SECRET_PRIMARY=replace-with-a-real-secret \
./ops/staging/render-secrets.sh
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml run --rm api python /app/ops/db/migrate.py up
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml up -d
```

This adds Prometheus, Grafana, and PostgreSQL exporter around the API. Staging defaults to `SHAKTI_DB_MIGRATION_MODE=verify`, so API boot fails fast if migrations drift or are pending. The starter dashboard, scrape config, and staging secret contract live under `ops/staging/`.

## Production Plan

The current production hardening task list is tracked in `docs/production_readiness_plan.md`.

## Image Publishing

Pushing a semantic tag such as `v1.2.3` triggers `.github/workflows/publish-image.yml`, which builds and publishes a multi-architecture API image to GitHub Container Registry.
