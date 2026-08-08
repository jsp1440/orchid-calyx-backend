#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg

from scripts.preflight_university_activation import _database_state, preflight

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "ocu_sci_008_durable_sessions.sql"
ADVISORY_LOCK_KEY = 730090014  # OCU-SCI-009N, transaction scoped.


class MigrationGuardError(RuntimeError):
    pass


def migration_digest() -> str:
    return "sha256:" + hashlib.sha256(MIGRATION.read_bytes()).hexdigest()


def safe_database_identity(database_url: str) -> dict[str, str | None]:
    parsed = urlparse(database_url)
    return {
        "hostname": parsed.hostname,
        "port": str(parsed.port) if parsed.port is not None else None,
        "database": parsed.path.lstrip("/") or None,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MigrationGuardError(message)


def plan(*, release_evidence: Path, database_url: str) -> dict[str, Any]:
    readiness = preflight(release_evidence=release_evidence, database_url=database_url)
    database = readiness.get("database") or {}
    digest = migration_digest()
    already_valid = bool(database.get("schema_valid"))
    blockers = list(readiness.get("migration_blockers") or [])

    return {
        "contract": "OCU-SCI-009N-MIGRATION-RUNNER-001",
        "mode": "dry_run",
        "migration": {
            "path": str(MIGRATION.relative_to(ROOT)),
            "sha256": digest,
        },
        "database": safe_database_identity(database_url),
        "migration_stage_preflight": {
            "ready": bool(readiness.get("ready_to_apply_migration")),
            "blockers": blockers,
        },
        "schema_already_valid": already_valid,
        "would_apply": bool(readiness.get("ready_to_apply_migration")) and not already_valid,
        "requires_exact_confirmation": digest,
        "mutations_performed": False,
    }


def apply_migration(*, release_evidence: Path, database_url: str, confirm_migration_sha256: str) -> dict[str, Any]:
    migration_plan = plan(release_evidence=release_evidence, database_url=database_url)
    expected_digest = str(migration_plan["migration"]["sha256"])

    _require(
        confirm_migration_sha256.strip().lower() == expected_digest,
        "exact migration SHA-256 confirmation is required",
    )
    _require(
        bool(migration_plan["migration_stage_preflight"]["ready"]),
        "migration-stage preflight is blocked",
    )

    if migration_plan["schema_already_valid"]:
        return {
            **migration_plan,
            "mode": "apply",
            "would_apply": False,
            "result": "already_valid_noop",
            "mutations_performed": False,
        }

    sql = MIGRATION.read_text(encoding="utf-8")
    try:
        with psycopg.connect(database_url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
                    cur.execute(sql)

                post_state = _database_state(database_url)
                _require(bool(post_state.get("reachable")), "post-apply database verification failed: database unreachable")
                _require(bool(post_state.get("schema_valid")), "post-apply durable schema verification failed")
    except MigrationGuardError:
        raise
    except Exception as exc:
        raise MigrationGuardError(f"migration transaction failed: {exc}") from exc

    return {
        **migration_plan,
        "mode": "apply",
        "would_apply": False,
        "result": "applied_and_verified",
        "post_apply_schema_valid": True,
        "mutations_performed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Guarded transactional runner for the Orchid University durable-session migration"
    )
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-migration-sha256")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    if not args.database_url:
        print("BLOCKED: DATABASE_URL or --database-url is required")
        return 2

    try:
        if args.apply:
            if not args.confirm_migration_sha256:
                raise MigrationGuardError("--apply requires --confirm-migration-sha256")
            result = apply_migration(
                release_evidence=args.release_evidence,
                database_url=args.database_url,
                confirm_migration_sha256=args.confirm_migration_sha256,
            )
        else:
            result = plan(release_evidence=args.release_evidence, database_url=args.database_url)
    except (OSError, MigrationGuardError, ValueError) as exc:
        if args.json_output:
            print(json.dumps({"contract": "OCU-SCI-009N-MIGRATION-RUNNER-001", "result": "blocked", "error": str(exc)}, indent=2))
        else:
            print(f"BLOCKED: {exc}")
        return 1

    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(f"University durable migration runner: {result.get('result', 'DRY RUN')}")
        print(f"Migration: {result['migration']['path']}")
        print(f"SHA-256: {result['migration']['sha256']}")
        print(f"Database: {result['database']}")
        if not args.apply:
            print(f"Ready to apply: {result['migration_stage_preflight']['ready']}")
            print(f"Schema already valid: {result['schema_already_valid']}")
            print("No mutations were performed.")

    if args.apply:
        return 0
    return 0 if result["migration_stage_preflight"]["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
