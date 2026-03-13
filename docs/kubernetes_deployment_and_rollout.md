# Kubernetes Deployment And Rollout

## Helm Chart

SHAKTI ships with a Helm chart at `deploy/helm/shakti`:

- `values.yaml`: baseline defaults
- `values-staging.yaml`: staging overlay
- `values-production.yaml`: production overlay

Render manifests locally:

```bash
helm template shakti-staging deploy/helm/shakti -f deploy/helm/shakti/values-staging.yaml
helm template shakti-prod deploy/helm/shakti -f deploy/helm/shakti/values-production.yaml
```

## Required Secret Contracts

The API expects file-backed secrets mounted by Kubernetes Secrets:

- auth secret key: `auth_shared_secrets.json` (for `AUTH_STRATEGY=shared_secret`)
- database secret key: `pg_dsn`

Example staging auth secret:

```bash
kubectl -n shakti-staging create secret generic shakti-staging-auth \
  --from-literal=auth_shared_secrets.json='{"primary":"<secret>","secondary":""}'
```

Example production DB secret:

```bash
kubectl -n shakti-prod create secret generic shakti-production-db \
  --from-literal=pg_dsn='postgresql://<user>:<password>@<host>:5432/shakti'
```

## Image Pinning

Do not deploy `latest` in staging/production. Pin immutable images:

1. Use a release tag for traceability (`vX.Y.Z`).
2. Pin by digest for immutability (`sha256:...`), especially in production.

Example:

```bash
helm upgrade --install shakti-prod deploy/helm/shakti \
  -n shakti-prod --create-namespace \
  -f deploy/helm/shakti/values-production.yaml \
  --set image.repository=ghcr.io/<owner>/project-shakti-api \
  --set image.tag=v1.2.3 \
  --set image.digest=sha256:<immutable_digest>
```

## Rollout Strategy

1. Apply to staging first and wait for rollout completion:

```bash
helm upgrade --install shakti-staging deploy/helm/shakti \
  -n shakti-staging --create-namespace \
  -f deploy/helm/shakti/values-staging.yaml
kubectl -n shakti-staging rollout status deployment/shakti-staging-shakti --timeout=5m
```

2. Run frontend path smoke checks against staging:

```bash
.venv/bin/python ops/smoke/frontend_path_smoke.py \
  --base-url http://<staging-api-host> \
  --shared-secret <staging-auth-secret>
```

3. Promote the same pinned image digest to production.

4. Confirm production rollout:

```bash
kubectl -n shakti-prod rollout status deployment/shakti-prod-shakti --timeout=10m
```

The chart runs migrations using a Helm pre-install/pre-upgrade hook job before application rollout.

## Rollback Strategy

Roll back Kubernetes workload to a previous Helm revision:

```bash
helm -n shakti-prod history shakti-prod
helm -n shakti-prod rollback shakti-prod <revision>
```

If a migration also needs rollback, run an explicit DB rollback command:

```bash
kubectl -n shakti-prod exec deploy/shakti-prod-shakti -- \
  python /app/ops/db/migrate.py --dsn-file /run/secrets/db/pg_dsn down --steps 1
```

Only roll database schema back after validating application compatibility and backup/restore readiness.
