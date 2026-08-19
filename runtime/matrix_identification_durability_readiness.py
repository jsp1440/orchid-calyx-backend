"""Integrated read-only durability readiness for the Matrix scientific trail."""

from __future__ import annotations

from typing import Any

from runtime.matrix_identification_persistence_preflight import (
    matrix_session_persistence_preflight,
)
from runtime.matrix_identification_registry_preflight import (
    matrix_registry_persistence_preflight,
)
from runtime.matrix_identification_registry_store import (
    matrix_registry_persistence_status,
)
from runtime.matrix_identification_session_store import (
    matrix_session_persistence_status,
)

READINESS_SCHEMA_VERSION = "matrix-identification-durability-readiness/v1"


def compose_matrix_durability_readiness(
    *,
    session_preflight: dict[str, Any],
    registry_preflight: dict[str, Any],
    session_status: dict[str, Any],
    registry_status: dict[str, Any],
) -> dict[str, Any]:
    """Compose a deterministic go/no-go contract without mutating deployment state."""
    session_ready = bool(session_preflight.get("activation_ready"))
    registry_ready = bool(registry_preflight.get("activation_ready"))
    session_active = bool(session_status.get("durable") and session_status.get("ready"))
    registry_active = bool(registry_status.get("durable") and registry_status.get("ready"))

    blockers: list[dict[str, Any]] = []
    for code in session_preflight.get("blockers") or []:
        blockers.append({"component": "session", "code": str(code)})
    for code in registry_preflight.get("blockers") or []:
        blockers.append({"component": "registry", "code": str(code)})

    deployment_sequence = [
        {
            "order": 1,
            "action": "apply_migration_612",
            "description": "Apply governed Matrix session schema migration 612 and re-run session preflight.",
            "required": not bool(session_preflight.get("migration_612_schema_ready")),
            "performed_by_readiness": False,
        },
        {
            "order": 2,
            "action": "apply_migration_613",
            "description": "Apply governed immutable-registry schema migration 613 and re-run registry preflight.",
            "required": not bool(registry_preflight.get("migration_613_schema_ready")),
            "performed_by_readiness": False,
        },
        {
            "order": 3,
            "action": "verify_registry_source_inventory",
            "description": "Require every physical file-backed registry package to be readable and independently checksum-valid.",
            "required": not bool(registry_preflight.get("source_inventory_ready")),
            "performed_by_readiness": False,
        },
        {
            "order": 4,
            "action": "copy_registry_packages",
            "description": "Run the governed registry migration utility in dry-run first, then explicit --apply only after review.",
            "required": not bool(registry_preflight.get("data_copy_ready")),
            "performed_by_readiness": False,
        },
        {
            "order": 5,
            "action": "enable_registry_durable_mode",
            "description": "Enable CALYX_MATRIX_REGISTRY_DURABLE_ENABLED only after registry activation readiness is true.",
            "required": registry_ready and not registry_active,
            "performed_by_readiness": False,
        },
        {
            "order": 6,
            "action": "enable_session_durable_mode",
            "description": "Enable CALYX_MATRIX_SESSION_DURABLE_ENABLED only after session readiness and durable registry readiness are true.",
            "required": session_ready and registry_ready and not session_active,
            "performed_by_readiness": False,
        },
        {
            "order": 7,
            "action": "post_activation_verify",
            "description": "Re-run integrated readiness and verify both stores report durable=true and ready=true.",
            "required": not (session_active and registry_active),
            "performed_by_readiness": False,
        },
    ]

    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "components": {
            "session": {
                "activation_ready": session_ready,
                "durable_active": session_active,
                "preflight": session_preflight,
                "status": session_status,
            },
            "registry": {
                "activation_ready": registry_ready,
                "durable_active": registry_active,
                "preflight": registry_preflight,
                "status": registry_status,
            },
        },
        "scientific_trail_activation_ready": bool(session_ready and registry_ready),
        "scientific_trail_durable_active": bool(session_active and registry_active),
        "blockers": blockers,
        "deployment_sequence": deployment_sequence,
        "automatic_migration": False,
        "automatic_data_copy": False,
        "automatic_environment_change": False,
        "governance_boundary": (
            "This readiness contract is read-only. Migrations, registry copy, environment flags, and production activation require separate governed deployment actions."
        ),
    }


def matrix_durability_readiness() -> dict[str, Any]:
    return compose_matrix_durability_readiness(
        session_preflight=matrix_session_persistence_preflight(),
        registry_preflight=matrix_registry_persistence_preflight(),
        session_status=matrix_session_persistence_status(),
        registry_status=matrix_registry_persistence_status(),
    )
