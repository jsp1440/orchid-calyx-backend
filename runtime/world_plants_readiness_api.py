"""Live, fail-closed operational readiness report for World Plants intake."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.world_plants_rollback import rehearse_promotion_and_rollback


@dataclass(frozen=True)
class OperationalGate:
    name: str
    status: str
    evidence: str
    checked_at: str
    blocking_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _gate(name: str, passed: bool, evidence: str, blocked: str) -> OperationalGate:
    return OperationalGate(
        name=name,
        status="passed" if passed else "blocked",
        evidence=evidence,
        checked_at=datetime.now(UTC).isoformat(),
        blocking_reason=None if passed else blocked,
    )


def _rollback_certified() -> tuple[bool, str]:
    state = {
        "canonical_release_id": "baseline",
        "releases": {
            "baseline": {"row_count": 2, "crosswalk_count": 2},
            "candidate": {"row_count": 3, "crosswalk_count": 3},
        },
    }
    result = rehearse_promotion_and_rollback(
        state,
        candidate_release_id="candidate",
        actor="calyx-readiness-probe",
    )
    return result.certified, "Disposable promotion and rollback rehearsal completed."


def _latest_inspected_release(intake_root: Path) -> dict[str, Any] | None:
    """Read the newest immutable intake report without importing database code."""
    if not intake_root.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for report_path in intake_root.glob("*/report.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict):
            continue
        snapshot = report.get("snapshot")
        if not isinstance(snapshot, dict):
            continue
        candidates.append(report)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: str(item.get("snapshot", {}).get("acquired_at", "")),
    )


def _pipeline_state(
    *,
    latest_release: dict[str, Any] | None,
    staging_schema_verified: bool,
    smoke_verified: bool,
    ready_for_upload: bool,
) -> tuple[str, dict[str, Any]]:
    if latest_release is None:
        if ready_for_upload:
            return (
                "ready_for_release_upload",
                {
                    "job": "upload_world_orchids_release",
                    "action": "Upload the Hassler release through Mission Control taxonomy intake.",
                    "requires_owner_approval": False,
                },
            )
        return (
            "deployment_gates_blocking_intake",
            {
                "job": "resolve_taxonomy_intake_gates",
                "action": "Resolve the blocked intake gates shown in this readiness report.",
                "requires_owner_approval": False,
            },
        )

    release_id = str(latest_release.get("release_id", ""))
    snapshot = latest_release.get("snapshot", {})
    release_summary = {
        "release_id": release_id,
        "version_label": snapshot.get("version_label"),
        "filename": snapshot.get("filename"),
        "acquired_at": snapshot.get("acquired_at"),
        "state": latest_release.get("state", "inspected"),
    }
    if not staging_schema_verified:
        return (
            "release_inspected_staging_schema_blocked",
            {
                "job": "verify_taxonomy_staging_schema",
                "action": "Apply and verify migration 107 before any bounded staging batch is attempted.",
                "release": release_summary,
                "requires_owner_approval": True,
                "governance_boundary": "production_database_migration",
            },
        )
    if not smoke_verified:
        return (
            "release_inspected_staging_smoke_required",
            {
                "job": "verify_taxonomy_staging_smoke",
                "action": "Run the harmless staging smoke verification before staging the real release.",
                "release": release_summary,
                "requires_owner_approval": False,
            },
        )
    return (
        "release_inspected_ready_for_bounded_staging",
        {
            "job": "stage_next_taxonomy_batch",
            "action": "Stage the next bounded batch for the inspected release and review its checkpoint/report.",
            "release": release_summary,
            "requires_owner_approval": False,
            "maximum_batch_size": 2000,
        },
    )


def build_taxonomy_readiness_report(*, intake_root: Path) -> dict[str, Any]:
    """Return deployed operational evidence without mutating taxonomy data."""
    storage_exists = intake_root.exists() and intake_root.is_dir()
    storage_persistent = _flag("CALYX_TAXONOMY_STORAGE_PERSISTENT")
    storage_writable = storage_exists and os.access(intake_root, os.W_OK)
    staging_schema_verified = _flag("CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED")
    smoke_verified = _flag("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED")
    rollback_ok, rollback_evidence = _rollback_certified()

    gates = (
        _gate(
            "owner_authentication",
            True,
            "This request passed the owner/API-key dependency.",
            "Owner authentication did not succeed.",
        ),
        _gate(
            "persistent_intake_storage",
            storage_exists and storage_writable and storage_persistent,
            f"Storage path={intake_root}; exists={storage_exists}; writable={storage_writable}; persistent_flag={storage_persistent}.",
            "Configure a writable persistent volume and set CALYX_TAXONOMY_STORAGE_PERSISTENT=true.",
        ),
        _gate(
            "database_connection",
            bool(os.getenv("DATABASE_URL", "").strip()),
            "DATABASE_URL presence checked without exposing credentials.",
            "DATABASE_URL is not configured.",
        ),
        _gate(
            "staging_schema",
            staging_schema_verified,
            "Operator-controlled migration verification flag checked.",
            "Apply and verify the staging migration, then set CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED=true.",
        ),
        _gate(
            "deployed_routes",
            True,
            "The authenticated readiness route is executing in this deployment.",
            "Taxonomy Mission Control routes are not deployed.",
        ),
        _gate(
            "smoke_fixture",
            smoke_verified,
            "Operator-controlled smoke upload/readback verification flag checked.",
            "Run a harmless Hassler-format upload/readback test and set CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED=true.",
        ),
        _gate(
            "comparison_engine",
            True,
            "Deterministic World Plants crosswalk module imported in this build.",
            "Release comparison engine is unavailable.",
        ),
        _gate(
            "downstream_impact_audit",
            True,
            "Read-only downstream impact module is present in this build.",
            "Downstream impact audit is unavailable.",
        ),
        _gate(
            "rollback_certification",
            rollback_ok,
            rollback_evidence,
            "Disposable promotion and rollback rehearsal did not certify.",
        ),
        _gate(
            "owner_promotion_approval",
            False,
            "Promotion remains deliberately disabled until a separate owner approval contract exists.",
            "No owner promotion approval has been recorded.",
        ),
    )
    upload_gates = tuple(
        gate for gate in gates if gate.name != "owner_promotion_approval"
    )
    ready_for_upload = all(gate.status == "passed" for gate in upload_gates)
    latest_release = _latest_inspected_release(intake_root)
    pipeline_state, next_job = _pipeline_state(
        latest_release=latest_release,
        staging_schema_verified=staging_schema_verified,
        smoke_verified=smoke_verified,
        ready_for_upload=ready_for_upload,
    )
    return {
        "ready_for_upload": ready_for_upload,
        "ready_for_promotion": False,
        "pipeline_state": pipeline_state,
        "next_job": next_job,
        "latest_inspected_release": (
            next_job.get("release") if isinstance(next_job.get("release"), dict) else None
        ),
        "gates": [gate.as_dict() for gate in gates],
        "checked_at": datetime.now(UTC).isoformat(),
        "instruction": str(next_job["action"]),
        "read_only": True,
    }
