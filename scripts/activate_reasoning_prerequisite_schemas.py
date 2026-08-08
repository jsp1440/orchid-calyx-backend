"""Preflight or explicitly activate Reasoning Ledger prerequisite schemas.

Default behavior is read-only. Production mutation requires BOTH ``--apply`` and
``CALYX_REASONING_PREREQ_CONFIRM=APPLY_087B_088B_088C_088D_101``.

This script installs only prerequisite schema foundations. It never applies
migrations 103/105, publishes a Reasoning Ledger, or mutates the Knowledge Graph.
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
MIGRATIONS = (
    ("087b_context_preserving_interpretation.sql", "3a8273d058808bd98025270faddfdf9e8f589b7b"),
    ("088b_publication_registry_policy_foundation.sql", "10c3ab60420f7c15342691c80dbef1a039859678"),
    ("088c_atomic_graph_transaction_publication_engine.sql", "35c27b6278430ac65e70d3c9e85f77bf19c85a19"),
    ("088d_publication_lifecycle_corrections_rollback.sql", "779a2a262b20c1dfe52b80df953a802eaf546f55"),
    ("101_research_workspace_foundation.sql", "3333853c97832154cb0f61bace0c2184396da160"),
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
    "101_research_workspace_foundation.sql": (
        "research_station.projects",
    ),
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


def _relation_report(connection, qualified_name: str) -> dict[str, Any]:
    schema, table = qualified_name.split(".", 1)
    relation = connection.execute("SELECT to_regclass(%s)", (qualified_name,)).fetchone()
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
        malformed = any(report["exists"] and not report["complete"] for report in reports)
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


def classify_preflight(contract: dict[str, Any], identities_match: bool) -> dict[str, Any]:
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


def _write_receipt(receipt: dict[str, Any]) -> None:
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["artifact_hash"] = hashlib.sha256(canonical).hexdigest()
    EVIDENCE_PATH.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    import psycopg

    identities = migration_identity_report()
    identities_match = all(item["matches"] for item in identities.values())
    confirmation_present = (
        os.environ.get("CALYX_REASONING_PREREQ_CONFIRM", "").strip() == CONFIRMATION
    )

    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "preflight",
        "apply_requested": args.apply,
        "explicit_confirmation_present": confirmation_present,
        "migration_order": [filename for filename, _ in MIGRATIONS],
        "migration_identities": identities,
        "applied_migrations": [],
        "migration_results": [],
        "failed_migration": None,
        "partial_application": False,
        "production_database_mutation_authorized": bool(args.apply and confirmation_present),
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
            receipt["blockers"] = [*receipt["blockers"], "EXPLICIT_CONFIRMATION_REQUIRED"]
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
                    {"migration": filename, "status": "failed", "error_type": type(exc).__name__}
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
