#!/bin/sh
set -eu

OUTPUT_DIR="${1:-ops/staging/secrets}"

python3 - "$OUTPUT_DIR" <<'PY'
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote


output_dir = Path(sys.argv[1])
output_dir.mkdir(parents=True, exist_ok=True)

postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
if not postgres_password:
    raise SystemExit("POSTGRES_PASSWORD is required to render staging secrets.")

auth_primary = os.getenv("AUTH_SHARED_SECRET_PRIMARY", "").strip() or secrets.token_hex(32)
auth_secondary = os.getenv("AUTH_SHARED_SECRET_SECONDARY", "").strip()
pg_user = os.getenv("PG_USER", "shakti").strip() or "shakti"
pg_host = os.getenv("PG_HOST", "postgres").strip() or "postgres"
pg_port = os.getenv("PG_PORT", "5432").strip() or "5432"
pg_database = os.getenv("PG_DATABASE", "shakti").strip() or "shakti"

auth_bundle_path = output_dir / "auth_shared_secrets.json"
pg_dsn_path = output_dir / "api_pg_dsn"

auth_bundle_path.write_text(
    json.dumps(
        {
            "primary": auth_primary,
            "secondary": auth_secondary,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
pg_dsn_path.write_text(
    "postgresql://"
    f"{quote(pg_user, safe='')}:{quote(postgres_password, safe='')}@"
    f"{pg_host}:{pg_port}/{quote(pg_database, safe='')}\n",
    encoding="utf-8",
)

os.chmod(auth_bundle_path, 0o600)
os.chmod(pg_dsn_path, 0o600)

print(f"Rendered {auth_bundle_path}")
print(f"Rendered {pg_dsn_path}")
if not os.getenv("AUTH_SHARED_SECRET_PRIMARY", "").strip():
    print("Generated a new AUTH_SHARED_SECRET_PRIMARY value because none was provided.")
PY
