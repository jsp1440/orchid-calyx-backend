#!/usr/bin/env python3
"""Guarded deployment orchestrator for Matrix durable scientific-trail persistence.

Dry-run is the default. `--apply` performs only the database/data-copy phase:
1. apply migration 612 (sessions),
2. apply migration 613 (immutable registries),
3. strict-copy file-backed registry packages to PostgreSQL,
4. run integrated readiness verification.

It NEVER mutates Render/service environment variables. Persistent activation remains
an environment/deployment operation performed after this script reports
`activation_ready_after_apply=true`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg

from runtime.matrix_identification_durability_readiness import matrix_durability_readiness
from runtime.matrix_identification_registry_store import (
    FileMatrixRegistryStore,
    PostgresMatrixRegistryStore,
    default_registry_root,
)
from scripts.calyx_matrix_registry_migrate import execute_registry_migration

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    (612, ROOT / "migrations" / "612_matrix_identification_sessions.sql"),
    (613, ROOT / "migrations" / "613_matrix_identification_registry_versions.sql"),
)
ACTIVATION_FLAGS = (
    "CALYX_MATRIX_REGISTRY_DURABLE_ENABLED",
    "CALYX_MATRIX_SESSION_DURABLE_ENABLED",
)


def migration_inventory() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for number, path in MIGRATIONS:
        items.append(
            {
                "migration": number,
                "path": str(path),
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else 0,
            }
        )
    return items


def _read_migration(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"MATRIX_MIGRATION_FILE_MISSING:{path.name}")
    sql = path.read_text(encoding="utf-8").strip()
    if not sql:
        raise RuntimeError(f"MATRIX_MIGRATION_FILE_EMPTY:{path.name}")
    return sql


def apply_migrations(dsn: str) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    with psycopg.connect(dsn) as conn:
        for number, path in MIGRATIONS:
            sql = _read_migration(path)
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            receipts.append({"migration": number, "applied": True, "path": str(path)})
    return receipts


def deployment_plan() -> dict[str, Any]:
    dsn = os.getenv("DATABASE_URL", "").strip()
    try:
        readiness = matrix_durability_readiness()
        readiness_error = None
    except Exception as exc:  # read-only probe must not prevent dry-run inventory
        readiness = None
        readiness_error = type(exc).__name__
    return {
        "mode": "dry_run",
        "database_url_configured": bool(dsn),
        "migrations": migration_inventory(),
        "integrated_readiness": readiness,
        "integrated_readiness_error": readiness_error,
        "apply_would_perform": [
            "apply migration 612",
            "apply migration 613",
            "strict-copy missing immutable registry packages",
            "post-copy integrated readiness verification",
        ],
        "apply_would_not_perform": [
            "change Render/service environment variables",
            "enable durable registry mode",
            "enable durable session mode",
            "activate live Vision inference",
            "publish or alter taxonomic/scientific evidence",
        ],
        "required_persistent_activation_flags_after_successful_apply": {
            ACTIVATION_FLAGS[0]: "true",
            ACTIVATION_FLAGS[1]: "true",
        },
    }


def _failure(plan: dict[str, Any], code: str, *, error: Exception | None = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        **plan,
        "mode": "apply",
        "applied": False,
        "blockers": [code],
        "activation_flags_changed": False,
        **extra,
    }
    if error is not None:
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
    return result


def execute_deployment(*, apply: bool = False, source_root: Path | None = None) -> dict[str, Any]:
    plan = deployment_plan()
    if not apply:
        return plan

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        return _failure(plan, "DATABASE_URL_NOT_CONFIGURED")
    missing_migrations = [item for item in plan["migrations"] if not item["exists"]]
    if missing_migrations:
        return _failure(
            plan,
            "MATRIX_MIGRATION_FILE_MISSING",
            missing_migrations=missing_migrations,
        )

    try:
        receipts = apply_migrations(dsn)
    except Exception as exc:
        return _failure(plan, "MATRIX_MIGRATION_APPLY_FAILED", error=exc)

    try:
        source = FileMatrixRegistryStore(source_root or default_registry_root())
        destination = PostgresMatrixRegistryStore(dsn)
        migration_result = execute_registry_migration(
            source=source,
            destination=destination,
            apply=True,
        )
    except Exception as exc:
        return _failure(
            plan,
            "MATRIX_REGISTRY_COPY_EXECUTION_FAILED",
            error=exc,
            migration_receipts=receipts,
        )

    if migration_result.get("blockers") or not migration_result.get("applied"):
        return {
            **plan,
            "mode": "apply",
            "applied": False,
            "migration_receipts": receipts,
            "registry_copy": migration_result,
            "blockers": migration_result.get("blockers") or ["MATRIX_REGISTRY_COPY_NOT_CONFIRMED"],
            "activation_flags_changed": False,
        }

    try:
        readiness = matrix_durability_readiness()
    except Exception as exc:
        return _failure(
            plan,
            "MATRIX_POST_APPLY_READINESS_FAILED",
            error=exc,
            migration_receipts=receipts,
            registry_copy=migration_result,
        )

    components = readiness.get("components") or {}
    registry_preflight = (components.get("registry") or {}).get("preflight") or {}
    session_preflight = (components.get("session") or {}).get("preflight") or {}
    activation_ready = bool(
        registry_preflight.get("activation_ready")
        and session_preflight.get("activation_ready")
    )
    blockers: list[str] = []
    if not activation_ready:
        blockers.append("MATRIX_POST_APPLY_ACTIVATION_READINESS_FAILED")

    return {
        "mode": "apply",
        "applied": not blockers,
        "migration_receipts": receipts,
        "registry_copy": migration_result,
        "post_apply_readiness": readiness,
        "activation_ready_after_apply": activation_ready,
        "blockers": blockers,
        "activation_flags_changed": False,
        "next_persistent_environment_values": {
            ACTIVATION_FLAGS[0]: "true",
            ACTIVATION_FLAGS[1]: "true",
        } if activation_ready else {},
        "activation_order": [
            ACTIVATION_FLAGS[0],
            ACTIVATION_FLAGS[1],
        ],
        "post_activation_verification_endpoint": "/api/matrix-identification/persistence-readiness",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run-first Matrix durability deployment orchestrator."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply migrations 612/613 and strict-copy registry packages. Does not set durable flags.",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Optional source registry directory; defaults to CALYX_MATRIX_REGISTRY_DIR/canonical path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = execute_deployment(
        apply=bool(args.apply),
        source_root=Path(args.source_root) if args.source_root else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 3 if result.get("blockers") else 0


if __name__ == "__main__":
    sys.exit(main())
