"""Preflight or explicitly activate the World Plants staging schema.

Default behavior is read-only. Production mutation requires BOTH ``--apply`` and
``CALYX_TAXONOMY_MIGRATION_CONFIRM=APPLY_107``. This script never activates a
taxonomy release and never mutates the Knowledge Graph.
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
MIGRATION = ROOT / "migrations" / "107_world_plants_release_staging.sql"
EVIDENCE_PATH = Path(
    os.environ.get(
        "CALYX_TAXONOMY_MIGRATION_EVIDENCE_PATH",
        "calyx-taxonomy-migration-107-activation.json",
    )
)
CONFIRMATION = "APPLY_107"
TARGETS = (
    "taxonomy_pipeline.releases",
    "taxonomy_pipeline.staged_taxa",
    "taxonomy_pipeline.staging_checkpoints",
    "taxonomy_pipeline.change_reports",
    "taxonomy_pipeline.review_queue",
)


def _relation_state(connection) -> dict[str, bool]:
    return {
        name: bool(connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0])
        for name in TARGETS
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
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply_requested else "preflight",
        "migration_id": "107_world_plants_release_staging",
        "migration_sha256": hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),
        "apply_requested": apply_requested,
        "explicit_confirmation_present": (
            os.environ.get("CALYX_TAXONOMY_MIGRATION_CONFIRM", "") == CONFIRMATION
        ),
        "production_database_mutation_authorized": False,
        "production_database_mutation_attempted": False,
        "production_database_mutation_observed": False,
        "taxonomy_activation_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    blockers: list[str] = []
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        blockers.append("DATABASE_URL_MISSING")
        report.update({"blockers": blockers, "status": "blocked"})
        _write(report)
        return 2
    if apply_requested and not report["explicit_confirmation_present"]:
        blockers.append("EXPLICIT_APPLY_CONFIRMATION_REQUIRED")

    import psycopg

    before: dict[str, bool] | None = None
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            before = _relation_state(connection)
            report["targets_before"] = before
            report["activation_required"] = not all(before.values())
            if apply_requested and not blockers:
                report["production_database_mutation_authorized"] = True
                report["production_database_mutation_attempted"] = True
                connection.execute(MIGRATION.read_text(encoding="utf-8"), prepare=False)
    except psycopg.Error as exc:
        blockers.append(f"DATABASE_OPERATION_FAILED:{type(exc).__name__}")
        report["database_error_type"] = type(exc).__name__

    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            after = _relation_state(connection)
            report["targets_after"] = after
            report["activation_complete"] = all(after.values())
            report["production_database_mutation_observed"] = bool(
                report["production_database_mutation_attempted"] and before != after
            )
    except psycopg.Error as exc:
        blockers.append(f"POST_APPLY_INSPECTION_FAILED:{type(exc).__name__}")
        report["post_apply_inspection_error_type"] = type(exc).__name__

    if apply_requested and not report.get("activation_complete", False):
        blockers.append("POST_APPLY_SCHEMA_VERIFICATION_FAILED")
    report["blockers"] = sorted(set(blockers))
    report["status"] = "passed" if not blockers else "blocked"
    report["applied"] = bool(
        apply_requested
        and report["production_database_mutation_attempted"]
        and report.get("activation_complete", False)
        and not blockers
    )
    _write(report)
    return 0 if not blockers else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return run(apply_requested=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
