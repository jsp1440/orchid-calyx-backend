#!/usr/bin/env python3
"""Governed file→PostgreSQL migration utility for immutable Matrix registries.

Dry-run is the default. `--apply` is required to write missing immutable registry
packages after migration 613 is already ready. The utility never enables durable
registry mode and aborts on checksum conflicts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from runtime.matrix_identification_registry_preflight import compare_registry_records
from runtime.matrix_identification_registry_store import (
    FileMatrixRegistryStore,
    PostgresMatrixRegistryStore,
    default_registry_root,
)


def plan_registry_migration(
    file_records: list[dict[str, Any]],
    database_records: list[dict[str, Any]],
) -> dict[str, Any]:
    comparison = compare_registry_records(file_records, database_records)
    missing_keys = {
        (item["registry_id"], item["version"])
        for item in comparison["missing_in_database"]
    }
    records_by_key = {
        (str(item.get("registry_id")), str(item.get("version"))): item
        for item in file_records
        if item.get("registry_id") and item.get("version")
    }
    copy_records = [records_by_key[key] for key in sorted(missing_keys)]
    return {
        **comparison,
        "copy_count": len(copy_records),
        "copy_records": copy_records,
        "apply_allowed": not comparison["checksum_mismatches"],
    }


def execute_registry_migration(
    *,
    source: FileMatrixRegistryStore,
    destination: PostgresMatrixRegistryStore,
    apply: bool = False,
) -> dict[str, Any]:
    inspection = destination.schema_inspection()
    if not inspection.get("migration_613_schema_ready"):
        return {
            "mode": "apply" if apply else "dry_run",
            "schema_ready": False,
            "applied": False,
            "blockers": inspection.get("blockers") or ["MATRIX_REGISTRY_SCHEMA_NOT_READY"],
        }

    file_records = source.list_records()
    database_records = destination.list_records()
    plan = plan_registry_migration(file_records, database_records)
    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "schema_ready": True,
        "applied": False,
        "source_root": str(source.root),
        "plan": {
            key: value
            for key, value in plan.items()
            if key != "copy_records"
        },
        "automatic_activation": False,
    }

    if plan["checksum_mismatches"]:
        result["blockers"] = ["MATRIX_REGISTRY_CHECKSUM_MISMATCH"]
        return result
    if not apply:
        result["would_copy"] = [
            {
                "registry_id": item.get("registry_id"),
                "version": item.get("version"),
                "checksum_sha256": item.get("checksum_sha256"),
            }
            for item in plan["copy_records"]
        ]
        return result

    receipts: list[dict[str, Any]] = []
    for record in plan["copy_records"]:
        receipt = destination.save(record)
        receipts.append(
            {
                "registry_id": record.get("registry_id"),
                "version": record.get("version"),
                "checksum_sha256": record.get("checksum_sha256"),
                "created": bool(receipt.get("created")),
            }
        )

    verification = compare_registry_records(source.list_records(), destination.list_records())
    if not verification["data_copy_ready"]:
        result["blockers"] = ["MATRIX_REGISTRY_POST_COPY_VERIFICATION_FAILED"]
        result["copy_receipts"] = receipts
        result["verification"] = verification
        return result

    result["applied"] = True
    result["copy_receipts"] = receipts
    result["verification"] = verification
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run-first migration of immutable Matrix registry packages to PostgreSQL."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write missing packages after schema/checksum validation. Default is dry-run.",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Optional file registry root. Defaults to CALYX_MATRIX_REGISTRY_DIR or canonical /tmp path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print(json.dumps({"ok": False, "blockers": ["DATABASE_URL_NOT_CONFIGURED"]}, indent=2))
        return 2

    source_root = default_registry_root() if not args.source_root else __import__("pathlib").Path(args.source_root)
    result = execute_registry_migration(
        source=FileMatrixRegistryStore(source_root),
        destination=PostgresMatrixRegistryStore(dsn),
        apply=bool(args.apply),
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get("blockers"):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
