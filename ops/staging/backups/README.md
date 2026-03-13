# Staging Backup Artifacts

This directory is the default local output target for:

- `ops/db/backup_postgres.sh`

Expected files:

- `*.dump` database backups
- `*.dump.sha256` checksum files

Do not commit backup artifacts to git.
