"""Persistent, owner-gated activation state for governed Calyx cycles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(frozen=True)
class ActivationState:
    enabled: bool = False
    owner_approved: bool = False
    paused: bool = True
    interval_minutes: int = 60
    max_draft_prs_per_cycle: int = 1
    last_cycle_at: str | None = None
    last_result: str | None = None
    updated_at: str | None = None

    def validated(self) -> ActivationState:
        if not 15 <= self.interval_minutes <= 1440:
            raise ValueError("interval_minutes must be between 15 and 1440")
        if not 0 <= self.max_draft_prs_per_cycle <= 5:
            raise ValueError("max_draft_prs_per_cycle must be between 0 and 5")
        if self.enabled and not self.owner_approved:
            raise PermissionError("activation requires explicit owner approval")
        return self

    @property
    def authorized(self) -> bool:
        return self.enabled and self.owner_approved and not self.paused

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["authorized"] = self.authorized
        return payload


class ActivationStateStore(Protocol):
    def load(self) -> dict[str, Any] | None: ...

    def save(self, payload: dict[str, Any]) -> None: ...


class PersistentActivationController:
    """Load and persist activation state while failing closed by default."""

    def __init__(self, store: ActivationStateStore) -> None:
        self._store = store

    def load(self) -> ActivationState:
        payload = self._store.load()
        if not payload:
            return ActivationState().validated()
        allowed = {
            field.name for field in ActivationState.__dataclass_fields__.values()
        }
        state = ActivationState(
            **{key: value for key, value in payload.items() if key in allowed}
        )
        return state.validated()

    def save(self, state: ActivationState) -> ActivationState:
        validated = state.validated()
        timestamp = datetime.now(timezone.utc).isoformat()
        persisted = ActivationState(**{**asdict(validated), "updated_at": timestamp})
        self._store.save(asdict(persisted))
        return persisted

    def record_cycle(
        self, result: str, *, occurred_at: str | None = None
    ) -> ActivationState:
        current = self.load()
        if not current.authorized:
            raise PermissionError("runtime is not authorized to record an active cycle")
        timestamp = occurred_at or datetime.now(timezone.utc).isoformat()
        return self.save(
            ActivationState(
                **{
                    **asdict(current),
                    "last_cycle_at": timestamp,
                    "last_result": result,
                }
            )
        )

    @staticmethod
    def safety_status() -> dict[str, bool]:
        return {
            "automatic_merge": False,
            "automatic_deploy": False,
            "scientific_publication": False,
            "production_deletion": False,
            "external_communication": False,
            "permissions_change": False,
            "governance_change": False,
        }
