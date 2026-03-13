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
grafana_admin_user = os.getenv("GRAFANA_ADMIN_USER", "admin").strip() or "admin"
grafana_admin_password = os.getenv("GRAFANA_ADMIN_PASSWORD", "").strip()
generated_grafana_admin_password = not bool(grafana_admin_password)
if generated_grafana_admin_password:
    grafana_admin_password = secrets.token_urlsafe(24)
pg_user = os.getenv("PG_USER", "shakti").strip() or "shakti"
pg_host = os.getenv("PG_HOST", "postgres").strip() or "postgres"
pg_port = os.getenv("PG_PORT", "5432").strip() or "5432"
pg_database = os.getenv("PG_DATABASE", "shakti").strip() or "shakti"

auth_bundle_path = output_dir / "auth_shared_secrets.json"
pg_dsn_path = output_dir / "api_pg_dsn"
postgres_password_path = output_dir / "postgres_password"
postgres_exporter_dsn_path = output_dir / "postgres_exporter_dsn"
grafana_admin_user_path = output_dir / "grafana_admin_user"
grafana_admin_password_path = output_dir / "grafana_admin_password"

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
postgres_password_path.write_text(postgres_password + "\n", encoding="utf-8")
postgres_exporter_dsn_path.write_text(
    "postgresql://"
    f"{quote(pg_user, safe='')}:{quote(postgres_password, safe='')}@"
    f"{pg_host}:{pg_port}/{quote(pg_database, safe='')}?sslmode=disable\n",
    encoding="utf-8",
)
grafana_admin_user_path.write_text(grafana_admin_user + "\n", encoding="utf-8")
grafana_admin_password_path.write_text(grafana_admin_password + "\n", encoding="utf-8")

os.chmod(auth_bundle_path, 0o600)
os.chmod(pg_dsn_path, 0o600)
os.chmod(postgres_password_path, 0o600)
os.chmod(postgres_exporter_dsn_path, 0o600)
os.chmod(grafana_admin_user_path, 0o600)
os.chmod(grafana_admin_password_path, 0o600)

print(f"Rendered {auth_bundle_path}")
print(f"Rendered {pg_dsn_path}")
print(f"Rendered {postgres_password_path}")
print(f"Rendered {postgres_exporter_dsn_path}")
print(f"Rendered {grafana_admin_user_path}")
print(f"Rendered {grafana_admin_password_path}")
if not os.getenv("AUTH_SHARED_SECRET_PRIMARY", "").strip():
    print("Generated a new AUTH_SHARED_SECRET_PRIMARY value because none was provided.")
if generated_grafana_admin_password:
    print("Generated a new GRAFANA_ADMIN_PASSWORD value because none was provided.")
PY
