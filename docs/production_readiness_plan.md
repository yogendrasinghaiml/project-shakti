# Production Readiness Plan

This checklist tracks the remaining work to move SHAKTI from staging-grade to production-grade.

## Phase 1: Secret Management And Rotation

- [x] Add file-backed secret loading for the API runtime (`*_FILE` support for critical secrets)
- [x] Move staging API auth and database DSN to mounted secret files
- [x] Add a staging secret rendering utility and secret directory contract
- [x] Move database/exporter/Grafana credentials to secret-file wiring where supported
- [x] Add external secret manager examples for Kubernetes and cloud deployments

## Phase 2: Database Migrations And Rollback

- [x] Introduce a versioned migration table and migration runner
- [x] Split the current schema bootstrap into ordered migration files
- [x] Make schema-on-boot dev-only and require explicit migrations in staging/prod
- [x] Add rollback and drift-check commands

## Phase 3: Backup, Restore, DR, And Alerting

- [x] Add PostgreSQL backup and restore scripts
- [x] Add recovery-point and recovery-time objectives to runbooks
- [x] Add Prometheus alert rules for API failures, latency, and database health
- [x] Add a restore drill checklist

## Phase 4: Load Testing And Capacity Limits

- [x] Add a load-testing harness for ingest and conflict retrieval flows
- [x] Define baseline SLO targets and max tested concurrency
- [x] Capture p95/p99 latency and error-rate thresholds in docs

## Phase 5: Real Deployment Targets

- [x] Add Kubernetes manifests or a Helm chart
- [x] Add environment overlays for staging and production
- [x] Add image/tag pinning and rollout strategy docs

## Phase 6: External Auth Hardening

- [x] Add JWT/JWKS validation for real external identity providers
- [x] Separate gateway signing concerns from service-side validation
- [x] Add key rotation and issuer/audience policy tests

## Phase 7: Frontend Product Hardening

- [x] Add production navigation, error states, and loading states
- [x] Add frontend smoke tests for the main user paths
- [x] Replace demo-only surfaces with real API-backed flows
