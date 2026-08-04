from __future__ import annotations

from typing import Any

_REQUIRED_SECRETS = {"CALYX_BACKEND_URL", "CALYX_OWNER_ACCESS_CODE"}


def evaluate_secret_readiness(entries: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {str(entry.get("name")): entry for entry in entries}
    blockers: list[str] = []
    for name in sorted(_REQUIRED_SECRETS):
        entry = by_name.get(name)
        if entry is None:
            blockers.append(f"missing:{name}")
            continue
        if entry.get("configured") is not True:
            blockers.append(f"unconfigured:{name}")
        if entry.get("value") not in (None, ""):
            blockers.append(f"secret_value_exposed:{name}")
        if entry.get("source") not in {"github_actions", "runtime_environment"}:
            blockers.append(f"invalid_source:{name}")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "required_secret_names": sorted(_REQUIRED_SECRETS),
        "secret_values_stored": False,
        "production_action_authorized": False,
    }
