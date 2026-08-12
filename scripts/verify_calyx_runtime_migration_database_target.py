from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg

from app.database import get_database_url

EVIDENCE_PATH = Path(
    os.environ.get(
        "CALYX_DB_TARGET_EVIDENCE_PATH",
        "artifacts/calyx-runtime-migration-database-target.json",
    )
)


@dataclass(frozen=True)
class TargetObservation:
    source: str
    host: str
    port: int | None
    database: str
    current_user: str
    database_oid: str
    server_version_num: str
    server_address: str | None
    server_port: int | None
    system_identifier: str | None
    species_relation_oid: str | None
    research_station_projects_oid: str | None
    transaction_read_only: str


def _runtime_source() -> str:
    if os.environ.get("PGHOST"):
        return "PGHOST"
    if os.environ.get("DATABASE_URL"):
        return "DATABASE_URL"
    return "SQLITE_FALLBACK"


def _safe_config_identity(database_url: str) -> tuple[str, int | None, str]:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("POSTGRESQL_TARGET_REQUIRED")
    database = parsed.path.lstrip("/")
    if not parsed.hostname or not database:
        raise RuntimeError("DATABASE_TARGET_IDENTITY_INCOMPLETE")
    return parsed.hostname.lower(), parsed.port or 5432, database


def _system_identifier(connection: psycopg.Connection[Any]) -> str | None:
    try:
        row = connection.execute(
            "SELECT system_identifier::text FROM pg_control_system()"
        ).fetchone()
    except psycopg.Error:
        connection.rollback()
        return None
    return str(row[0]) if row and row[0] is not None else None


def observe_target(database_url: str, *, source: str) -> TargetObservation:
    config_host, config_port, config_database = _safe_config_identity(database_url)
    with psycopg.connect(
        database_url,
        autocommit=True,
        options="-c default_transaction_read_only=on",
    ) as connection:
        transaction_read_only = connection.execute(
            "SHOW transaction_read_only"
        ).fetchone()[0]
        if transaction_read_only != "on":
            raise RuntimeError("READ_ONLY_SESSION_REQUIRED")
        row = connection.execute(
            """
            SELECT
                current_database(),
                (SELECT oid::text FROM pg_database WHERE datname = current_database()),
                current_setting('server_version_num'),
                inet_server_addr()::text,
                inet_server_port(),
                current_user,
                to_regclass('public.species')::oid::text,
                to_regclass('research_station.projects')::oid::text
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("DATABASE_TARGET_OBSERVATION_FAILED")
        return TargetObservation(
            source=source,
            host=config_host,
            port=config_port,
            database=str(row[0] or config_database),
            database_oid=str(row[1]),
            server_version_num=str(row[2]),
            server_address=str(row[3]) if row[3] is not None else None,
            server_port=int(row[4]) if row[4] is not None else None,
            current_user=str(row[5]),
            species_relation_oid=str(row[6]) if row[6] is not None else None,
            research_station_projects_oid=(
                str(row[7]) if row[7] is not None else None
            ),
            system_identifier=_system_identifier(connection),
            transaction_read_only=str(transaction_read_only),
        )


def compare_targets(
    runtime: TargetObservation,
    migration: TargetObservation,
) -> dict[str, Any]:
    config_match = (
        runtime.host == migration.host
        and runtime.port == migration.port
        and runtime.database == migration.database
    )
    cluster_match = bool(
        runtime.system_identifier
        and migration.system_identifier
        and runtime.system_identifier == migration.system_identifier
        and runtime.database_oid == migration.database_oid
        and runtime.database == migration.database
    )
    sentinel_pairs = (
        (runtime.species_relation_oid, migration.species_relation_oid),
        (
            runtime.research_station_projects_oid,
            migration.research_station_projects_oid,
        ),
    )
    sentinel_mismatches = [
        index
        for index, (runtime_oid, migration_oid) in enumerate(sentinel_pairs)
        if runtime_oid != migration_oid
    ]
    same_target = (config_match or cluster_match) and not sentinel_mismatches
    blockers: list[str] = []
    if not same_target:
        blockers.append("RUNTIME_MIGRATION_DATABASE_TARGET_NOT_PROVEN_EQUAL")
    if runtime.transaction_read_only != "on" or migration.transaction_read_only != "on":
        blockers.append("READ_ONLY_PREFLIGHT_NOT_ENFORCED")
    return {
        "same_target": same_target and not blockers,
        "config_identity_match": config_match,
        "cluster_database_identity_match": cluster_match,
        "sentinel_relation_mismatch_indexes": sentinel_mismatches,
        "blockers": blockers,
    }


def _write_receipt(receipt: dict[str, Any]) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["artifact_sha256"] = hashlib.sha256(canonical).hexdigest()
    EVIDENCE_PATH.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


def main() -> int:
    migration_url = os.environ.get("DATABASE_URL", "").strip()
    if not migration_url:
        raise SystemExit("DATABASE_URL is required")
    runtime_url = get_database_url()
    runtime_source = _runtime_source()
    if runtime_source == "SQLITE_FALLBACK":
        raise SystemExit("PostgreSQL runtime target is required")

    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_database_target_equivalence",
        "production_database_mutation_authorized": False,
        "production_database_mutation_attempted": False,
        "publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    try:
        runtime = observe_target(runtime_url, source=f"runtime:{runtime_source}")
        migration = observe_target(migration_url, source="migration:DATABASE_URL")
        comparison = compare_targets(runtime, migration)
    except (RuntimeError, psycopg.Error) as exc:
        receipt.update(
            {
                "status": "blocked",
                "blockers": [f"DATABASE_TARGET_PREFLIGHT_FAILED:{type(exc).__name__}"],
                "failure": str(exc),
            }
        )
        _write_receipt(receipt)
        return 2

    receipt.update(
        {
            "runtime_target": asdict(runtime),
            "migration_target": asdict(migration),
            "comparison": comparison,
            "status": "passed" if comparison["same_target"] else "blocked",
            "blockers": comparison["blockers"],
        }
    )
    _write_receipt(receipt)
    return 0 if comparison["same_target"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
