# Restore Drill Checklist

Run this checklist at least quarterly in staging and after major database changes.

## Pre-Drill

- [ ] Confirm drill owner and observers.
- [ ] Confirm target environment and maintenance window.
- [ ] Confirm latest backup artifact and checksum are available.
- [ ] Confirm rollback decision criteria and communication channel.
- [ ] Record start time.

## Drill Execution

- [ ] Bring up database/service stack with staging compose files.
- [ ] Validate pre-restore state (`/healthz`, key tables present).
- [ ] Execute restore command:
  - `./ops/db/restore_postgres.sh --env-file .env.staging --backup-file <path> --yes`
- [ ] Run schema drift check:
  - `docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml run --rm api python /app/ops/db/migrate.py drift-check --require-up-to-date`
- [ ] Run API sanity checks:
  - ingest endpoint request
  - conflicts read endpoint request
- [ ] Verify Prometheus targets are healthy and no critical alerts fire.

## Post-Drill Validation

- [ ] Verify row counts or key business records match expected backup state.
- [ ] Verify auth replay guard and rate-limit tables are present.
- [ ] Verify dashboard panels recover within expected time.
- [ ] Record end time and calculate observed RTO.
- [ ] Estimate data recency gap from backup timestamp and calculate observed RPO.

## Sign-Off

- [ ] Did observed RTO meet target?
- [ ] Did observed RPO meet target?
- [ ] Were any manual steps unclear or risky?
- [ ] Create follow-up issues for gaps (owner + due date).
- [ ] Attach logs, command output, and checklist artifact to incident/runbook history.
