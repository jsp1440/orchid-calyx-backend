"""Preflight or explicitly activate guarded prerequisite schema profiles.

The historical default remains the Reasoning Ledger prerequisite profile.
Production mutation for that profile requires BOTH ``--apply`` and
``CALYX_REASONING_PREREQ_CONFIRM=APPLY_087B_088B_088C_088D_101``.

The Research Station conversation profile is selected explicitly with
``--profile research-station-conversations``. Its mutation path requires BOTH
``--apply`` and ``CALYX_RESEARCH_STATION_CONFIRM=APPLY_RESEARCH_STATION_101_140``.
It serializes on the repository's canonical PostgreSQL advisory-lock key and
executes migrations 101 and 140 in one explicit transaction with structural
postconditions before commit.

Neither profile publishes scientific knowledge or mutates the Knowledge Graph.
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
        "CALYX_REASONING_PREREQ_EVIDENCE_PATH",
        "calyx-reasoning-prerequisite-schema-activation.json",
    )
)
CONFIRMATION = "APPLY_087B_088B_088C_088D_101"
RESEARCH_STATION_CONFIRMATION = "APPLY_RESEARCH_STATION_101_140"
POSTGRES_VALIDATION_LOCK_ID = 82078079
MIGRATIONS = (
    (
        "087b_context_preserving_interpretation.sql",
        "3a8273d058808bd98025270faddfdf9e8f589b7b",
    ),
    (
        "088b_publication_registry_policy_foundation.sql",
        "10c3ab60420f7c15342691c80dbef1a039859678",
    ),
    (
        "088c_atomic_graph_transaction_publication_engine.sql",
        "35c27b6278430ac65e70d3c9e85f77bf19c85a19",
    ),
    (
        "088d_publication_lifecycle_corrections_rollback.sql",
        "779a2a262b20c1dfe52b80df953a802eaf546f55",
    ),
    (
        "101_research_workspace_foundation.sql",
        "3333853c97832154cb0f61bace0c2184396da160",
    ),
)
RESEARCH_STATION_MIGRATIONS = (
    (
        "101_research_workspace_foundation.sql",
        "3333853c97832154cb0f61bace0c2184396da160",
    ),
    (
        "140_calyx_conversation_sessions.sql",
        "f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf",
    ),
)

PUBLICATION_CHAIN = (
    "087b_context_preserving_interpretation.sql",
    "088b_publication_registry_policy_foundation.sql",
    "088c_atomic_graph_transaction_publication_engine.sql",
    "088d_publication_lifecycle_corrections_rollback.sql",
)

MIGRATION_TARGETS: dict[str, tuple[str, ...]] = {
    "087b_context_preserving_interpretation.sql": (
        "oc_scientific_interpretation.routing_decisions",
        "oc_scientific_interpretation.canonical_assertions",
    ),
    "088b_publication_registry_policy_foundation.sql": (
        "oc_knowledge_publication.publication_candidates",
    ),
    "088c_atomic_graph_transaction_publication_engine.sql": (
        "oc_knowledge_publication.graph_versions",
    ),
    "088d_publication_lifecycle_corrections_rollback.sql": (
        "oc_knowledge_publication.publication_lineage",
    ),
    "101_research_workspace_foundation.sql": ("research_station.projects",),
}

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "oc_scientific_interpretation.routing_decisions": frozenset(
        {"routing_decision_id", "interpretation_id", "path", "fingerprint", "payload"}
    ),
    "oc_scientific_interpretation.canonical_assertions": frozenset(
        {"assertion_id", "assertion_key", "version", "fingerprint", "payload"}
    ),
    "oc_knowledge_publication.publication_candidates": frozenset(
        {
            "publication_id",
            "publication_version",
            "assertion_id",
            "eligibility_decision_id",
            "policy_version_id",
            "requested_pathway",
            "idempotency_key",
            "fingerprint",
            "trusted_snapshot",
        }
    ),
    "oc_knowledge_publication.graph_versions": frozenset(
        {
            "graph_version_id",
            "sequence",
            "graph_transaction_id",
            "status",
            "fingerprint",
        }
    ),
    "oc_knowledge_publication.publication_lineage": frozenset(
        {
            "lineage_id",
            "predecessor_publication_id",
            "successor_publication_id",
            "lineage_type",
            "fingerprint",
        }
    ),
    "research_station.projects": frozenset(
        {"project_id", "owner_subject", "title", "status", "version", "created_at"}
    ),
}

REQUIRED_FUNCTIONS = frozenset(
    {
        "oc_knowledge_publication.reject_mutation",
        "oc_knowledge_publication.enforce_lifecycle",
        "oc_knowledge_publication.enforce_policy_lifecycle",
        "research_station.reject_audit_mutation",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "oc_knowledge_publication.publication_candidates.protect_088b_publication_candidates",
        "oc_knowledge_publication.lifecycle_transitions.enforce_088b_lifecycle",
        "research_station.audit_events.rs_audit_immutable",
    }
)

RESEARCH_STATION_101_TABLES = (
    "projects",
    "saved_searches",
    "notes",
    "project_taxa",
    "project_documents",
    "project_evidence",
    "audit_events",
)
RESEARCH_STATION_140_TABLES = ("conversation_sessions", "conversation_messages")
RESEARCH_STATION_REQUIRED_COLUMNS: dict[str, dict[str, str]] = {
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
RESEARCH_STATION_REQUIRED_NOT_NULL: dict[str, frozenset[str]] = {
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
RESEARCH_STATION_REQUIRED_INDEXES = frozenset(
    {
        "idx_rs_projects_owner_archive_updated",
        "idx_rs_projects_owner_status",
        "uq_rs_saved_search_name",
        "idx_rs_notes_project_updated",
        "idx_rs_project_taxa_id",
        "idx_rs_project_documents_id",
        "idx_rs_project_evidence_id",
        "idx_rs_audit_project_time",
        "idx_rs_conversation_owner_project_updated",
        "idx_rs_conversation_messages_session_time",
    }
)


def _git_blob_sha(path: Path) -> str:
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def _identity_report(
    migrations: tuple[tuple[str, str], ...],
) -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for filename, expected_blob_sha in migrations:
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


def migration_identity_report() -> dict[str, dict[str, Any]]:
    return _identity_report(MIGRATIONS)


def research_station_migration_identity_report() -> dict[str, dict[str, Any]]:
    return _identity_report(RESEARCH_STATION_MIGRATIONS)


def _relation_report(connection, qualified_name: str) -> dict[str, Any]:
    schema, table = qualified_name.split(".", 1)
    relation = connection.execute(
        "SELECT to_regclass(%s)", (qualified_name,)
    ).fetchone()
    exists = bool(relation and relation[0])
    if not exists:
        return {
            "exists": False,
            "complete": False,
            "missing_columns": sorted(REQUIRED_COLUMNS[qualified_name]),
        }
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    ).fetchall()
    actual = {row[0] for row in rows}
    missing = sorted(REQUIRED_COLUMNS[qualified_name] - actual)
    return {"exists": True, "complete": not missing, "missing_columns": missing}


def _function_names(connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT n.nspname || '.' || p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('oc_knowledge_publication', 'research_station')
        """
    ).fetchall()
    return {row[0] for row in rows}


def _trigger_names(connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT n.nspname || '.' || c.relname || '.' || t.tgname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE NOT t.tgisinternal
          AND n.nspname IN ('oc_knowledge_publication', 'research_station')
        """
    ).fetchall()
    return {row[0] for row in rows}


def inspect_contract(connection) -> dict[str, Any]:
    relation_reports = {
        target: _relation_report(connection, target) for target in REQUIRED_COLUMNS
    }
    stage_reports: dict[str, dict[str, Any]] = {}
    for migration, targets in MIGRATION_TARGETS.items():
        reports = [relation_reports[target] for target in targets]
        exists_any = any(report["exists"] for report in reports)
        complete = all(report["complete"] for report in reports)
        malformed = any(
            report["exists"] and not report["complete"] for report in reports
        )
        stage_reports[migration] = {
            "exists_any": exists_any,
            "complete": complete,
            "malformed": malformed,
            "targets": list(targets),
        }

    publication_states = [stage_reports[name]["complete"] for name in PUBLICATION_CHAIN]
    seen_absent = False
    out_of_order = False
    for complete in publication_states:
        if not complete:
            seen_absent = True
        elif seen_absent:
            out_of_order = True

    malformed = any(stage["malformed"] for stage in stage_reports.values())
    functions = _function_names(connection)
    triggers = _trigger_names(connection)
    missing_functions = sorted(REQUIRED_FUNCTIONS - functions)
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)

    all_stages_complete = all(stage["complete"] for stage in stage_reports.values())
    auxiliary_complete = not missing_functions and not missing_triggers
    complete = all_stages_complete and auxiliary_complete
    safe_resume = not malformed and not out_of_order

    blockers: list[str] = []
    if malformed:
        blockers.append("MALFORMED_PARTIAL_PREREQUISITE_SCHEMA")
    if out_of_order:
        blockers.append("OUT_OF_ORDER_PUBLICATION_FOUNDATION")
    if all_stages_complete and not auxiliary_complete:
        blockers.append("PREREQUISITE_GOVERNANCE_OBJECTS_MISSING")

    return {
        "relations": relation_reports,
        "stages": stage_reports,
        "missing_functions": missing_functions,
        "missing_triggers": missing_triggers,
        "malformed_partial_schema": malformed,
        "out_of_order_publication_foundation": out_of_order,
        "safe_resume": safe_resume,
        "complete": complete,
        "blockers": blockers,
    }


def classify_preflight(
    contract: dict[str, Any], identities_match: bool
) -> dict[str, Any]:
    if not identities_match:
        return {
            "status": "blocked",
            "activation_required": not contract["complete"],
            "ready_to_apply": False,
            "blockers": ["MIGRATION_IDENTITY_DRIFT", *contract["blockers"]],
        }
    if contract["complete"]:
        return {
            "status": "passed",
            "activation_required": False,
            "ready_to_apply": False,
            "blockers": [],
        }
    if not contract["safe_resume"] or contract["blockers"]:
        return {
            "status": "blocked",
            "activation_required": True,
            "ready_to_apply": False,
            "blockers": list(contract["blockers"]),
        }
    return {
        "status": "ready",
        "activation_required": True,
        "ready_to_apply": True,
        "blockers": [],
    }


def _rs_table_report(connection, table: str) -> dict[str, Any]:
    expected = RESEARCH_STATION_REQUIRED_COLUMNS[table]
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
        for name, data_type in expected.items()
        if name in actual and actual[name]["data_type"] != data_type
    )
    required_not_null = RESEARCH_STATION_REQUIRED_NOT_NULL.get(table, frozenset())
    nullability_mismatches = sorted(
        name
        for name in required_not_null
        if name in actual and actual[name]["is_nullable"] != "NO"
    )
    complete = not missing and not wrong_types and not nullability_mismatches
    return {
        "exists": True,
        "complete": complete,
        "missing_columns": missing,
        "wrong_types": wrong_types,
        "nullability_mismatches": nullability_mismatches,
    }


def _rs_constraints(connection, table: str) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
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
    ]


def _rs_index_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='research_station'"
        ).fetchall()
    }


def _rs_trigger_locations(connection, trigger_name: str) -> list[dict[str, str]]:
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
    return [
        {"schema": row[0], "table": row[1], "definition": row[2]} for row in rows
    ]


def inspect_research_station_conversation_contract(connection) -> dict[str, Any]:
    tables = {
        table: _rs_table_report(connection, table)
        for table in (*RESEARCH_STATION_101_TABLES, *RESEARCH_STATION_140_TABLES)
    }
    prereq_reports = [tables[table] for table in RESEARCH_STATION_101_TABLES]
    target_reports = [tables[table] for table in RESEARCH_STATION_140_TABLES]
    prereq_exists_any = any(report["exists"] for report in prereq_reports)
    target_exists_any = any(report["exists"] for report in target_reports)
    prereq_complete = all(report["complete"] for report in prereq_reports)
    target_complete = all(report["complete"] for report in target_reports)

    blockers: list[str] = []
    if prereq_exists_any and not prereq_complete:
        blockers.append("MALFORMED_OR_PARTIAL_MIGRATION_101_STATE")
    if target_exists_any and not target_complete:
        blockers.append("MALFORMED_OR_PARTIAL_MIGRATION_140_STATE")
    if target_exists_any and not prereq_complete:
        blockers.append("MIGRATION_140_PRESENT_WITHOUT_CANONICAL_101")

    indexes = _rs_index_names(connection)
    if prereq_complete or target_complete:
        expected_indexes = {
            name
            for name in RESEARCH_STATION_REQUIRED_INDEXES
            if (
                prereq_complete
                or name
                in {
                    "idx_rs_conversation_owner_project_updated",
                    "idx_rs_conversation_messages_session_time",
                }
            )
        }
        missing_indexes = sorted(expected_indexes - indexes)
        if missing_indexes:
            blockers.append("REQUIRED_RESEARCH_STATION_INDEX_MISSING")
    else:
        missing_indexes = []

    projects_constraints = "\n".join(_rs_constraints(connection, "projects"))
    sessions_constraints = "\n".join(
        _rs_constraints(connection, "conversation_sessions")
    )
    messages_constraints = "\n".join(
        _rs_constraints(connection, "conversation_messages")
    )
    if prereq_complete and "PRIMARY KEY (project_id)" not in projects_constraints:
        blockers.append("PROJECT_PRIMARY_KEY_MISSING")
    if target_complete:
        required_fragments = {
            "SESSION_PRIMARY_KEY_MISSING": (
                "PRIMARY KEY (conversation_id)",
                sessions_constraints,
            ),
            "PROJECT_FOREIGN_KEY_MISSING": (
                "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
                sessions_constraints,
            ),
            "MESSAGE_PRIMARY_KEY_MISSING": (
                "PRIMARY KEY (message_id)",
                messages_constraints,
            ),
            "SESSION_FOREIGN_KEY_MISSING": (
                "FOREIGN KEY (conversation_id) REFERENCES research_station.conversation_sessions(conversation_id)",
                messages_constraints,
            ),
            "CONVERSATION_CONTEXT_CHECK_MISSING": (
                "CONVERSATION_CONTEXT",
                messages_constraints,
            ),
            "EVIDENCE_AUTHORITY_CHECK_MISSING": (
                "evidence_authority = false",
                messages_constraints.lower(),
            ),
            "PUBLICATION_AUTHORITY_CHECK_MISSING": (
                "scientific_publication_authorized = false",
                messages_constraints.lower(),
            ),
            "KG_AUTHORITY_CHECK_MISSING": (
                "knowledge_graph_mutation_authorized = false",
                messages_constraints.lower(),
            ),
        }
        blockers.extend(
            code
            for code, (fragment, text) in required_fragments.items()
            if fragment not in text
        )

    audit_triggers = _rs_trigger_locations(connection, "rs_audit_immutable")
    conversation_triggers = _rs_trigger_locations(
        connection, "rs_conversation_messages_immutable"
    )
    if prereq_complete:
        valid_audit = [
            trigger
            for trigger in audit_triggers
            if trigger["schema"] == "research_station"
            and trigger["table"] == "audit_events"
            and "BEFORE DELETE OR UPDATE" in trigger["definition"]
            and "research_station.reject_audit_mutation()" in trigger["definition"]
        ]
        if len(valid_audit) != 1 or len(audit_triggers) != 1:
            blockers.append("AUDIT_IMMUTABLE_TRIGGER_INVALID")
    if target_complete:
        valid_conversation = [
            trigger
            for trigger in conversation_triggers
            if trigger["schema"] == "research_station"
            and trigger["table"] == "conversation_messages"
            and "BEFORE DELETE OR UPDATE" in trigger["definition"]
            and "research_station.reject_conversation_message_mutation()"
            in trigger["definition"]
        ]
        if len(valid_conversation) != 1 or len(conversation_triggers) != 1:
            blockers.append("CONVERSATION_IMMUTABLE_TRIGGER_INVALID")

    if prereq_complete:
        audit_function = connection.execute(
            "SELECT to_regprocedure('research_station.reject_audit_mutation()')"
        ).fetchone()[0]
        if not audit_function:
            blockers.append("AUDIT_REJECT_FUNCTION_MISSING")
    if target_complete:
        conversation_function = connection.execute(
            "SELECT to_regprocedure('research_station.reject_conversation_message_mutation()')"
        ).fetchone()[0]
        if not conversation_function:
            blockers.append("CONVERSATION_REJECT_FUNCTION_MISSING")

    public_privileges = connection.execute(
        """
        SELECT table_name, privilege_type
        FROM information_schema.table_privileges
        WHERE table_schema='research_station' AND grantee='PUBLIC'
        ORDER BY table_name, privilege_type
        """
    ).fetchall()
    if (prereq_complete or target_complete) and public_privileges:
        blockers.append("PUBLIC_PRIVILEGE_PRESENT")

    complete = prereq_complete and target_complete and not blockers
    safe_resume = not blockers and (
        (not prereq_exists_any and not target_exists_any)
        or (prereq_complete and not target_exists_any)
        or complete
    )
    if complete:
        state = "COMPLETE_101_140"
    elif prereq_complete and not target_exists_any:
        state = "COMPLETE_101_ONLY"
    elif not prereq_exists_any and not target_exists_any:
        state = "ABSENT"
    else:
        state = "MALFORMED_OR_OUT_OF_ORDER"
    return {
        "state": state,
        "tables": tables,
        "migration_101_complete": prereq_complete,
        "migration_140_complete": target_complete,
        "complete": complete,
        "safe_resume": safe_resume,
        "blockers": sorted(set(blockers)),
        "missing_indexes": missing_indexes,
        "audit_trigger_locations": audit_triggers,
        "conversation_trigger_locations": conversation_triggers,
        "public_privileges": [list(row) for row in public_privileges],
    }


def classify_research_station_preflight(
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


def apply_research_station_conversation_chain(
    connection,
    *,
    inject_failure_after: str | None = None,
) -> dict[str, Any]:
    """Apply exact migration 101->140 under one transaction and xact advisory lock."""
    identities = research_station_migration_identity_report()
    if not all(item["matches"] for item in identities.values()):
        raise RuntimeError("MIGRATION_IDENTITY_DRIFT")

    applied: list[str] = []
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(%s)", (POSTGRES_VALIDATION_LOCK_ID,)
        )
        before = inspect_research_station_conversation_contract(connection)
        preflight = classify_research_station_preflight(before, identities_match=True)
        if preflight["status"] == "blocked":
            raise RuntimeError(
                "RESEARCH_STATION_PREFLIGHT_BLOCKED:"
                + ",".join(preflight["blockers"])
            )
        if preflight["status"] == "passed":
            return {
                "applied_migrations": [],
                "contract_before": before,
                "contract_after": before,
                "already_complete": True,
            }

        if not before["migration_101_complete"]:
            filename = RESEARCH_STATION_MIGRATIONS[0][0]
            connection.execute((ROOT / "migrations" / filename).read_text())
            applied.append(filename)
            after_101 = inspect_research_station_conversation_contract(connection)
            if not after_101["migration_101_complete"] or after_101["blockers"]:
                raise RuntimeError("MIGRATION_101_POSTCONDITION_FAILED")
            if inject_failure_after == "101":
                raise RuntimeError("INTENTIONAL_FAILURE_AFTER_101")

        filename = RESEARCH_STATION_MIGRATIONS[1][0]
        connection.execute((ROOT / "migrations" / filename).read_text())
        applied.append(filename)
        after = inspect_research_station_conversation_contract(connection)
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


def _write_receipt(receipt: dict[str, Any]) -> None:
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["artifact_hash"] = hashlib.sha256(canonical).hexdigest()
    EVIDENCE_PATH.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


def _run_research_station_profile(database_url: str, apply: bool) -> int:
    import psycopg

    identities = research_station_migration_identity_report()
    identities_match = all(item["matches"] for item in identities.values())
    confirmation_present = (
        os.environ.get("CALYX_RESEARCH_STATION_CONFIRM", "").strip()
        == RESEARCH_STATION_CONFIRMATION
    )
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "profile": "research-station-conversations",
        "mode": "apply" if apply else "preflight",
        "apply_requested": apply,
        "explicit_confirmation_present": confirmation_present,
        "migration_order": [name for name, _ in RESEARCH_STATION_MIGRATIONS],
        "migration_identities": identities,
        "serialization": {
            "mechanism": "pg_advisory_xact_lock",
            "lock_id": POSTGRES_VALIDATION_LOCK_ID,
        },
        "transaction_scope": "single_transaction_101_through_140_postconditions",
        "production_database_mutation_authorized": bool(
            apply and confirmation_present
        ),
        "production_database_mutation_attempted": False,
        "publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    with psycopg.connect(database_url, autocommit=True) as connection:
        before = inspect_research_station_conversation_contract(connection)
        preflight = classify_research_station_preflight(before, identities_match)
        receipt["contract_before"] = before
        receipt.update(preflight)
        if not apply:
            _write_receipt(receipt)
            return 0 if preflight["status"] in {"ready", "passed"} else 2
        if not confirmation_present:
            receipt["status"] = "blocked"
            receipt["ready_to_apply"] = False
            receipt["blockers"] = [
                *receipt["blockers"],
                "EXPLICIT_CONFIRMATION_REQUIRED",
            ]
            _write_receipt(receipt)
            return 2
        if not identities_match or not preflight["ready_to_apply"]:
            receipt["status"] = "blocked"
            _write_receipt(receipt)
            return 2
        receipt["production_database_mutation_attempted"] = True
        try:
            result = apply_research_station_conversation_chain(connection)
        except Exception as exc:
            receipt["status"] = "blocked"
            receipt["activation_complete"] = False
            receipt["failure_type"] = type(exc).__name__
            receipt["failure"] = str(exc)
            receipt["contract_after_rollback"] = (
                inspect_research_station_conversation_contract(connection)
            )
            _write_receipt(receipt)
            return 2
        receipt["applied_migrations"] = result["applied_migrations"]
        receipt["contract_after"] = result["contract_after"]
        receipt["activation_complete"] = result["contract_after"]["complete"]
        receipt["status"] = "passed" if receipt["activation_complete"] else "blocked"
        receipt["activation_required"] = False
        receipt["ready_to_apply"] = False
        receipt["blockers"] = [] if receipt["activation_complete"] else [
            "POST_APPLY_CONTRACT_INCOMPLETE"
        ]
        _write_receipt(receipt)
        return 0 if receipt["activation_complete"] else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--profile",
        choices=("reasoning-prerequisites", "research-station-conversations"),
        default="reasoning-prerequisites",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    if args.profile == "research-station-conversations":
        return _run_research_station_profile(database_url, args.apply)

    import psycopg

    identities = migration_identity_report()
    identities_match = all(item["matches"] for item in identities.values())
    confirmation_present = (
        os.environ.get("CALYX_REASONING_PREREQ_CONFIRM", "").strip() == CONFIRMATION
    )

    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "profile": "reasoning-prerequisites",
        "mode": "apply" if args.apply else "preflight",
        "apply_requested": args.apply,
        "explicit_confirmation_present": confirmation_present,
        "migration_order": [filename for filename, _ in MIGRATIONS],
        "migration_identities": identities,
        "applied_migrations": [],
        "migration_results": [],
        "failed_migration": None,
        "partial_application": False,
        "production_database_mutation_authorized": bool(
            args.apply and confirmation_present
        ),
        "production_database_mutation_attempted": False,
        "production_database_mutation_observed": False,
        "publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "reasoning_103_105_authorized": False,
    }

    with psycopg.connect(database_url, autocommit=True) as connection:
        before = inspect_contract(connection)
        preflight = classify_preflight(before, identities_match)
        receipt["contract_before"] = before
        receipt.update(preflight)

        if not args.apply:
            _write_receipt(receipt)
            return 0 if preflight["status"] in {"passed", "ready"} else 2

        if not confirmation_present:
            receipt["status"] = "blocked"
            receipt["ready_to_apply"] = False
            receipt["blockers"] = [
                *receipt["blockers"],
                "EXPLICIT_CONFIRMATION_REQUIRED",
            ]
            _write_receipt(receipt)
            return 2
        if not identities_match or not preflight["ready_to_apply"]:
            receipt["status"] = "blocked"
            _write_receipt(receipt)
            return 2

        receipt["production_database_mutation_attempted"] = True
        for filename, _ in MIGRATIONS:
            try:
                connection.execute((ROOT / "migrations" / filename).read_text())
            except psycopg.Error as exc:
                receipt["failed_migration"] = filename
                receipt["migration_results"].append(
                    {
                        "migration": filename,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    }
                )
                break
            receipt["applied_migrations"].append(filename)
            receipt["migration_results"].append(
                {"migration": filename, "status": "completed"}
            )

        after = inspect_contract(connection)
        receipt["contract_after"] = after
        receipt["production_database_mutation_observed"] = before != after
        receipt["partial_application"] = bool(
            receipt["applied_migrations"] and not after["complete"]
        )
        if receipt["failed_migration"] or not after["complete"]:
            receipt["status"] = "blocked"
            receipt["activation_complete"] = False
            if receipt["failed_migration"]:
                receipt["blockers"] = [
                    *receipt["blockers"],
                    f"MIGRATION_FAILED:{receipt['failed_migration']}",
                ]
            if not after["complete"]:
                receipt["blockers"] = [
                    *receipt["blockers"],
                    "POST_APPLY_CONTRACT_INCOMPLETE",
                ]
            _write_receipt(receipt)
            return 2

        receipt["status"] = "passed"
        receipt["activation_complete"] = True
        receipt["activation_required"] = False
        receipt["ready_to_apply"] = False
        receipt["blockers"] = []
        _write_receipt(receipt)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
