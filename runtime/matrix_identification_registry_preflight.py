"""Read-only activation preflight for durable Matrix registry persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runtime.matrix_identification_registry import compute_registry_record_checksum
from runtime.matrix_identification_registry_store import (
    FileMatrixRegistryStore,
    PostgresMatrixRegistryStore,
    default_registry_root,
    registry_durable_requested,
)

PREFLIGHT_SCHEMA_VERSION = "matrix-identification-registry-persistence-preflight/v2"


def strict_file_registry_inventory(root: Path) -> dict[str, Any]:
    """Read every physical registry package and independently verify its checksum."""
    records: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    paths = sorted(root.glob("*/*.json")) if root.exists() else []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(
                {
                    "code": "MATRIX_REGISTRY_SOURCE_PACKAGE_UNREADABLE",
                    "path": str(path),
                    "error_type": type(exc).__name__,
                }
            )
            continue

        registry_id = str(record.get("registry_id") or "").strip()
        version = str(record.get("version") or "").strip()
        claimed = str(record.get("checksum_sha256") or "").strip()
        if not registry_id or not version or not claimed:
            blockers.append(
                {
                    "code": "MATRIX_REGISTRY_SOURCE_PACKAGE_INCOMPLETE",
                    "path": str(path),
                    "registry_id": registry_id or None,
                    "version": version or None,
                }
            )
            continue

        actual = compute_registry_record_checksum(record)
        if actual != claimed:
            blockers.append(
                {
                    "code": "MATRIX_REGISTRY_SOURCE_CHECKSUM_INVALID",
                    "path": str(path),
                    "registry_id": registry_id,
                    "version": version,
                    "claimed_checksum_sha256": claimed,
                    "computed_checksum_sha256": actual,
                }
            )
            continue
        records.append(record)

    return {
        "physical_package_count": len(paths),
        "valid_package_count": len(records),
        "records": records,
        "blockers": blockers,
        "inventory_complete": not blockers and len(records) == len(paths),
    }


def compare_registry_records(
    file_records: list[dict[str, Any]],
    database_records: list[dict[str, Any]],
) -> dict[str, Any]:
    def keyed(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (str(item.get("registry_id") or ""), str(item.get("version") or "")): item
            for item in records
            if item.get("registry_id") and item.get("version")
        }

    file_by = keyed(file_records)
    db_by = keyed(database_records)
    missing_in_database = [
        {"registry_id": key[0], "version": key[1], "checksum_sha256": file_by[key].get("checksum_sha256")}
        for key in sorted(set(file_by) - set(db_by))
    ]
    checksum_mismatches = [
        {
            "registry_id": key[0],
            "version": key[1],
            "file_checksum_sha256": file_by[key].get("checksum_sha256"),
            "database_checksum_sha256": db_by[key].get("checksum_sha256"),
        }
        for key in sorted(set(file_by) & set(db_by))
        if file_by[key].get("checksum_sha256") != db_by[key].get("checksum_sha256")
    ]
    database_only = [
        {"registry_id": key[0], "version": key[1], "checksum_sha256": db_by[key].get("checksum_sha256")}
        for key in sorted(set(db_by) - set(file_by))
    ]
    return {
        "file_registry_count": len(file_by),
        "database_registry_count": len(db_by),
        "missing_in_database": missing_in_database,
        "checksum_mismatches": checksum_mismatches,
        "database_only": database_only,
        "data_copy_ready": not missing_in_database and not checksum_mismatches,
    }


def matrix_registry_persistence_preflight() -> dict[str, Any]:
    requested = registry_durable_requested()
    dsn = os.getenv("DATABASE_URL", "").strip()
    base: dict[str, Any] = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "database_url_configured": bool(dsn),
        "durable_requested": requested,
        "activated": False,
        "migration_613_schema_ready": False,
        "source_inventory_ready": False,
        "data_copy_ready": False,
        "activation_ready": False,
        "migration_applied_by_preflight": False,
        "data_copied_by_preflight": False,
        "environment_changed_by_preflight": False,
        "governance_boundary": (
            "Apply migration 613, copy/verify existing immutable registry packages, and enable CALYX_MATRIX_REGISTRY_DURABLE_ENABLED as separate governed deployment actions."
        ),
    }
    if not dsn:
        base["blockers"] = ["DATABASE_URL_NOT_CONFIGURED"]
        return base

    postgres_store = PostgresMatrixRegistryStore(dsn)
    inspection = postgres_store.schema_inspection()
    base.update(inspection)
    if not inspection.get("migration_613_schema_ready"):
        base["blockers"] = inspection.get("blockers") or ["MATRIX_REGISTRY_SCHEMA_NOT_READY"]
        return base

    inventory = strict_file_registry_inventory(default_registry_root())
    base["source_inventory"] = {key: value for key, value in inventory.items() if key != "records"}
    base["source_inventory_ready"] = bool(inventory["inventory_complete"])
    if not inventory["inventory_complete"]:
        base["blockers"] = [item["code"] for item in inventory["blockers"]]
        return base

    try:
        database_records = postgres_store.list_records()
    except Exception as exc:
        base["blockers"] = ["MATRIX_REGISTRY_COPY_VERIFICATION_FAILED"]
        base["error_type"] = type(exc).__name__
        return base

    comparison = compare_registry_records(inventory["records"], database_records)
    base.update(comparison)
    blockers: list[str] = []
    if comparison["missing_in_database"]:
        blockers.append("MATRIX_REGISTRY_VERSIONS_MISSING_IN_DATABASE")
    if comparison["checksum_mismatches"]:
        blockers.append("MATRIX_REGISTRY_CHECKSUM_MISMATCH")
    base["blockers"] = blockers
    base["activation_ready"] = bool(
        inspection.get("migration_613_schema_ready")
        and inventory["inventory_complete"]
        and comparison["data_copy_ready"]
    )
    base["activated"] = bool(requested and base["activation_ready"])
    return base
