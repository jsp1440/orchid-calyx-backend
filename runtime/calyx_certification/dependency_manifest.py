from __future__ import annotations

from typing import Any


def validate_dependency_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = (
        "backend_url",
        "database",
        "persistent_mount",
        "owner_secret",
        "deployed_commit",
    )
    blockers = [f"missing:{key}" for key in required if not manifest.get(key)]
    return {
        "complete": not blockers,
        "blockers": blockers,
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
