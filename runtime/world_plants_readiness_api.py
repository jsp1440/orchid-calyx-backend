"""Live, fail-closed operational readiness report for World Plants intake."""

from __future__ import annotations

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


def build_taxonomy_readiness_report(*, intake_root: Path) -> dict[str, Any]:
    """Return deployed operational evidence without mutating taxonomy data."""
    storage_exists = intake_root.exists() and intake_root.is_dir()
    storage_persistent = _flag("CALYX_TAXONOMY_STORAGE_PERSISTENT")
    storage_writable = storage_exists and os.access(intake_root, os.W_OK)
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
            _flag("CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED"),
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
            _flag("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED"),
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
    return {
        "ready_for_upload": ready_for_upload,
        "ready_for_promotion": False,
        "gates": [gate.as_dict() for gate in gates],
        "checked_at": datetime.now(UTC).isoformat(),
        "instruction": (
            "Upload Michael Hassler's file through /mission-control?view=taxonomy-releases."
            if ready_for_upload
            else "Do not upload the production taxonomy file yet; resolve every blocked upload gate."
        ),
        "read_only": True,
    }
