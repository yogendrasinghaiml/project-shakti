# Database Migrations

## Overview

SHAKTI uses versioned SQL migrations under `db/migrations/`:

- `*.up.sql` applies a migration
- `*.down.sql` rolls a migration back

Migration state is tracked in `shakti_meta.schema_migrations`.

## Runner

Use `ops/db/migrate.py` for all migration operations:

```bash
python ops/db/migrate.py status
python ops/db/migrate.py up
python ops/db/migrate.py drift-check --require-up-to-date
python ops/db/migrate.py down --steps 1
```

The runner reads PostgreSQL credentials in this order:

1. `--dsn` / `--dsn-file`
2. `PG_DSN` / `PG_DSN_FILE`
3. default `postgresql://shakti:shakti@127.0.0.1:5432/shakti`

## Boot Modes

Container boot behavior is controlled with `SHAKTI_DB_MIGRATION_MODE`:

- `auto`: wait for DB and apply pending migrations
- `verify`: wait for DB and fail startup on drift/pending migrations
- `off`: skip migration commands

Recommended values:

- Local/dev: `auto`
- Staging/prod: `verify`

## Staging Flow

1. Render/update secrets:

```bash
POSTGRES_PASSWORD=... AUTH_SHARED_SECRET_PRIMARY=... ./ops/staging/render-secrets.sh
```

2. Apply migrations explicitly:

```bash
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml run --rm api python /app/ops/db/migrate.py up
```

3. Verify drift and boot services:

```bash
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml run --rm api python /app/ops/db/migrate.py drift-check --require-up-to-date
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml up -d
```

## Rollback Flow

Rollback one migration:

```bash
python ops/db/migrate.py down --steps 1
```

Rollback to a target version:

```bash
python ops/db/migrate.py down --to 0001
```

Rollback everything:

```bash
python ops/db/migrate.py down --to 0
```
