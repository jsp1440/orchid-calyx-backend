"""Preflight or explicitly activate Reasoning Ledger publication schemas.

Default behavior is read-only. Production mutation requires BOTH ``--apply`` and
``CALYX_REASONING_MIGRATION_CONFIRM=APPLY_103_105``. This script never publishes
a Reasoning Ledger and never mutates the Knowledge Graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = Path(
    os.environ.get(
        "CALYX_REASONING_MIGRATION_EVIDENCE_PATH",
        "calyx-reasoning-publication-schema-activation.json",
    )
)
CONFIRMATION = "APPLY_103_105"
MIGRATIONS = (
    ("103_reasoning_ledger.sql", "b69fb53bf0771aa3730fb8a1b1c0d7a73a7a2153"),
    (
        "105_reasoning_ledger_publication_adapter.sql",
        "d3a2fa44103a2f45f8b23a816b88496d0c88bf1e",
    ),
)
PREREQUISITES = (
    "research_station.projects",
    "oc_knowledge_publication.publication_candidates",
)
TARGETS = (
    "reasoning_ledger.ledger_heads",
    "reasoning_ledger.ledger_revisions",
    "reasoning_ledger.audit_events",
    "reasoning_publication.publication_artifacts",
    "reasoning_publication.publication_attempts",
)
REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "reasoning_ledger.ledger_heads": frozenset(
        {
            "ledger_id",
            "schema_version",
            "owner_subject",
            "project_id",
            "logical_key_hash",
            "current_version",
            "current_content_hash",
            "created_at",
            "updated_at",
        }
    ),
    "reasoning_ledger.ledger_revisions": frozenset(
        {
            "revision_id",
            "ledger_id",
            "version",
            "owner_subject",
            "project_id",
            "status",
            "entry_count",
            "content_hash",
            "canonical_payload",
            "created_at",
        }
    ),
    "reasoning_ledger.audit_events": frozenset(
        {
            "event_id",
            "ledger_id",
            "ledger_version",
            "owner_subject",
            "project_id",
            "event_type",
            "actor_subject",
            "event_payload",
            "occurred_at",
        }
    ),
    "reasoning_publication.publication_artifacts": frozenset(
        {
            "publication_artifact_id",
            "artifact_hash",
            "ledger_id",
            "ledger_version",
            "review_content_hash",
            "owner_subject",
            "project_id",
            "status",
            "snapshot",
            "canonical_publication_id",
            "canonical_graph_result",
            "failure_reason",
            "created_at",
        }
    ),
    "reasoning_publication.publication_attempts": frozenset(
        {
            "attempt_id",
            "publication_artifact_id",
            "attempt_number",
            "outcome",
            "actor",
            "details",
            "created_at",
        }
    ),
}
REQUIRED_CONSTRAINT_COUNTS: dict[str, dict[str, int]] = {
    "reasoning_ledger.ledger_heads": {"p": 1, "u": 1, "f": 1, "c": 1},
    "reasoning_ledger.ledger_revisions": {"p": 1, "u": 1, "f": 2, "c": 4},
    "reasoning_ledger.audit_events": {"p": 1, "f": 2},
    "reasoning_publication.publication_artifacts": {"p": 1, "u": 2, "f": 3, "c": 2},
    "reasoning_publication.publication_attempts": {"p": 1, "u": 1, "f": 1, "c": 1},
}
REQUIRED_INDEXES = frozenset(
    {
        "idx_reasoning_heads_owner_project",
        "idx_reasoning_revisions_owner_project",
        "idx_reasoning_audit_ledger",
        "idx_reasoning_publication_scope",
        "idx_reasoning_publication_ledger",
        "idx_reasoning_publication_attempt",
    }
)
REQUIRED_FUNCTIONS = frozenset(
    {
        "reasoning_publication.protect_published_artifact",
        "reasoning_publication.reject_attempt_mutation",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "reasoning_publication.publication_artifacts.protect_reasoning_publication_identity",
        "reasoning_publication.publication_attempts.protect_reasoning_publication_attempt",
    }
)


def _git_blob_sha(path: Path) -> str:
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def migration_identity_report() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for filename, expected_blob_sha in MIGRATIONS:
        path = ROOT / "migrations" / filename
        actual_blob_sha = _git_blob_sha(path)
        result[filename] = {
            "expected_git_blob_sha": expected_blob_sha,
            "actual_git_blob_sha": actual_blob_sha,
            "matches": actual_blob_sha == expected_blob_sha,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return result


def _relation_state(connection, names: tuple[str, ...]) -> dict[str, bool]:
    state: dict[str, bool] = {}
    for name in names:
        row = connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()
        state[name] = bool(row and row[0])
    return state


def _schema_contract(connection) -> dict[str, Any]:
    table_reports: dict[str, dict[str, Any]] = {}
    for qualified_name, required_columns in REQUIRED_COLUMNS.items():
        schema, table = qualified_name.split(".", 1)
        column_rows = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        ).fetchall()
        actual_columns = {row[0] for row in column_rows}
        missing_columns = sorted(required_columns - actual_columns)

        constraint_rows = connection.execute(
            """
            SELECT c.contype, count(*)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = %s AND t.relname = %s
            GROUP BY c.contype
            """,
            (schema, table),
        ).fetchall()
        actual_counts = {row[0]: int(row[1]) for row in constraint_rows}
        required_counts = REQUIRED_CONSTRAINT_COUNTS[qualified_name]
        missing_constraint_types = {
            key: required - actual_counts.get(key, 0)
            for key, required in required_counts.items()
            if actual_counts.get(key, 0) < required
        }
        table_reports[qualified_name] = {
            "missing_columns": missing_columns,
            "constraint_counts": actual_counts,
            "missing_constraint_counts": missing_constraint_types,
            "complete": not missing_columns and not missing_constraint_types,
        }

    index_rows = connection.execute(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname IN ('reasoning_ledger', 'reasoning_publication')
        """
    ).fetchall()
    actual_indexes = {row[0] for row in index_rows}
    missing_indexes = sorted(REQUIRED_INDEXES - actual_indexes)

    function_rows = connection.execute(
        """
        SELECT n.nspname || '.' || p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'reasoning_publication'
        """
    ).fetchall()
    actual_functions = {row[0] for row in function_rows}
    missing_functions = sorted(REQUIRED_FUNCTIONS - actual_functions)

    trigger_rows = connection.execute(
        """
        SELECT event_object_schema || '.' || event_object_table || '.' || trigger_name
        FROM information_schema.triggers
        WHERE event_object_schema = 'reasoning_publication'
        """
    ).fetchall()
    actual_triggers = {row[0] for row in trigger_rows}
    missing_triggers = sorted(REQUIRED_TRIGGERS - actual_triggers)

    complete = (
        all(item["complete"] for item in table_reports.values())
        and not missing_indexes
        and not missing_functions
        and not missing_triggers
    )
    return {
        "tables": table_reports,
        "missing_indexes": missing_indexes,
        "missing_functions": missing_functions,
        "missing_triggers": missing_triggers,
        "complete": complete,
    }


def _inspect(connection) -> dict[str, Any]:
    return {
        "prerequisites": _relation_state(connection, PREREQUISITES),
        "targets": _relation_state(connection, TARGETS),
        "schema_contract": _schema_contract(connection),
    }


def _apply_migrations(connection, *, error_type: type[BaseException]) -> tuple[list[dict[str, Any]], str | None]:
    results: list[dict[str, Any]] = []
    failed_migration: str | None = None
    for filename, _ in MIGRATIONS:
        result: dict[str, Any] = {
            "filename": filename,
            "started": True,
            "completed": False,
        }
        sql = (ROOT / "migrations" / filename).read_text(encoding="utf-8")
        try:
            connection.execute(sql)
        except error_type as exc:
            result["error_type"] = type(exc).__name__
            failed_migration = filename
            results.append(result)
            try:
                connection.rollback()
            except error_type:
                pass
            break
        else:
            result["completed"] = True
            results.append(result)
    return results, failed_migration


def _base_report(*, apply_requested: bool) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply_requested else "preflight",
        "migration_order": [filename for filename, _ in MIGRATIONS],
        "migration_identities": migration_identity_report(),
        "apply_requested": apply_requested,
        "explicit_confirmation_present": (
            os.environ.get("CALYX_REASONING_MIGRATION_CONFIRM", "") == CONFIRMATION
        ),
        "production_database_mutation_authorized": False,
        "production_database_mutation_attempted": False,
        "production_database_mutation_observed": False,
        "publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "migration_results": [],
        "applied_migrations": [],
    }


def _write(report: dict[str, Any]) -> None:
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    report["artifact_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    EVIDENCE_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


def run(*, apply_requested: bool) -> int:
    report = _base_report(apply_requested=apply_requested)
    blockers: list[str] = []

    if not all(item["matches"] for item in report["migration_identities"].values()):
        blockers.append("MIGRATION_IDENTITY_DRIFT")

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        blockers.append("DATABASE_URL_MISSING")
        report.update({"blockers": blockers, "status": "blocked"})
        _write(report)
        return 2

    if apply_requested and not report["explicit_confirmation_present"]:
        blockers.append("EXPLICIT_APPLY_CONFIRMATION_REQUIRED")

    import psycopg

    initial_inspection: dict[str, Any] | None = None
    connection_established = False
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection_established = True
            initial_inspection = _inspect(connection)
            report["prerequisites"] = initial_inspection["prerequisites"]
            report["targets_before"] = initial_inspection["targets"]
            report["schema_contract_before"] = initial_inspection["schema_contract"]
            report["activation_required"] = not initial_inspection["schema_contract"]["complete"]

            missing_prerequisites = [
                name
                for name, present in initial_inspection["prerequisites"].items()
                if not present
            ]
            blockers.extend(
                f"PREREQUISITE_MISSING:{name}" for name in missing_prerequisites
            )
            report["ready_to_apply"] = not blockers

            if apply_requested and not blockers:
                report["production_database_mutation_authorized"] = True
                report["production_database_mutation_attempted"] = True
                migration_results, failed_migration = _apply_migrations(
                    connection, error_type=psycopg.Error
                )
                report["migration_results"] = migration_results
                report["applied_migrations"] = [
                    item["filename"] for item in migration_results if item["completed"]
                ]
                if failed_migration:
                    report["failed_migration"] = failed_migration
                    blockers.append(f"MIGRATION_FAILED:{failed_migration}")
            report["applied"] = False
    except psycopg.Error as exc:
        blockers.append(f"DATABASE_OPERATION_FAILED:{type(exc).__name__}")
        report["database_error_type"] = type(exc).__name__

    if connection_established:
        try:
            with psycopg.connect(database_url, autocommit=True) as connection:
                final_inspection = _inspect(connection)
                report["targets_after"] = final_inspection["targets"]
                report["schema_contract_after"] = final_inspection["schema_contract"]
                report["activation_complete"] = final_inspection["schema_contract"]["complete"]
                before_contract = (
                    initial_inspection["schema_contract"] if initial_inspection else None
                )
                report["production_database_mutation_observed"] = bool(
                    report["applied_migrations"]
                    or (
                        report["production_database_mutation_attempted"]
                        and before_contract != final_inspection["schema_contract"]
                    )
                )
        except psycopg.Error as exc:
            blockers.append(f"POST_APPLY_INSPECTION_FAILED:{type(exc).__name__}")
            report["post_apply_inspection_error_type"] = type(exc).__name__

    if apply_requested and report["production_database_mutation_attempted"]:
        if not report.get("activation_complete", False):
            blockers.append("POST_APPLY_SCHEMA_VERIFICATION_FAILED")
        report["applied"] = bool(
            not blockers
            and report.get("activation_complete", False)
            and len(report["applied_migrations"]) == len(MIGRATIONS)
        )
        report["partial_application"] = bool(
            report["production_database_mutation_observed"] and not report["applied"]
        )
    else:
        report["partial_application"] = False

    report["blockers"] = sorted(set(blockers))
    report["status"] = "passed" if not blockers else "blocked"
    _write(report)
    return 0 if not blockers else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply migrations 103 then 105; also requires explicit confirmation env.",
    )
    args = parser.parse_args()
    return run(apply_requested=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
