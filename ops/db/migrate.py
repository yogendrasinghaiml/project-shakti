#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

MIGRATION_FILE_RE = re.compile(
    r"^(?P<version>\d{4,})_(?P<name>[a-z0-9_]+)\.(?P<direction>up|down)\.sql$"
)
MIGRATION_LOCK_NAME = "shakti_schema_migrations_v1"
MIGRATION_META_SCHEMA = "shakti_meta"
MIGRATION_META_TABLE = "schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    up_path: Path
    down_path: Path | None
    checksum: str


def load_text_value(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip()


def load_text_value_from_env_or_file(name: str, default: str = "") -> str:
    raw_value = os.getenv(name)
    raw_file = os.getenv(f"{name}_FILE")
    value = raw_value.strip() if raw_value is not None else ""
    file_path = raw_file.strip() if raw_file is not None else ""

    if value and file_path:
        raise ValueError(f"{name} and {name}_FILE cannot both be set.")
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"{name}_FILE is unreadable: {file_path}") from exc
    if raw_value is None:
        return default
    return value


def parse_positive_float(value: str, arg_name: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{arg_name} must be a positive number.")
    return parsed


def redact_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if not parts.scheme or parts.hostname is None:
        return dsn
    auth_prefix = ""
    if parts.username:
        auth_prefix = f"{parts.username}:***@"
    host = parts.hostname
    port = f":{parts.port}" if parts.port is not None else ""
    return urlunsplit(
        (
            parts.scheme,
            f"{auth_prefix}{host}{port}",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


def default_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "migrations"


def resolve_dsn(args: argparse.Namespace) -> str:
    cli_dsn = (args.dsn or "").strip()
    cli_dsn_file = (args.dsn_file or "").strip()
    if cli_dsn and cli_dsn_file:
        raise ValueError("--dsn and --dsn-file cannot both be set.")
    if cli_dsn_file:
        try:
            return Path(cli_dsn_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"--dsn-file is unreadable: {cli_dsn_file}") from exc
    if cli_dsn:
        return cli_dsn
    return load_text_value_from_env_or_file(
        "PG_DSN",
        "postgresql://shakti:shakti@127.0.0.1:5432/shakti",
    )


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    if not migrations_dir.exists():
        raise ValueError(f"Migration directory does not exist: {migrations_dir}")
    if not migrations_dir.is_dir():
        raise ValueError(f"Migration directory is not a directory: {migrations_dir}")

    grouped: dict[str, dict[str, Path | str | None]] = {}
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_FILE_RE.match(path.name)
        if match is None:
            continue
        version = match.group("version")
        name = match.group("name")
        direction = match.group("direction")
        row = grouped.get(version)
        if row is None:
            row = {"name": name, "up": None, "down": None}
            grouped[version] = row
        elif row["name"] != name:
            raise ValueError(
                f"Version {version} is declared with multiple names: {row['name']} and {name}."
            )
        row[direction] = path

    if not grouped:
        raise ValueError(f"No migration files were found under {migrations_dir}.")

    migrations: list[Migration] = []
    for version in sorted(grouped.keys(), key=int):
        row = grouped[version]
        up_path = row["up"]
        down_path = row["down"]
        if not isinstance(up_path, Path):
            raise ValueError(f"Migration {version}_{row['name']} is missing an .up.sql file.")
        up_bytes = up_path.read_bytes()
        checksum = hashlib.sha256(up_bytes).hexdigest()
        migrations.append(
            Migration(
                version=version,
                name=str(row["name"]),
                up_path=up_path,
                down_path=down_path if isinstance(down_path, Path) else None,
                checksum=checksum,
            )
        )
    return migrations


async def ensure_migration_metadata(conn: asyncpg.Connection) -> None:
    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {MIGRATION_META_SCHEMA}")
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_META_SCHEMA}.{MIGRATION_META_TABLE} (
          sequence_id BIGSERIAL PRIMARY KEY,
          version TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


async def acquire_migration_lock(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "SELECT pg_advisory_lock(hashtextextended($1, 0))",
        MIGRATION_LOCK_NAME,
    )


async def release_migration_lock(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "SELECT pg_advisory_unlock(hashtextextended($1, 0))",
        MIGRATION_LOCK_NAME,
    )


async def fetch_applied_rows(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        SELECT sequence_id, version, name, checksum, applied_at
        FROM {MIGRATION_META_SCHEMA}.{MIGRATION_META_TABLE}
        ORDER BY sequence_id ASC
        """
    )


async def wait_for_database(dsn: str, timeout_seconds: float, connect_timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    redacted_dsn = redact_dsn(dsn)
    last_error = "unknown error"
    while time.time() < deadline:
        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(dsn, timeout=connect_timeout_seconds)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception as exc:  # pragma: no cover - runtime/network dependent
            if conn is not None:
                await conn.close()
            last_error = str(exc).replace(dsn, redacted_dsn)
            await asyncio.sleep(1)
    raise RuntimeError(
        f"PostgreSQL at {redacted_dsn} did not become ready within {timeout_seconds:g}s: {last_error}"
    )


def validate_drift(
    migrations: list[Migration],
    applied_rows: list[asyncpg.Record],
    require_up_to_date: bool,
) -> tuple[list[str], list[str], list[str]]:
    by_version = {migration.version: migration for migration in migrations}
    applied_versions = {str(row["version"]) for row in applied_rows}
    problems: list[str] = []

    for row in applied_rows:
        version = str(row["version"])
        migration = by_version.get(version)
        if migration is None:
            problems.append(
                f"Applied migration {version}_{row['name']} does not exist in db/migrations."
            )
            continue
        if str(row["name"]) != migration.name:
            problems.append(
                f"Applied migration {version} name mismatch: db={row['name']} files={migration.name}."
            )
        if str(row["checksum"]) != migration.checksum:
            problems.append(f"Applied migration {version} checksum does not match migration file.")

    pending = [migration.version for migration in migrations if migration.version not in applied_versions]
    if require_up_to_date and pending:
        problems.append(f"Database is not up to date. Pending migrations: {', '.join(pending)}.")

    applied = [str(row["version"]) for row in applied_rows]
    return problems, applied, pending


async def command_status(
    dsn: str,
    migrations: list[Migration],
    connect_timeout_seconds: float,
) -> int:
    conn = await asyncpg.connect(dsn, timeout=connect_timeout_seconds)
    try:
        await ensure_migration_metadata(conn)
        rows = await fetch_applied_rows(conn)
        applied_versions = {str(row["version"]) for row in rows}
        print("Migration status:")
        for migration in migrations:
            state = "APPLIED" if migration.version in applied_versions else "PENDING"
            print(f"- {migration.version}_{migration.name}: {state}")
        unknown_rows = [row for row in rows if str(row["version"]) not in {m.version for m in migrations}]
        if unknown_rows:
            print("Unknown applied migrations:")
            for row in unknown_rows:
                print(f"- {row['version']}_{row['name']}")
        print(f"Applied: {len(rows)}")
        print(f"Pending: {len(migrations) - len(applied_versions.intersection({m.version for m in migrations}))}")
    finally:
        await conn.close()
    return 0


async def command_up(
    dsn: str,
    migrations: list[Migration],
    connect_timeout_seconds: float,
    target_version: str | None,
) -> int:
    by_version = {migration.version: migration for migration in migrations}
    if target_version and target_version not in by_version:
        raise ValueError(f"--to version {target_version} does not exist in db/migrations.")

    conn = await asyncpg.connect(dsn, timeout=connect_timeout_seconds)
    try:
        await ensure_migration_metadata(conn)
        await acquire_migration_lock(conn)
        try:
            applied_rows = await fetch_applied_rows(conn)
            applied_by_version = {str(row["version"]): row for row in applied_rows}

            applied_count = 0
            for migration in migrations:
                if target_version is not None and int(migration.version) > int(target_version):
                    break
                row = applied_by_version.get(migration.version)
                if row is not None:
                    if str(row["checksum"]) != migration.checksum:
                        raise RuntimeError(
                            f"Migration {migration.version}_{migration.name} was already applied "
                            "with a different checksum."
                        )
                    continue

                sql = migration.up_path.read_text(encoding="utf-8")
                print(f"Applying {migration.version}_{migration.name} ...")
                await conn.execute(sql)
                await conn.execute(
                    f"""
                    INSERT INTO {MIGRATION_META_SCHEMA}.{MIGRATION_META_TABLE} (version, name, checksum)
                    VALUES ($1, $2, $3)
                    """,
                    migration.version,
                    migration.name,
                    migration.checksum,
                )
                applied_count += 1

            print(f"Applied {applied_count} migration(s).")
        finally:
            await release_migration_lock(conn)
    finally:
        await conn.close()
    return 0


async def command_down(
    dsn: str,
    migrations: list[Migration],
    connect_timeout_seconds: float,
    steps: int | None,
    target_version: str | None,
) -> int:
    if steps is not None and steps < 1:
        raise ValueError("--steps must be >= 1.")
    if steps is not None and target_version is not None:
        raise ValueError("--steps and --to cannot be used together.")

    by_version = {migration.version: migration for migration in migrations}
    if target_version and target_version != "0" and target_version not in by_version:
        raise ValueError(f"--to version {target_version} does not exist in db/migrations.")

    conn = await asyncpg.connect(dsn, timeout=connect_timeout_seconds)
    try:
        await ensure_migration_metadata(conn)
        await acquire_migration_lock(conn)
        try:
            applied_rows = await fetch_applied_rows(conn)
            if not applied_rows:
                print("No applied migrations found.")
                return 0

            applied_versions_in_order = [str(row["version"]) for row in applied_rows]
            versions_to_rollback: list[str]
            if target_version is not None:
                if target_version == "0":
                    keep_set: set[str] = set()
                else:
                    keep_cutoff = int(target_version)
                    keep_set = {
                        version
                        for version in applied_versions_in_order
                        if int(version) <= keep_cutoff
                    }
                versions_to_rollback = [
                    version for version in reversed(applied_versions_in_order) if version not in keep_set
                ]
            else:
                effective_steps = steps if steps is not None else 1
                versions_to_rollback = list(reversed(applied_versions_in_order))[:effective_steps]

            if not versions_to_rollback:
                print("Database is already at requested rollback target.")
                return 0

            for version in versions_to_rollback:
                migration = by_version.get(version)
                if migration is None:
                    raise RuntimeError(
                        f"Applied migration version {version} has no matching file in db/migrations."
                    )
                if migration.down_path is None:
                    raise RuntimeError(
                        f"Migration {version}_{migration.name} cannot be rolled back because "
                        "it has no .down.sql file."
                    )
                sql = migration.down_path.read_text(encoding="utf-8")
                print(f"Rolling back {migration.version}_{migration.name} ...")
                await conn.execute(sql)
                await conn.execute(
                    f"DELETE FROM {MIGRATION_META_SCHEMA}.{MIGRATION_META_TABLE} WHERE version = $1",
                    migration.version,
                )
            print(f"Rolled back {len(versions_to_rollback)} migration(s).")
        finally:
            await release_migration_lock(conn)
    finally:
        await conn.close()
    return 0


async def command_drift_check(
    dsn: str,
    migrations: list[Migration],
    connect_timeout_seconds: float,
    require_up_to_date: bool,
) -> int:
    conn = await asyncpg.connect(dsn, timeout=connect_timeout_seconds)
    try:
        await ensure_migration_metadata(conn)
        rows = await fetch_applied_rows(conn)
        problems, applied, pending = validate_drift(
            migrations=migrations,
            applied_rows=rows,
            require_up_to_date=require_up_to_date,
        )
        if problems:
            print("Migration drift check failed:")
            for problem in problems:
                print(f"- {problem}")
            return 1
        print("Migration drift check passed.")
        print(f"Applied versions: {', '.join(applied) if applied else '(none)'}")
        print(f"Pending versions: {', '.join(pending) if pending else '(none)'}")
    finally:
        await conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SHAKTI PostgreSQL migration runner.")
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN. Overrides PG_DSN/PG_DSN_FILE.")
    parser.add_argument(
        "--dsn-file",
        default="",
        help="Path to a file containing PostgreSQL DSN. Overrides PG_DSN/PG_DSN_FILE.",
    )
    parser.add_argument(
        "--migrations-dir",
        default=str(default_migrations_dir()),
        help="Directory containing versioned *.up.sql/*.down.sql files.",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=parse_positive_float(
            load_text_value("SHAKTI_DB_CONNECT_TIMEOUT_SECONDS", "3"),
            "SHAKTI_DB_CONNECT_TIMEOUT_SECONDS",
        ),
        help="Per-connection timeout in seconds.",
    )
    parser.add_argument(
        "--wait-timeout-seconds",
        type=float,
        default=parse_positive_float(
            load_text_value("SHAKTI_DB_WAIT_TIMEOUT_SECONDS", "60"),
            "SHAKTI_DB_WAIT_TIMEOUT_SECONDS",
        ),
        help="Total wait timeout for the wait command in seconds.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("wait", help="Wait until PostgreSQL is reachable.")
    subparsers.add_parser("status", help="Show migration status.")

    up = subparsers.add_parser("up", help="Apply pending migrations.")
    up.add_argument("--to", default="", help="Apply migrations up to and including this version.")

    down = subparsers.add_parser("down", help="Rollback applied migrations.")
    down.add_argument("--steps", type=int, default=None, help="Rollback this many migrations.")
    down.add_argument("--to", default="", help="Rollback to this version. Use 0 to rollback all.")

    drift = subparsers.add_parser("drift-check", help="Validate migration history and checksums.")
    drift.add_argument(
        "--require-up-to-date",
        action="store_true",
        help="Fail if any local migration is pending.",
    )

    return parser


async def async_main(args: argparse.Namespace) -> int:
    dsn = resolve_dsn(args)
    connect_timeout = parse_positive_float(
        str(args.connect_timeout_seconds),
        "--connect-timeout-seconds",
    )
    wait_timeout = parse_positive_float(
        str(args.wait_timeout_seconds),
        "--wait-timeout-seconds",
    )

    if args.command == "wait":
        await wait_for_database(
            dsn=dsn,
            timeout_seconds=wait_timeout,
            connect_timeout_seconds=connect_timeout,
        )
        print("Database is ready.")
        return 0

    migrations_dir = Path(args.migrations_dir).resolve()
    migrations = discover_migrations(migrations_dir)

    if args.command == "status":
        return await command_status(
            dsn=dsn,
            migrations=migrations,
            connect_timeout_seconds=connect_timeout,
        )
    if args.command == "up":
        target_version = args.to.strip() or None
        return await command_up(
            dsn=dsn,
            migrations=migrations,
            connect_timeout_seconds=connect_timeout,
            target_version=target_version,
        )
    if args.command == "down":
        target_version = args.to.strip() or None
        return await command_down(
            dsn=dsn,
            migrations=migrations,
            connect_timeout_seconds=connect_timeout,
            steps=args.steps,
            target_version=target_version,
        )
    if args.command == "drift-check":
        return await command_drift_check(
            dsn=dsn,
            migrations=migrations,
            connect_timeout_seconds=connect_timeout,
            require_up_to_date=bool(args.require_up_to_date),
        )
    raise ValueError(f"Unsupported command: {args.command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except Exception as exc:
        print(f"Migration runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
