# External Secret Manager Examples

This document shows reference patterns for managing SHAKTI secrets outside git and injecting them into runtime environments.

## Kubernetes + External Secrets Operator (AWS Secrets Manager)

Store secrets in AWS Secrets Manager, then sync into Kubernetes `Secret` objects.

Example `ExternalSecret` for API auth and DB DSN:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: shakti-api-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secretsmanager
  target:
    name: shakti-api-secrets
    creationPolicy: Owner
  data:
    - secretKey: auth_shared_secrets.json
      remoteRef:
        key: /shakti/staging/auth_shared_secrets_json
    - secretKey: api_pg_dsn
      remoteRef:
        key: /shakti/staging/api_pg_dsn
```

Mount to container paths used by SHAKTI:

- `/run/secrets/auth_shared_secrets.json`
- `/run/secrets/api_pg_dsn`

Set:

- `AUTH_SHARED_SECRETS_FILE=/run/secrets/auth_shared_secrets.json`
- `PG_DSN_FILE=/run/secrets/api_pg_dsn`

## Kubernetes + CSI Secret Store (Azure Key Vault)

Use `SecretProviderClass` to mount Key Vault secrets as files:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: shakti-secrets
spec:
  provider: azure
  parameters:
    usePodIdentity: "true"
    keyvaultName: "<kv-name>"
    tenantId: "<tenant-id>"
    objects: |
      array:
        - |
          objectName: shakti-auth-shared-secrets-json
          objectType: secret
        - |
          objectName: shakti-api-pg-dsn
          objectType: secret
```

Mount volume at `/run/secrets` and configure `*_FILE` environment variables as above.

## Cloud Service Example (AWS ECS/Fargate)

Use task definition secrets from AWS Secrets Manager:

- `AUTH_SHARED_SECRETS_FILE` mapped via sidecar/init to local file path
- `PG_DSN_FILE` mapped via sidecar/init to local file path
- Grafana/Postgres exporter secrets injected similarly as files or container runtime secrets

For services that do not support `_FILE` directly, use a tiny wrapper entrypoint that reads secret files and exports runtime env vars before starting the process.

## Rotation Guidance

1. Keep secret names stable; rotate values in-place.
2. Use short refresh intervals for staging and controlled rollout windows for production.
3. Validate rotation with:
   - API auth signed-claim checks
   - migration drift check
   - health and alert dashboards
