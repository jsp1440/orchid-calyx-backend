"""Read-only activation preflight for durable Matrix registry persistence."""

from __future__ import annotations

import os
from typing import Any

from runtime.matrix_identification_registry_store import (
    FileMatrixRegistryStore,
    PostgresMatrixRegistryStore,
    default_registry_root,
    registry_durable_requested,
)

PREFLIGHT_SCHEMA_VERSION = "matrix-identification-registry-persistence-preflight/v1"


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

    try:
        file_records = FileMatrixRegistryStore(default_registry_root()).list_records()
        database_records = postgres_store.list_records()
    except Exception as exc:
        base["blockers"] = ["MATRIX_REGISTRY_COPY_VERIFICATION_FAILED"]
        base["error_type"] = type(exc).__name__
        return base

    comparison = compare_registry_records(file_records, database_records)
    base.update(comparison)
    blockers: list[str] = []
    if comparison["missing_in_database"]:
        blockers.append("MATRIX_REGISTRY_VERSIONS_MISSING_IN_DATABASE")
    if comparison["checksum_mismatches"]:
        blockers.append("MATRIX_REGISTRY_CHECKSUM_MISMATCH")
    base["blockers"] = blockers
    base["activation_ready"] = bool(
        inspection.get("migration_613_schema_ready") and comparison["data_copy_ready"]
    )
    base["activated"] = bool(requested and base["activation_ready"])
    return base
