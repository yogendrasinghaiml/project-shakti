# SHAKTI Backup And Restore Runbook

## Scope

This runbook defines PostgreSQL backup, restore, and recovery objectives for SHAKTI.

Scripts:

- `ops/db/backup_postgres.sh`
- `ops/db/restore_postgres.sh`

## Recovery Objectives

| Environment | RPO Target | RTO Target |
| --- | --- | --- |
| Staging | 24 hours | 60 minutes |
| Production (target) | 15 minutes | 30 minutes |

Definitions:

- RPO (Recovery Point Objective): maximum acceptable data loss window.
- RTO (Recovery Time Objective): maximum acceptable time to restore service.

## Backup Schedule

1. Staging:
   - Minimum cadence: daily full backup.
   - Suggested cadence: every 6 hours.
2. Production target:
   - Full backup every 24 hours plus WAL archiving or frequent snapshot backups to meet 15-minute RPO.

## Staging Backup Procedure

1. Ensure staging stack is running.
2. Run backup command:

```bash
./ops/db/backup_postgres.sh --env-file .env.staging
```

3. Confirm output:
   - `.dump` file created in `ops/staging/backups/`
   - `.sha256` file created for integrity verification
4. Copy backup artifacts to durable storage outside the host (object store or secure archive).

## Staging Restore Procedure

1. Stop API writes or enter maintenance mode.
2. Identify backup artifact to restore.
3. Run restore command:

```bash
./ops/db/restore_postgres.sh --env-file .env.staging --backup-file ops/staging/backups/<backup>.dump --yes
```

4. Re-validate schema and service:

```bash
docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml run --rm api python /app/ops/db/migrate.py drift-check --require-up-to-date
curl -fsS http://127.0.0.1:18000/healthz
```

5. Review Prometheus/Grafana for error and latency spikes.

## Integrity And Retention

1. Keep checksum files (`.sha256`) with each backup.
2. Verify checksum before restore:

```bash
shasum -a 256 -c ops/staging/backups/<backup>.dump.sha256
```

3. Default local retention in backup script is 14 days.
4. Retention in external storage should follow organizational policy and compliance controls.

## Failure Handling

1. If backup fails:
   - Check PostgreSQL container health.
   - Check disk free space and host permissions.
   - Re-run backup and verify checksum output.
2. If restore fails:
   - Keep failed logs.
   - Re-run restore with a known-good backup.
   - Run restore drill checklist before resuming traffic.

## Drill Reference

Use `docs/restore_drill_checklist.md` for quarterly restore exercises and sign-off.
