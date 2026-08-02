"""Mission Control persistence contract for governed Calyx audit briefings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class BriefingStore:
    """Small deterministic store interface; production adapters may persist to PostgreSQL."""

    def __init__(self) -> None:
        self._latest: dict[str, Any] | None = None

    def save(self, briefing: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(briefing)
        payload.setdefault("execution_policy", {})
        payload["execution_policy"].update(
            {
                "automatic_merge": False,
                "automatic_deploy": False,
                "automatic_scientific_publication": False,
                "external_communications": False,
            }
        )
        self._latest = payload
        return deepcopy(payload)

    def latest(self) -> dict[str, Any] | None:
        return deepcopy(self._latest)


def mission_control_response(briefing: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "available": briefing is not None,
        "briefing": deepcopy(briefing),
        "reactive_mode_enabled": False,
        "requires_owner_activation": True,
    }
