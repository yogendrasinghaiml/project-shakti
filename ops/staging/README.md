# Staging Stack

Use the base compose file plus the staging override to run the API from a published image with Prometheus and Grafana:

```bash
cp ops/staging/staging.env.example .env.staging
POSTGRES_PASSWORD=replace-with-a-real-password \
AUTH_SHARED_SECRET_PRIMARY=replace-with-a-real-secret \
GRAFANA_ADMIN_PASSWORD=replace-with-a-real-password \
./ops/staging/render-secrets.sh
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml up -d
```

The staging API, database, exporter, and Grafana now read credentials from mounted files in `ops/staging/secrets/`:

- `auth_shared_secrets.json`
- `api_pg_dsn`
- `postgres_password`
- `postgres_exporter_dsn`
- `grafana_admin_user`
- `grafana_admin_password`

`./ops/staging/render-secrets.sh` creates these files with `0600` permissions.
If `GRAFANA_ADMIN_PASSWORD` is omitted, the renderer generates one automatically.

Default exposed ports:

- API: `18000`
- PostgreSQL: `15432`
- Prometheus: `19090`
- Grafana: `13000`

Key services:

- `api` scrapes its own `/metrics` endpoint
- `postgres-exporter` exposes PostgreSQL metrics to Prometheus
- Prometheus loads alert rules from `ops/staging/prometheus/alerts.yml`
- Grafana auto-loads the starter `SHAKTI Staging Overview` dashboard

Backup and restore scripts:

- `./ops/db/backup_postgres.sh --env-file .env.staging`
- `./ops/db/restore_postgres.sh --env-file .env.staging --backup-file ops/staging/backups/<backup>.dump --yes`

Shutdown:

```bash
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml down
```
