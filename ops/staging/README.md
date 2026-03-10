# Staging Stack

Use the base compose file plus the staging override to run the API from a published image with Prometheus and Grafana:

```bash
cp ops/staging/staging.env.example .env.staging
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml up -d
```

Default exposed ports:

- API: `18000`
- PostgreSQL: `15432`
- Prometheus: `19090`
- Grafana: `13000`

Key services:

- `api` scrapes its own `/metrics` endpoint
- `postgres-exporter` exposes PostgreSQL metrics to Prometheus
- Grafana auto-loads the starter `SHAKTI Staging Overview` dashboard

Shutdown:

```bash
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml down
```
