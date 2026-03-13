#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ops/db/backup_postgres.sh [options]

Create a compressed PostgreSQL backup from a running Docker Compose service.

Options:
  --env-file PATH            Compose env file (default: ops/staging/staging.env.example)
  -f, --compose-file PATH    Compose file (repeatable; default: docker-compose.yml + docker-compose.staging.yml)
  --service NAME             Postgres service name (default: postgres)
  --db-name NAME             Database name (default: shakti)
  --db-user NAME             Database user (default: shakti)
  --output-dir PATH          Backup output directory (default: ops/staging/backups)
  --filename NAME            Output filename (default: shakti_YYYYmmddTHHMMSSZ.dump)
  --retention-days DAYS      Delete backup files older than DAYS (default: 14)
  -h, --help                 Show this help
EOF
}

ENV_FILE="ops/staging/staging.env.example"
declare -a COMPOSE_FILES=()
SERVICE="postgres"
DB_NAME="shakti"
DB_USER="shakti"
OUTPUT_DIR="ops/staging/backups"
FILENAME=""
RETENTION_DAYS="14"

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --filename)
      FILENAME="$2"
      shift 2
      ;;
    --retention-days)
      RETENTION_DAYS="$2"
      shift 2
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

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  echo "--retention-days must be a non-negative integer." >&2
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
  echo "Service '$SERVICE' is not running. Start the stack before taking backups." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
if [[ -z "$FILENAME" ]]; then
  FILENAME="shakti_${timestamp}.dump"
fi
backup_path="${OUTPUT_DIR%/}/$FILENAME"
checksum_path="${backup_path}.sha256"

if [[ -e "$backup_path" ]]; then
  echo "Backup target already exists: $backup_path" >&2
  exit 1
fi

umask 077
tmp_path="${backup_path}.tmp"

run_compose exec -T "$SERVICE" \
  pg_dump \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  > "$tmp_path"

if [[ ! -s "$tmp_path" ]]; then
  rm -f "$tmp_path"
  echo "Backup failed: output file is empty." >&2
  exit 1
fi

mv "$tmp_path" "$backup_path"
shasum -a 256 "$backup_path" > "$checksum_path"

if [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$OUTPUT_DIR" -type f \( -name "*.dump" -o -name "*.dump.sha256" \) -mtime +"$RETENTION_DAYS" -delete
fi

echo "Backup created: $backup_path"
echo "Checksum file: $checksum_path"
