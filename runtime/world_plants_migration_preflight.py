"""Read-only preflight for the durable World Plants staging migration.

The preflight inspects PostgreSQL metadata only. It never applies DDL, writes
staging rows, activates taxonomy, or mutates the Knowledge Graph.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import get_engine

MIGRATION_ID = "107_world_plants_release_staging"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / f"{MIGRATION_ID}.sql"
)
REQUIRED_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "releases": frozenset(
        {
            "release_id",
            "source_sha256",
            "version_label",
            "filename",
            "acquired_at",
            "source_encoding",
            "source_row_count",
            "source_payload",
            "state",
            "automatic_promotion",
            "created_at",
            "updated_at",
        }
    ),
    "staged_taxa": frozenset(
        {
            "release_id",
            "source_row_number",
            "taxon_code",
            "world_plants_number",
            "scientific_name",
            "row_checksum",
            "normalized_payload",
        }
    ),
    "staging_checkpoints": frozenset(
        {
            "release_id",
            "next_row_index",
            "staged_count",
            "completed",
            "updated_at",
        }
    ),
    "change_reports": frozenset(
        {
            "release_id",
            "baseline_release_id",
            "report",
            "generated_at",
        }
    ),
    "review_queue": frozenset(
        {
            "release_id",
            "review_key",
            "category",
            "summary",
            "evidence",
            "status",
            "created_at",
            "updated_at",
        }
    ),
}
REQUIRED_INDEXES = frozenset(
    {
        "idx_taxonomy_staged_taxa_identity",
        "idx_taxonomy_review_queue_open",
    }
)


def migration_sha256() -> str:
    """Return the fingerprint of the exact migration artifact under review."""
    return hashlib.sha256(MIGRATION_PATH.read_bytes()).hexdigest()


def _next_job(
    *,
    state: str,
    can_create_database_objects: bool,
) -> dict[str, Any]:
    if state == "migration_verified":
        return {
            "job": "run_taxonomy_staging_smoke",
            "action": (
                "Run a bounded staging smoke verification against the verified schema "
                "before staging the real Hassler release."
            ),
            "requires_owner_approval": True,
            "governance_boundary": "production_database_write",
        }
    if state == "migration_required" and can_create_database_objects:
        return {
            "job": "apply_migration_107",
            "action": (
                "Apply migration 107 to the production staging database, then rerun this "
                "read-only preflight before any taxonomy staging write."
            ),
            "requires_owner_approval": True,
            "governance_boundary": "production_database_migration",
        }
    if state == "migration_required":
        return {
            "job": "resolve_taxonomy_migration_privileges",
            "action": (
                "Provide a database role with CREATE privilege for the taxonomy staging schema "
                "before migration 107 can be applied."
            ),
            "requires_owner_approval": True,
            "governance_boundary": "production_database_access",
        }
    if state == "partial_schema_detected":
        return {
            "job": "review_partial_taxonomy_schema",
            "action": (
                "Review the partial taxonomy_pipeline schema before applying any corrective DDL; "
                "CREATE TABLE IF NOT EXISTS cannot safely repair missing columns."
            ),
            "requires_owner_approval": True,
            "governance_boundary": "production_database_repair",
        }
    return {
        "job": "configure_postgresql_taxonomy_target",
        "action": "Configure a PostgreSQL target before migration preflight can proceed.",
        "requires_owner_approval": False,
    }


def inspect_world_plants_migration(engine: Engine | None = None) -> dict[str, Any]:
    """Inspect migration readiness using PostgreSQL catalog reads only."""
    target = engine or get_engine()
    if target.dialect.name != "postgresql":
        state = "non_postgresql_target"
        return {
            "migration_id": MIGRATION_ID,
            "migration_sha256": migration_sha256(),
            "state": state,
            "database_dialect": target.dialect.name,
            "schema_exists": False,
            "schema_complete": False,
            "missing_tables": sorted(REQUIRED_TABLE_COLUMNS),
            "missing_columns": {},
            "missing_indexes": sorted(REQUIRED_INDEXES),
            "can_create_database_objects": False,
            "next_job": _next_job(
                state=state,
                can_create_database_objects=False,
            ),
            "read_only": True,
            "automatic_promotion": False,
            "no_schema_mutation": True,
        }

    with target.connect() as connection:
        server_version = connection.execute(text("SHOW server_version")).scalar_one()
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()
        schema_exists = bool(
            connection.execute(
                text("SELECT to_regnamespace('taxonomy_pipeline') IS NOT NULL")
            ).scalar_one()
        )
        database_create = bool(
            connection.execute(
                text(
                    "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
                )
            ).scalar_one()
        )
        schema_create = False
        if schema_exists:
            schema_create = bool(
                connection.execute(
                    text(
                        "SELECT has_schema_privilege(current_user, 'taxonomy_pipeline', 'CREATE')"
                    )
                ).scalar_one()
            )

        rows = connection.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'taxonomy_pipeline'
                """
            )
        ).all()
        present_columns: dict[str, set[str]] = {}
        for table_name, column_name in rows:
            present_columns.setdefault(str(table_name), set()).add(str(column_name))

        indexes = {
            str(value)
            for value in connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'taxonomy_pipeline'"
                )
            ).scalars()
        }

    missing_tables = sorted(
        table for table in REQUIRED_TABLE_COLUMNS if table not in present_columns
    )
    missing_columns = {
        table: sorted(required - present_columns.get(table, set()))
        for table, required in REQUIRED_TABLE_COLUMNS.items()
        if required - present_columns.get(table, set()) and table in present_columns
    }
    missing_indexes = sorted(REQUIRED_INDEXES - indexes)
    schema_complete = (
        schema_exists
        and not missing_tables
        and not missing_columns
        and not missing_indexes
    )

    if schema_complete:
        state = "migration_verified"
    elif schema_exists:
        state = "partial_schema_detected"
    else:
        state = "migration_required"

    can_create = database_create if not schema_exists else schema_create
    return {
        "migration_id": MIGRATION_ID,
        "migration_sha256": migration_sha256(),
        "state": state,
        "database_dialect": target.dialect.name,
        "database_name": str(database_name),
        "server_version": str(server_version),
        "schema_exists": schema_exists,
        "schema_complete": schema_complete,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "can_create_database_objects": can_create,
        "next_job": _next_job(
            state=state,
            can_create_database_objects=can_create,
        ),
        "read_only": True,
        "automatic_promotion": False,
        "no_schema_mutation": True,
    }
