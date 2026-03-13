# Staging Secret Files

This directory is mounted into the staging API container as `/run/secrets`.

Expected files:

- `auth_shared_secrets.json`
- `api_pg_dsn`
- `postgres_password`
- `postgres_exporter_dsn`
- `grafana_admin_user`
- `grafana_admin_password`

Render them with:

```bash
POSTGRES_PASSWORD=replace-with-a-real-password \
AUTH_SHARED_SECRET_PRIMARY=replace-with-a-real-secret \
GRAFANA_ADMIN_PASSWORD=replace-with-a-real-password \
./ops/staging/render-secrets.sh
```

The generated files are ignored by Git and written with `0600` permissions.
If `GRAFANA_ADMIN_PASSWORD` is not provided, the renderer generates a random one.
