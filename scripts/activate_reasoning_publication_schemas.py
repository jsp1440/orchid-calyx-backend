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
    (
        "103_reasoning_ledger.sql",
        "b69fb53bf0771aa3730fb8a1b1c0d7a73a7a2153",
    ),
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


def _base_report(*, apply_requested: bool) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply_requested else "preflight",
        "migration_order": [filename for filename, _ in MIGRATIONS],
        "migration_identities": migration_identity_report(),
        "apply_requested": apply_requested,
        "explicit_confirmation_present": (
            os.environ.get("CALYX_REASONING_MIGRATION_CONFIRM", "") == CONFIRMATION
        ),
        "publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
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
        report.update(
            {
                "blockers": blockers,
                "status": "blocked",
                "production_database_mutation_authorized": False,
            }
        )
        _write(report)
        return 2

    if apply_requested and not report["explicit_confirmation_present"]:
        blockers.append("EXPLICIT_APPLY_CONFIRMATION_REQUIRED")

    import psycopg

    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            prerequisites = _relation_state(connection, PREREQUISITES)
            targets_before = _relation_state(connection, TARGETS)
            report["prerequisites"] = prerequisites
            report["targets_before"] = targets_before
            report["activation_required"] = not all(targets_before.values())

            missing_prerequisites = [
                name for name, present in prerequisites.items() if not present
            ]
            if missing_prerequisites:
                blockers.extend(
                    f"PREREQUISITE_MISSING:{name}" for name in missing_prerequisites
                )

            report["ready_to_apply"] = not blockers

            if apply_requested and not blockers:
                report["production_database_mutation_authorized"] = True
                for filename, _ in MIGRATIONS:
                    sql = (ROOT / "migrations" / filename).read_text(encoding="utf-8")
                    connection.execute(sql)
                report["applied"] = True
            else:
                report["production_database_mutation_authorized"] = False
                report["applied"] = False

            targets_after = _relation_state(connection, TARGETS)
            report["targets_after"] = targets_after
            report["activation_complete"] = all(targets_after.values())

            if apply_requested and not blockers and not report["activation_complete"]:
                blockers.append("POST_APPLY_SCHEMA_VERIFICATION_FAILED")
    except psycopg.Error as exc:
        blockers.append(f"DATABASE_OPERATION_FAILED:{type(exc).__name__}")
        report["database_error"] = str(exc)
        report["production_database_mutation_authorized"] = False

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
