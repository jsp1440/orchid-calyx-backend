"""Atomic Research Station migration-101 -> migration-140 activation profile.

This module is invoked only through the repository's canonical guarded schema
activation CLI. It has no independent command-line entry point.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[1]
CONFIRMATION = "APPLY_RESEARCH_STATION_101_140"
POSTGRES_VALIDATION_LOCK_ID = 82078079
MIGRATIONS = (
    (
        "101_research_workspace_foundation.sql",
        "3333853c97832154cb0f61bace0c2184396da160",
    ),
    (
        "140_calyx_conversation_sessions.sql",
        "f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf",
    ),
)
TABLES_101 = (
    "projects",
    "saved_searches",
    "notes",
    "project_taxa",
    "project_documents",
    "project_evidence",
    "audit_events",
)
TABLES_140 = ("conversation_sessions", "conversation_messages")
COLUMN_TYPES: dict[str, dict[str, str]] = {
    "projects": {
        "project_id": "uuid",
        "owner_subject": "text",
        "title": "text",
        "description": "text",
        "research_question": "text",
        "hypothesis": "text",
        "status": "text",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
        "archived_at": "timestamp with time zone",
        "version": "integer",
    },
    "saved_searches": {
        "saved_search_id": "uuid",
        "project_id": "uuid",
        "owner_subject": "text",
        "name": "text",
        "query_json": "jsonb",
        "result_count_snapshot": "integer",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
        "archived_at": "timestamp with time zone",
        "version": "integer",
    },
    "notes": {
        "note_id": "uuid",
        "project_id": "uuid",
        "owner_subject": "text",
        "title": "text",
        "body": "text",
        "note_type": "text",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
        "archived_at": "timestamp with time zone",
        "version": "integer",
    },
    "project_taxa": {
        "project_id": "uuid",
        "taxon_id": "text",
        "relationship": "text",
        "created_at": "timestamp with time zone",
        "created_by_subject": "text",
    },
    "project_documents": {
        "project_id": "uuid",
        "document_id": "text",
        "revision_id": "text",
        "relationship": "text",
        "created_at": "timestamp with time zone",
        "created_by_subject": "text",
    },
    "project_evidence": {
        "project_id": "uuid",
        "evidence_kind": "text",
        "evidence_id": "text",
        "relationship": "text",
        "created_at": "timestamp with time zone",
        "created_by_subject": "text",
    },
    "audit_events": {
        "event_id": "uuid",
        "project_id": "uuid",
        "actor_subject": "text",
        "action": "text",
        "entity_type": "text",
        "entity_id": "text",
        "occurred_at": "timestamp with time zone",
        "request_correlation_id": "text",
        "change_summary": "jsonb",
    },
    "conversation_sessions": {
        "conversation_id": "uuid",
        "owner_subject": "text",
        "project_id": "uuid",
        "title": "text",
        "active_taxon_id": "text",
        "active_document_id": "text",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
        "archived_at": "timestamp with time zone",
        "version": "integer",
    },
    "conversation_messages": {
        "message_id": "uuid",
        "conversation_id": "uuid",
        "owner_subject": "text",
        "role": "text",
        "content": "text",
        "epistemic_status": "text",
        "context_json": "jsonb",
        "source_refs_json": "jsonb",
        "tool_trace_json": "jsonb",
        "data_status": "text",
        "evidence_authority": "boolean",
        "scientific_publication_authorized": "boolean",
        "knowledge_graph_mutation_authorized": "boolean",
        "created_at": "timestamp with time zone",
    },
}
NOT_NULL: dict[str, frozenset[str]] = {
    "projects": frozenset(
        {
            "project_id",
            "owner_subject",
            "title",
            "description",
            "status",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "saved_searches": frozenset(
        {
            "saved_search_id",
            "project_id",
            "owner_subject",
            "name",
            "query_json",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "notes": frozenset(
        {
            "note_id",
            "project_id",
            "owner_subject",
            "body",
            "note_type",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "project_taxa": frozenset(
        {
            "project_id",
            "taxon_id",
            "relationship",
            "created_at",
            "created_by_subject",
        }
    ),
    "project_documents": frozenset(
        {
            "project_id",
            "document_id",
            "relationship",
            "created_at",
            "created_by_subject",
        }
    ),
    "project_evidence": frozenset(
        {
            "project_id",
            "evidence_kind",
            "evidence_id",
            "relationship",
            "created_at",
            "created_by_subject",
        }
    ),
    "audit_events": frozenset(
        {
            "event_id",
            "project_id",
            "actor_subject",
            "action",
            "entity_type",
            "entity_id",
            "occurred_at",
            "change_summary",
        }
    ),
    "conversation_sessions": frozenset(
        {
            "conversation_id",
            "owner_subject",
            "title",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "conversation_messages": frozenset(
        {
            "message_id",
            "conversation_id",
            "owner_subject",
            "role",
            "content",
            "context_json",
            "source_refs_json",
            "tool_trace_json",
            "data_status",
            "evidence_authority",
            "scientific_publication_authorized",
            "knowledge_graph_mutation_authorized",
            "created_at",
        }
    ),
}
DEFAULT_FRAGMENTS: dict[str, dict[str, str]] = {
    "projects": {
        "project_id": "gen_random_uuid",
        "description": "''::text",
        "status": "'ACTIVE'::text",
        "created_at": "now()",
        "updated_at": "now()",
        "version": "1",
    },
    "saved_searches": {
        "saved_search_id": "gen_random_uuid",
        "created_at": "now()",
        "updated_at": "now()",
        "version": "1",
    },
    "notes": {
        "note_id": "gen_random_uuid",
        "note_type": "'GENERAL'::text",
        "created_at": "now()",
        "updated_at": "now()",
        "version": "1",
    },
    "project_taxa": {"relationship": "'SUBJECT'::text", "created_at": "now()"},
    "project_documents": {
        "relationship": "'SOURCE'::text",
        "created_at": "now()",
    },
    "project_evidence": {
        "relationship": "'SUPPORTS'::text",
        "created_at": "now()",
    },
    "audit_events": {
        "event_id": "gen_random_uuid",
        "occurred_at": "now()",
        "change_summary": "'{}'::jsonb",
    },
    "conversation_sessions": {
        "conversation_id": "gen_random_uuid",
        "title": "'New conversation'::text",
        "created_at": "now()",
        "updated_at": "now()",
        "version": "1",
    },
    "conversation_messages": {
        "message_id": "gen_random_uuid",
        "context_json": "'{}'::jsonb",
        "source_refs_json": "'[]'::jsonb",
        "tool_trace_json": "'[]'::jsonb",
        "data_status": "'CONVERSATION_CONTEXT'::text",
        "evidence_authority": "false",
        "scientific_publication_authorized": "false",
        "knowledge_graph_mutation_authorized": "false",
        "created_at": "now()",
    },
}
INDEXES_101 = frozenset(
    {
        "idx_rs_projects_owner_archive_updated",
        "idx_rs_projects_owner_status",
        "uq_rs_saved_search_name",
        "idx_rs_notes_project_updated",
        "idx_rs_project_taxa_id",
        "idx_rs_project_documents_id",
        "idx_rs_project_evidence_id",
        "idx_rs_audit_project_time",
    }
)
INDEXES_140 = frozenset(
    {
        "idx_rs_conversation_owner_project_updated",
        "idx_rs_conversation_messages_session_time",
    }
)
CONSTRAINT_FRAGMENTS: dict[str, tuple[str, ...]] = {
    "projects": ("PRIMARY KEY (project_id)",),
    "saved_searches": (
        "PRIMARY KEY (saved_search_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "notes": (
        "PRIMARY KEY (note_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "project_taxa": (
        "PRIMARY KEY (project_id, taxon_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "project_documents": (
        "PRIMARY KEY (project_id, document_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "project_evidence": (
        "PRIMARY KEY (project_id, evidence_kind, evidence_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "audit_events": (
        "PRIMARY KEY (event_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "conversation_sessions": (
        "PRIMARY KEY (conversation_id)",
        "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
    ),
    "conversation_messages": (
        "PRIMARY KEY (message_id)",
        "FOREIGN KEY (conversation_id) REFERENCES research_station.conversation_sessions(conversation_id)",
        "CONVERSATION_CONTEXT",
        "evidence_authority = false",
        "scientific_publication_authorized = false",
        "knowledge_graph_mutation_authorized = false",
    ),
}


def _git_blob_sha(path: Path) -> str:
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def migration_identity_report() -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for filename, expected_blob_sha in MIGRATIONS:
        path = ROOT / "migrations" / filename
        content = path.read_bytes()
        actual_blob_sha = _git_blob_sha(path)
        report[filename] = {
            "expected_git_blob_sha": expected_blob_sha,
            "actual_git_blob_sha": actual_blob_sha,
            "matches": actual_blob_sha == expected_blob_sha,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return report


def _table_report(connection, table: str) -> dict[str, Any]:
    expected = COLUMN_TYPES[table]
    exists = bool(
        connection.execute(
            "SELECT to_regclass(%s)", (f"research_station.{table}",)
        ).fetchone()[0]
    )
    if not exists:
        return {
            "exists": False,
            "complete": False,
            "missing_columns": sorted(expected),
            "wrong_types": [],
            "nullability_mismatches": [],
            "default_mismatches": [],
        }
    rows = connection.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='research_station' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    actual = {
        row[0]: {
            "data_type": row[1],
            "is_nullable": row[2],
            "column_default": row[3],
        }
        for row in rows
    }
    missing = sorted(set(expected) - set(actual))
    wrong_types = sorted(
        name
        for name, expected_type in expected.items()
        if name in actual and actual[name]["data_type"] != expected_type
    )
    nullability_mismatches = sorted(
        name
        for name in NOT_NULL[table]
        if name in actual and actual[name]["is_nullable"] != "NO"
    )
    default_mismatches = sorted(
        name
        for name, fragment in DEFAULT_FRAGMENTS.get(table, {}).items()
        if name in actual and fragment not in str(actual[name]["column_default"])
    )
    complete = not (
        missing or wrong_types or nullability_mismatches or default_mismatches
    )
    return {
        "exists": True,
        "complete": complete,
        "missing_columns": missing,
        "wrong_types": wrong_types,
        "nullability_mismatches": nullability_mismatches,
        "default_mismatches": default_mismatches,
    }


def _constraints(connection, table: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname='research_station' AND t.relname=%s
        ORDER BY c.conname
        """,
        (table,),
    ).fetchall()
    return [row[0] for row in rows]


def _index_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='research_station'"
        ).fetchall()
    }


def _trigger_locations(connection, trigger_name: str) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT n.nspname, c.relname, pg_get_triggerdef(t.oid)
        FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE NOT t.tgisinternal AND t.tgname=%s
        ORDER BY n.nspname, c.relname
        """,
        (trigger_name,),
    ).fetchall()
    return [{"schema": row[0], "table": row[1], "definition": row[2]} for row in rows]


def inspect_contract(connection) -> dict[str, Any]:
    tables = {
        table: _table_report(connection, table) for table in (*TABLES_101, *TABLES_140)
    }
    reports_101 = [tables[table] for table in TABLES_101]
    reports_140 = [tables[table] for table in TABLES_140]
    any_101 = any(report["exists"] for report in reports_101)
    any_140 = any(report["exists"] for report in reports_140)
    columns_101 = all(report["complete"] for report in reports_101)
    columns_140 = all(report["complete"] for report in reports_140)
    blockers: list[str] = []

    if any_101 and not columns_101:
        blockers.append("MALFORMED_OR_PARTIAL_MIGRATION_101_STATE")
    if any_140 and not columns_140:
        blockers.append("MALFORMED_OR_PARTIAL_MIGRATION_140_STATE")
    if any_140 and not columns_101:
        blockers.append("MIGRATION_140_PRESENT_WITHOUT_CANONICAL_101")

    if columns_101:
        for table in TABLES_101:
            definitions = "\n".join(_constraints(connection, table)).lower()
            for fragment in CONSTRAINT_FRAGMENTS[table]:
                if fragment.lower() not in definitions:
                    blockers.append(f"MIGRATION_101_CONSTRAINT_MISSING:{table}")
    if columns_140:
        for table in TABLES_140:
            definitions = "\n".join(_constraints(connection, table)).lower()
            for fragment in CONSTRAINT_FRAGMENTS[table]:
                if fragment.lower() not in definitions:
                    blockers.append(f"MIGRATION_140_CONSTRAINT_MISSING:{table}")

    indexes = _index_names(connection)
    missing_101_indexes = sorted(INDEXES_101 - indexes) if columns_101 else []
    missing_140_indexes = sorted(INDEXES_140 - indexes) if columns_140 else []
    if missing_101_indexes:
        blockers.append("MIGRATION_101_REQUIRED_INDEX_MISSING")
    if missing_140_indexes:
        blockers.append("MIGRATION_140_REQUIRED_INDEX_MISSING")

    audit_triggers = _trigger_locations(connection, "rs_audit_immutable")
    conversation_triggers = _trigger_locations(
        connection, "rs_conversation_messages_immutable"
    )
    if any(
        (item["schema"], item["table"]) != ("research_station", "audit_events")
        for item in audit_triggers
    ):
        blockers.append("AUDIT_TRIGGER_NAME_COLLISION")
    if any(
        (item["schema"], item["table"]) != ("research_station", "conversation_messages")
        for item in conversation_triggers
    ):
        blockers.append("CONVERSATION_TRIGGER_NAME_COLLISION")

    if columns_101:
        valid_audit = [
            item
            for item in audit_triggers
            if (item["schema"], item["table"]) == ("research_station", "audit_events")
            and "BEFORE DELETE OR UPDATE" in item["definition"]
            and "research_station.reject_audit_mutation()" in item["definition"]
        ]
        if len(valid_audit) != 1 or len(audit_triggers) != 1:
            blockers.append("AUDIT_IMMUTABLE_TRIGGER_INVALID")
        if not connection.execute(
            "SELECT to_regprocedure('research_station.reject_audit_mutation()')"
        ).fetchone()[0]:
            blockers.append("AUDIT_REJECT_FUNCTION_MISSING")
    if columns_140:
        valid_conversation = [
            item
            for item in conversation_triggers
            if (item["schema"], item["table"])
            == ("research_station", "conversation_messages")
            and "BEFORE DELETE OR UPDATE" in item["definition"]
            and "research_station.reject_conversation_message_mutation()"
            in item["definition"]
        ]
        if len(valid_conversation) != 1 or len(conversation_triggers) != 1:
            blockers.append("CONVERSATION_IMMUTABLE_TRIGGER_INVALID")
        if not connection.execute(
            "SELECT to_regprocedure('research_station.reject_conversation_message_mutation()')"
        ).fetchone()[0]:
            blockers.append("CONVERSATION_REJECT_FUNCTION_MISSING")

    public_privileges = connection.execute(
        """
        SELECT table_name, privilege_type
        FROM information_schema.table_privileges
        WHERE table_schema='research_station' AND grantee='PUBLIC'
        ORDER BY table_name, privilege_type
        """
    ).fetchall()
    if public_privileges:
        blockers.append("PUBLIC_PRIVILEGE_PRESENT")

    complete_101 = columns_101 and not any(
        blocker.startswith(("MIGRATION_101_", "AUDIT_")) for blocker in blockers
    )
    complete_140 = columns_140 and not any(
        blocker.startswith(("MIGRATION_140_", "CONVERSATION_")) for blocker in blockers
    )
    complete = complete_101 and complete_140 and not blockers
    safe_resume = not blockers and (
        (not any_101 and not any_140) or (complete_101 and not any_140) or complete
    )
    if complete:
        state = "COMPLETE_101_140"
    elif complete_101 and not any_140:
        state = "COMPLETE_101_ONLY"
    elif not any_101 and not any_140 and not blockers:
        state = "ABSENT"
    else:
        state = "MALFORMED_OR_OUT_OF_ORDER"
    return {
        "state": state,
        "tables": tables,
        "migration_101_complete": complete_101,
        "migration_140_complete": complete_140,
        "complete": complete,
        "safe_resume": safe_resume,
        "blockers": sorted(set(blockers)),
        "missing_101_indexes": missing_101_indexes,
        "missing_140_indexes": missing_140_indexes,
        "audit_trigger_locations": audit_triggers,
        "conversation_trigger_locations": conversation_triggers,
        "public_privileges": [list(row) for row in public_privileges],
    }


def classify_preflight(
    contract: dict[str, Any], identities_match: bool
) -> dict[str, Any]:
    blockers = list(contract["blockers"])
    if not identities_match:
        blockers.insert(0, "MIGRATION_IDENTITY_DRIFT")
    if blockers or not contract["safe_resume"]:
        return {
            "status": "blocked",
            "activation_required": not contract["complete"],
            "ready_to_apply": False,
            "blockers": sorted(set(blockers)),
        }
    if contract["complete"]:
        return {
            "status": "passed",
            "activation_required": False,
            "ready_to_apply": False,
            "blockers": [],
        }
    return {
        "status": "ready",
        "activation_required": True,
        "ready_to_apply": True,
        "blockers": [],
    }


def apply_chain(
    connection: psycopg.Connection,
    *,
    inject_failure_after: str | None = None,
) -> dict[str, Any]:
    identities = migration_identity_report()
    if not all(item["matches"] for item in identities.values()):
        raise RuntimeError("MIGRATION_IDENTITY_DRIFT")
    applied: list[str] = []
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(%s)", (POSTGRES_VALIDATION_LOCK_ID,)
        )
        before = inspect_contract(connection)
        preflight = classify_preflight(before, identities_match=True)
        if preflight["status"] == "blocked":
            raise RuntimeError(
                "RESEARCH_STATION_PREFLIGHT_BLOCKED:" + ",".join(preflight["blockers"])
            )
        if preflight["status"] == "passed":
            return {
                "applied_migrations": [],
                "contract_before": before,
                "contract_after": before,
                "already_complete": True,
            }

        if not before["migration_101_complete"]:
            filename = MIGRATIONS[0][0]
            connection.execute((ROOT / "migrations" / filename).read_text())
            applied.append(filename)
            after_101 = inspect_contract(connection)
            if not after_101["migration_101_complete"] or after_101["blockers"]:
                raise RuntimeError(
                    "MIGRATION_101_POSTCONDITION_FAILED:"
                    + ",".join(after_101["blockers"])
                )
            if inject_failure_after == "101":
                raise RuntimeError("INTENTIONAL_FAILURE_AFTER_101")

        filename = MIGRATIONS[1][0]
        connection.execute((ROOT / "migrations" / filename).read_text())
        applied.append(filename)
        after = inspect_contract(connection)
        if not after["complete"]:
            raise RuntimeError(
                "MIGRATION_140_POSTCONDITION_FAILED:" + ",".join(after["blockers"])
            )
        if inject_failure_after == "140":
            raise RuntimeError("INTENTIONAL_FAILURE_AFTER_140")
        return {
            "applied_migrations": applied,
            "contract_before": before,
            "contract_after": after,
            "already_complete": False,
        }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["artifact_hash"] = hashlib.sha256(canonical).hexdigest()
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


def run_profile(database_url: str, apply: bool, evidence_path: Path) -> int:
    identities = migration_identity_report()
    identities_match = all(item["matches"] for item in identities.values())
    confirmation_present = (
        os.environ.get("CALYX_RESEARCH_STATION_CONFIRM", "").strip() == CONFIRMATION
    )
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "profile": "research-station-conversations",
        "mode": "apply" if apply else "preflight",
        "apply_requested": apply,
        "explicit_confirmation_present": confirmation_present,
        "migration_order": [name for name, _ in MIGRATIONS],
        "migration_identities": identities,
        "serialization": {
            "mechanism": "pg_advisory_xact_lock",
            "lock_id": POSTGRES_VALIDATION_LOCK_ID,
        },
        "transaction_scope": "single_transaction_101_through_140_postconditions",
        "production_database_mutation_authorized": bool(apply and confirmation_present),
        "production_database_mutation_attempted": False,
        "publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    with psycopg.connect(database_url, autocommit=True) as connection:
        before = inspect_contract(connection)
        preflight = classify_preflight(before, identities_match)
        receipt["contract_before"] = before
        receipt.update(preflight)
        if not apply:
            _write_receipt(evidence_path, receipt)
            return 0 if preflight["status"] in {"ready", "passed"} else 2
        if not confirmation_present:
            receipt["status"] = "blocked"
            receipt["ready_to_apply"] = False
            receipt["blockers"] = [
                *receipt["blockers"],
                "EXPLICIT_CONFIRMATION_REQUIRED",
            ]
            _write_receipt(evidence_path, receipt)
            return 2
        if not identities_match or not preflight["ready_to_apply"]:
            receipt["status"] = "blocked"
            _write_receipt(evidence_path, receipt)
            return 2
        receipt["production_database_mutation_attempted"] = True
        try:
            result = apply_chain(connection)
        except (RuntimeError, psycopg.Error) as exc:
            receipt["status"] = "blocked"
            receipt["activation_complete"] = False
            receipt["failure_type"] = type(exc).__name__
            receipt["failure"] = str(exc)
            receipt["contract_after_rollback"] = inspect_contract(connection)
            _write_receipt(evidence_path, receipt)
            return 2
        receipt["applied_migrations"] = result["applied_migrations"]
        receipt["contract_after"] = result["contract_after"]
        receipt["activation_complete"] = result["contract_after"]["complete"]
        receipt["status"] = "passed" if receipt["activation_complete"] else "blocked"
        receipt["activation_required"] = False
        receipt["ready_to_apply"] = False
        receipt["blockers"] = (
            [] if receipt["activation_complete"] else ["POST_APPLY_CONTRACT_INCOMPLETE"]
        )
        _write_receipt(evidence_path, receipt)
        return 0 if receipt["activation_complete"] else 2
