#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.mission_control_access.qualification_registry import (
    QualificationRegistryError,
    reviewer_qualification_claims,
)
from app.university.config import env_bool, learner_auth_enabled, university_enabled
from app.university.durable_config import valid_release_evidence_id
from scripts.validate_university_release_evidence import (
    EvidenceError,
    evidence_digest,
    validate_evidence,
)

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "lab_sessions": {
        "session_id", "laboratory_id", "chapter_id", "learner_actor", "status",
        "current_stage", "revision", "publication_allowed",
        "automatic_candidate_knowledge", "human_review_required", "created_at", "updated_at",
    },
    "session_events": {
        "event_id", "session_id", "sequence_no", "event_type", "stage", "payload",
        "actor", "session_revision", "created_at",
    },
    "session_reviews": {
        "review_id", "session_id", "reviewer_actor", "reviewer_capability",
        "reviewer_roles", "reviewer_qualifications", "decision", "notes",
        "reviewed_revision", "candidate_knowledge_promoted", "publication_performed", "created_at",
    },
}

REQUIRED_CONSTRAINT_FRAGMENTS = (
    "publication_allowed = false",
    "automatic_candidate_knowledge = false",
    "human_review_required = true",
    "candidate_knowledge_promoted = false",
    "publication_performed = false",
)

REQUIRED_NOT_NULL_COLUMNS: dict[str, set[str]] = {
    "lab_sessions": {
        "session_id", "laboratory_id", "chapter_id", "learner_actor", "status",
        "current_stage", "revision", "publication_allowed",
        "automatic_candidate_knowledge", "human_review_required", "created_at", "updated_at",
    },
    "session_events": {
        "event_id", "session_id", "sequence_no", "event_type", "stage", "payload",
        "actor", "session_revision", "created_at",
    },
    "session_reviews": {
        "review_id", "session_id", "reviewer_actor", "reviewer_capability",
        "reviewer_roles", "reviewer_qualifications", "decision",
        "reviewed_revision", "candidate_knowledge_promoted", "publication_performed", "created_at",
    },
}

PREFLIGHT_STATEMENT_TIMEOUT_MS = 30_000


def _release_evidence_state(path: Path | None) -> dict[str, Any]:
    configured = os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID", "").strip()
    state: dict[str, Any] = {
        "configured_id_present": bool(configured),
        "configured_id_valid": valid_release_evidence_id(configured),
        "artifact_supplied": path is not None,
        "artifact_valid": False,
        "artifact_matches_configured_id": False,
    }
    if path is None:
        return state
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvidenceError("evidence root must be a JSON object")
        validate_evidence(payload)
        digest = evidence_digest(path)
    except (OSError, json.JSONDecodeError, EvidenceError, ValueError, TypeError) as exc:
        state["error"] = str(exc)
        return state
    state["artifact_valid"] = True
    state["artifact_matches_configured_id"] = bool(configured and digest == configured)
    state["artifact_digest"] = digest
    return state


def _reviewer_registry_state() -> dict[str, Any]:
    raw = os.getenv("MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON", "").strip()
    if not raw:
        return {
            "configured": False,
            "valid": True,
            "subject_count": 0,
            "science_grant_count": 0,
            "expert_grant_count": 0,
            "publication_grant_count": 0,
        }
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise QualificationRegistryError("INVALID_REVIEWER_QUALIFICATION_REGISTRY")
        counts = {
            "qualified.science-reviewer": 0,
            "qualified.expert-reviewer": 0,
            "qualified.publication-reviewer": 0,
        }
        for subject_id in payload:
            claims = reviewer_qualification_claims(str(subject_id), auth_source="owner_session")
            for qualification in claims.qualifications:
                counts[qualification] += 1
        return {
            "configured": True,
            "valid": True,
            "subject_count": len(payload),
            "science_grant_count": counts["qualified.science-reviewer"],
            "expert_grant_count": counts["qualified.expert-reviewer"],
            "publication_grant_count": counts["qualified.publication-reviewer"],
        }
    except (json.JSONDecodeError, QualificationRegistryError, TypeError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "subject_count": 0,
            "science_grant_count": 0,
            "expert_grant_count": 0,
            "publication_grant_count": 0,
            "error": getattr(exc, "code", str(exc)),
        }


def _database_state(database_url: str | None) -> dict[str, Any]:
    if not database_url:
        return {"configured": False, "reachable": False, "schema_valid": False}
    try:
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as conn, conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = '{PREFLIGHT_STATEMENT_TIMEOUT_MS}ms'")
            cur.execute(
                """
                SELECT table_name, column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema='oc_university'
                  AND table_name IN ('lab_sessions','session_events','session_reviews')
                """
            )
            found: dict[str, set[str]] = {name: set() for name in REQUIRED_COLUMNS}
            nullable_found: dict[str, set[str]] = {name: set() for name in REQUIRED_NOT_NULL_COLUMNS}
            for row in cur.fetchall():
                tname = str(row["table_name"])
                cname = str(row["column_name"])
                found[tname].add(cname)
                if str(row["is_nullable"]).upper() == "YES":
                    nullable_found[tname].add(cname)
            cur.execute(
                """
                SELECT pg_get_constraintdef(c.oid) AS definition
                FROM pg_constraint c
                JOIN pg_namespace n ON n.oid=c.connamespace
                WHERE n.nspname='oc_university'
                """
            )
            constraint_text = "\n".join(str(row["definition"]).lower() for row in cur.fetchall())
    except Exception as exc:
        return {"configured": True, "reachable": False, "schema_valid": False, "error": str(exc)}

    missing_columns = {
        table: sorted(required - found.get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
        if required - found.get(table, set())
    }
    missing_constraints = [fragment for fragment in REQUIRED_CONSTRAINT_FRAGMENTS if fragment not in constraint_text]
    nullable_required = {
        table: sorted(required & nullable_found.get(table, set()))
        for table, required in REQUIRED_NOT_NULL_COLUMNS.items()
        if required & nullable_found.get(table, set())
    }
    return {
        "configured": True,
        "reachable": True,
        "schema_valid": not missing_columns and not missing_constraints and not nullable_required,
        "missing_columns": missing_columns,
        "missing_constraint_fragments": missing_constraints,
        "nullable_required_columns": nullable_required,
    }


def preflight(*, release_evidence: Path | None = None, database_url: str | None = None) -> dict[str, Any]:
    writes_enabled = env_bool("OCU_UNIVERSITY_SESSION_WRITES_ENABLED", False)
    durable_flag_enabled = env_bool("OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED", False)
    environment = {
        "university_enabled": university_enabled(),
        "learner_auth_enabled": learner_auth_enabled(),
        "session_writes_enabled": writes_enabled,
        "durable_flag_enabled": durable_flag_enabled,
        "read_only_release_verified": env_bool("OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED", False),
        "supabase_url_present": bool(os.getenv("OCU_SUPABASE_URL", "").strip()),
        "supabase_anon_key_present": bool(os.getenv("OCU_SUPABASE_ANON_KEY", "").strip()),
        "safe_pre_activation_flags": not writes_enabled and not durable_flag_enabled,
    }
    evidence = _release_evidence_state(release_evidence)
    database = _database_state(database_url or os.getenv("DATABASE_URL"))
    reviewer_registry = _reviewer_registry_state()

    migration_blockers: list[str] = []
    if not environment["university_enabled"]:
        migration_blockers.append("OCU_UNIVERSITY_ENABLED must be true")
    if not environment["read_only_release_verified"]:
        migration_blockers.append("read-only production release has not been marked verified")
    if not environment["safe_pre_activation_flags"]:
        migration_blockers.append("preflight requires session writes and durable mode to remain disabled")
    if not evidence["configured_id_valid"]:
        migration_blockers.append("configured OCU-SCI-007 release evidence ID is missing or invalid")
    if release_evidence is None:
        migration_blockers.append("release evidence artifact was not supplied")
    elif not evidence["artifact_valid"]:
        migration_blockers.append("release evidence artifact is invalid")
    elif not evidence["artifact_matches_configured_id"]:
        migration_blockers.append("release evidence artifact does not match configured SHA-256 evidence ID")
    if not database["reachable"]:
        migration_blockers.append("target database is not reachable")

    durable_blockers = list(migration_blockers)
    if not environment["learner_auth_enabled"]:
        durable_blockers.append("OCU_UNIVERSITY_LEARNER_AUTH_ENABLED must be true before durable activation")
    if not environment["supabase_url_present"] or not environment["supabase_anon_key_present"]:
        durable_blockers.append("learner Supabase verification configuration is incomplete")
    if database["reachable"] and not database["schema_valid"]:
        durable_blockers.append("oc_university durable schema is incomplete or unsafe")
    if not reviewer_registry["valid"]:
        durable_blockers.append("reviewer qualification registry is invalid")
    elif int(reviewer_registry.get("science_grant_count", 0)) < 1:
        durable_blockers.append("no qualified scientific reviewer is assigned for learner submissions")

    return {
        "contract": "OCU-SCI-009H-PREFLIGHT-002",
        "mode": "read_only_pre_activation",
        "environment": environment,
        "release_evidence": evidence,
        "database": database,
        "reviewer_registry": reviewer_registry,
        "migration_blockers": migration_blockers,
        "durable_blockers": durable_blockers,
        "blockers": durable_blockers,
        "ready_to_apply_migration": not migration_blockers,
        "ready_to_enable_durable": not durable_blockers,
        "mutations_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Orchid University phased activation preflight")
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--stage", choices=("migration", "durable"), default="durable")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    result = preflight(release_evidence=args.release_evidence)
    ready_key = "ready_to_apply_migration" if args.stage == "migration" else "ready_to_enable_durable"
    blockers_key = "migration_blockers" if args.stage == "migration" else "durable_blockers"
    ready = bool(result[ready_key])
    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(f"University {args.stage} preflight: {'READY' if ready else 'BLOCKED'}")
        for blocker in result[blockers_key]:
            print(f"BLOCKER: {blocker}")
        print("No mutations were performed.")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
