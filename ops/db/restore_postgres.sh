#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ops/db/restore_postgres.sh --backup-file PATH [options]

Restore a PostgreSQL backup into a running Docker Compose service.

Options:
  --backup-file PATH         Backup file produced by backup_postgres.sh (required)
  --env-file PATH            Compose env file (default: ops/staging/staging.env.example)
  -f, --compose-file PATH    Compose file (repeatable; default: docker-compose.yml + docker-compose.staging.yml)
  --service NAME             Postgres service name (default: postgres)
  --db-name NAME             Database name (default: shakti)
  --db-user NAME             Database user (default: shakti)
  --skip-reset-public        Do not drop/recreate the public schema before restore
  --yes                      Skip interactive confirmation
  -h, --help                 Show this help
EOF
}

BACKUP_FILE=""
ENV_FILE="ops/staging/staging.env.example"
declare -a COMPOSE_FILES=()
SERVICE="postgres"
DB_NAME="shakti"
DB_USER="shakti"
RESET_PUBLIC="true"
AUTO_CONFIRM="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-file)
      BACKUP_FILE="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    -f|--compose-file)
      COMPOSE_FILES+=("$2")
      shift 2
      ;;
    --service)
      SERVICE="$2"
      shift 2
      ;;
    --db-name)
      DB_NAME="$2"
      shift 2
      ;;
    --db-user)
      DB_USER="$2"
      shift 2
      ;;
    --skip-reset-public)
      RESET_PUBLIC="false"
      shift
      ;;
    --yes)
      AUTO_CONFIRM="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$BACKUP_FILE" ]]; then
  echo "--backup-file is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file does not exist: $BACKUP_FILE" >&2
  exit 1
fi

if [[ ${#COMPOSE_FILES[@]} -eq 0 ]]; then
  COMPOSE_FILES=("docker-compose.yml" "docker-compose.staging.yml")
fi

declare -a COMPOSE_CMD=("docker" "compose" "--env-file" "$ENV_FILE")
for file_path in "${COMPOSE_FILES[@]}"; do
  COMPOSE_CMD+=("-f" "$file_path")
done

run_compose() {
  "${COMPOSE_CMD[@]}" "$@"
}

container_id="$(run_compose ps -q "$SERVICE")"
if [[ -z "$container_id" ]]; then
  echo "Service '$SERVICE' is not running. Start the stack before restoring." >&2
  exit 1
fi

if [[ "$AUTO_CONFIRM" != "true" ]]; then
  echo "Restore target service: $SERVICE"
  echo "Database: $DB_NAME"
  echo "Backup file: $BACKUP_FILE"
  echo "This operation will overwrite live data."
  read -r -p "Type RESTORE to continue: " response
  if [[ "$response" != "RESTORE" ]]; then
    echo "Restore cancelled."
    exit 1
  fi
fi

if [[ "$RESET_PUBLIC" == "true" ]]; then
  cat <<SQL | run_compose exec -T "$SERVICE" psql -v ON_ERROR_STOP=1 --username="$DB_USER" --dbname="$DB_NAME"
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DB_NAME'
  AND pid <> pg_backend_pid();

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO CURRENT_USER;
GRANT ALL ON SCHEMA public TO PUBLIC;
SQL
fi

cat "$BACKUP_FILE" | run_compose exec -T "$SERVICE" \
  pg_restore \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --format=custom \
  --single-transaction \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges

echo "Restore completed successfully from $BACKUP_FILE"
