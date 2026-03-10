# Project Shakti

Minimal multi-surface SHAKTI repo containing:

- A hardened FastAPI intelligence-fusion service in `backend/intelligence_fusion_service.py`
- A Postgres/PostGIS schema in `db/phase2_schema_postgres_postgis.sql`
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

Live Postgres integration tests are opt-in and require `psql` plus a reachable database at `SHAKTI_TEST_PG_DSN`:

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

This stack waits for PostgreSQL, applies the schema on boot, disables MQTT by default for local runs, and serves the API at `http://127.0.0.1:8000/healthz`.

## Staging

Use the staging override plus the published GHCR image:

```bash
cp ops/staging/staging.env.example .env.staging
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml up -d
```

This adds Prometheus, Grafana, and PostgreSQL exporter around the API. The starter dashboard and scrape config live under `ops/staging/`.

## Image Publishing

Pushing a semantic tag such as `v1.2.3` triggers `.github/workflows/publish-image.yml`, which builds and publishes a multi-architecture API image to GitHub Container Registry.
