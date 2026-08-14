"""Strict contract facade for atomic Research Station migration activation.

The validated activation state machine lives in
``research_station_conversation_activation_base``. This facade strengthens the
existing-schema contract checks without changing migration bytes, transaction
ordering, receipt semantics, or the canonical guarded CLI entry point.
"""

from __future__ import annotations

from typing import Any

import psycopg

try:
    from scripts import research_station_conversation_activation_base as base
except ImportError:  # direct ``python scripts/...`` execution
    import research_station_conversation_activation_base as base

_BASE_INSPECT_CONTRACT = base.inspect_contract
_BASE_APPLY_CHAIN = base.apply_chain

STRICT_CHECK_GROUPS_101: dict[str, tuple[tuple[str, ...], ...]] = {
    "projects": (
        ("char_length(title)", ">= 1", "<= 160"),
        ("char_length(description)", "<= 10000"),
        ("char_length(research_question)", "<= 5000"),
        ("char_length(hypothesis)", "<= 5000"),
        ("status", "'active'", "'paused'", "'completed'"),
        ("version", "> 0"),
    ),
    "saved_searches": (
        ("char_length(name)", ">= 1", "<= 160"),
        ("result_count_snapshot", ">= 0"),
        ("version", "> 0"),
    ),
    "notes": (
        ("char_length(title)", "<= 200"),
        ("char_length(body)", ">= 1", "<= 50000"),
        ("note_type", "'general'", "'question'", "'method'", "'observation'"),
        ("version", "> 0"),
    ),
    "project_taxa": (
        ("relationship", "'subject'", "'comparison'", "'context'", "'excluded'"),
    ),
    "project_documents": (
        ("relationship", "'source'", "'background'", "'method'", "'contradicts'"),
    ),
    "project_evidence": (
        ("evidence_kind", "'candidate'", "'aggregate'"),
        ("relationship", "'supports'", "'contradicts'", "'context'", "'review'"),
    ),
}

STRICT_CHECK_GROUPS_140: dict[str, tuple[tuple[str, ...], ...]] = {
    "conversation_sessions": (
        ("char_length(title)", ">= 1", "<= 160"),
        ("version", "> 0"),
    ),
    "conversation_messages": (
        ("role", "'operator'", "'calyx'"),
        ("char_length(content)", ">= 1", "<= 50000"),
        ("data_status", "'conversation_context'"),
        ("evidence_authority", "false"),
        ("scientific_publication_authorized", "false"),
        ("knowledge_graph_mutation_authorized", "false"),
    ),
}

INDEX_SPECS_101: dict[str, dict[str, Any]] = {
    "idx_rs_projects_owner_archive_updated": {
        "table": "projects",
        "unique": False,
        "keys": ("owner_subject", "archived_at", "updated_at DESC"),
        "predicate": None,
    },
    "idx_rs_projects_owner_status": {
        "table": "projects",
        "unique": False,
        "keys": ("owner_subject", "status"),
        "predicate": None,
    },
    "uq_rs_saved_search_name": {
        "table": "saved_searches",
        "unique": True,
        "keys": ("project_id", "lower(name)"),
        "predicate": "(archived_at IS NULL)",
    },
    "idx_rs_notes_project_updated": {
        "table": "notes",
        "unique": False,
        "keys": ("project_id", "archived_at", "updated_at DESC"),
        "predicate": None,
    },
    "idx_rs_project_taxa_id": {
        "table": "project_taxa",
        "unique": False,
        "keys": ("taxon_id",),
        "predicate": None,
    },
    "idx_rs_project_documents_id": {
        "table": "project_documents",
        "unique": False,
        "keys": ("document_id",),
        "predicate": None,
    },
    "idx_rs_project_evidence_id": {
        "table": "project_evidence",
        "unique": False,
        "keys": ("evidence_kind", "evidence_id"),
        "predicate": None,
    },
    "idx_rs_audit_project_time": {
        "table": "audit_events",
        "unique": False,
        "keys": ("project_id", "occurred_at DESC", "event_id"),
        "predicate": None,
    },
}

INDEX_SPECS_140: dict[str, dict[str, Any]] = {
    "idx_rs_conversation_owner_project_updated": {
        "table": "conversation_sessions",
        "unique": False,
        "keys": ("owner_subject", "project_id", "updated_at DESC"),
        "predicate": None,
    },
    "idx_rs_conversation_messages_session_time": {
        "table": "conversation_messages",
        "unique": False,
        "keys": ("conversation_id", "created_at", "message_id"),
        "predicate": None,
    },
}


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _normalize_index_expression(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(value.lower().split())


def _index_contracts(connection: psycopg.Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            i.relname,
            t.relname,
            ix.indisunique,
            ARRAY(
                SELECT pg_get_indexdef(ix.indexrelid, key_position, true)
                FROM generate_series(1, ix.indnkeyatts) AS key_position
                ORDER BY key_position
            ),
            pg_get_expr(ix.indpred, ix.indrelid)
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'research_station'
        """
    ).fetchall()
    return {
        row[0]: {
            "table": row[1],
            "unique": bool(row[2]),
            "keys": tuple(row[3]),
            "predicate": row[4],
        }
        for row in rows
    }


def _missing_or_mismatched_indexes(
    connection: psycopg.Connection,
    specs: dict[str, dict[str, Any]],
) -> list[str]:
    actual = _index_contracts(connection)
    failures: list[str] = []
    for name, expected in specs.items():
        observed = actual.get(name)
        if observed is None:
            failures.append(name)
            continue
        expected_keys = tuple(
            _normalize_index_expression(value) for value in expected["keys"]
        )
        observed_keys = tuple(
            _normalize_index_expression(value) for value in observed["keys"]
        )
        if (
            observed["table"] != expected["table"]
            or observed["unique"] is not expected["unique"]
            or observed_keys != expected_keys
            or _normalize_index_expression(observed["predicate"])
            != _normalize_index_expression(expected["predicate"])
        ):
            failures.append(name)
    return sorted(failures)


def _strict_index_blockers(
    connection: psycopg.Connection,
) -> tuple[list[str], list[str], list[str]]:
    missing_101 = _missing_or_mismatched_indexes(connection, INDEX_SPECS_101)
    missing_140 = _missing_or_mismatched_indexes(connection, INDEX_SPECS_140)
    blockers: list[str] = []
    if missing_101:
        blockers.append("MIGRATION_101_REQUIRED_INDEX_MISSING")
    if missing_140:
        blockers.append("MIGRATION_140_REQUIRED_INDEX_MISSING")
    return blockers, missing_101, missing_140


def _strict_constraint_blockers(
    connection: psycopg.Connection,
    report: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for prefix, groups_by_table in (
        ("MIGRATION_101", STRICT_CHECK_GROUPS_101),
        ("MIGRATION_140", STRICT_CHECK_GROUPS_140),
    ):
        for table, required_groups in groups_by_table.items():
            table_report = report["tables"][table]
            if not table_report["exists"] or not table_report["complete"]:
                continue
            definitions = [_normalize(value) for value in base._constraints(connection, table)]
            for index, fragments in enumerate(required_groups, start=1):
                normalized = tuple(fragment.lower() for fragment in fragments)
                if not any(
                    all(fragment in definition for fragment in normalized)
                    for definition in definitions
                ):
                    blockers.append(f"{prefix}_CHECK_CONSTRAINT_MISSING:{table}:{index}")
    return blockers


def inspect_contract(connection: psycopg.Connection) -> dict[str, Any]:
    report = _BASE_INSPECT_CONTRACT(connection)
    inherited_blockers = [
        blocker
        for blocker in report["blockers"]
        if blocker
        not in {
            "MIGRATION_101_REQUIRED_INDEX_MISSING",
            "MIGRATION_140_REQUIRED_INDEX_MISSING",
        }
    ]
    index_blockers, missing_101_indexes, missing_140_indexes = _strict_index_blockers(
        connection
    )
    blockers = sorted(
        set(
            inherited_blockers
            + index_blockers
            + _strict_constraint_blockers(connection, report)
        )
    )
    complete_101 = report["migration_101_complete"] and not any(
        blocker.startswith(
            (
                "MIGRATION_101_CHECK_CONSTRAINT_MISSING:",
                "MIGRATION_101_REQUIRED_INDEX_MISSING",
            )
        )
        for blocker in blockers
    )
    complete_140 = report["migration_140_complete"] and not any(
        blocker.startswith(
            (
                "MIGRATION_140_CHECK_CONSTRAINT_MISSING:",
                "MIGRATION_140_REQUIRED_INDEX_MISSING",
            )
        )
        for blocker in blockers
    )
    complete = complete_101 and complete_140 and not blockers
    any_101 = any(report["tables"][table]["exists"] for table in base.TABLES_101)
    any_140 = any(report["tables"][table]["exists"] for table in base.TABLES_140)
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
        **report,
        "state": state,
        "migration_101_complete": complete_101,
        "migration_140_complete": complete_140,
        "complete": complete,
        "safe_resume": safe_resume,
        "blockers": blockers,
        "missing_101_indexes": missing_101_indexes,
        "missing_140_indexes": missing_140_indexes,
    }


def apply_chain(
    connection: psycopg.Connection,
    *,
    inject_failure_after: str | None = None,
) -> dict[str, Any]:
    original_inspect = base.inspect_contract
    base.inspect_contract = inspect_contract
    try:
        return _BASE_APPLY_CHAIN(
            connection,
            inject_failure_after=inject_failure_after,
        )
    finally:
        base.inspect_contract = original_inspect


def run_profile(database_url: str, apply: bool, evidence_path) -> int:
    original_inspect = base.inspect_contract
    original_apply = base.apply_chain
    base.inspect_contract = inspect_contract
    base.apply_chain = apply_chain
    try:
        return base.run_profile(database_url, apply, evidence_path)
    finally:
        base.inspect_contract = original_inspect
        base.apply_chain = original_apply


def __getattr__(name: str):
    return getattr(base, name)
