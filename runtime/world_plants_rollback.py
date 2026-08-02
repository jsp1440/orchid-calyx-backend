"""Disposable promotion and rollback rehearsal for World Plants releases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class RehearsalReceipt:
    action: str
    release_id: str
    previous_release_id: str | None
    actor: str
    occurred_at: str
    row_count: int
    crosswalk_count: int
    historical_release_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RehearsalCertification:
    promoted_release_id: str
    restored_release_id: str | None
    state_restored: bool
    historical_releases_preserved: bool
    row_counts_restored: bool
    crosswalk_counts_restored: bool
    receipts: tuple[RehearsalReceipt, ...]

    @property
    def certified(self) -> bool:
        return all(
            (
                self.state_restored,
                self.historical_releases_preserved,
                self.row_counts_restored,
                self.crosswalk_counts_restored,
                len(self.receipts) == 2,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "promoted_release_id": self.promoted_release_id,
            "restored_release_id": self.restored_release_id,
            "state_restored": self.state_restored,
            "historical_releases_preserved": self.historical_releases_preserved,
            "row_counts_restored": self.row_counts_restored,
            "crosswalk_counts_restored": self.crosswalk_counts_restored,
            "receipts": [receipt.as_dict() for receipt in self.receipts],
            "certified": self.certified,
            "environment": "disposable_only",
            "production_mutation_allowed": False,
        }


def _receipt(
    *,
    action: str,
    release_id: str,
    previous_release_id: str | None,
    actor: str,
    state: dict[str, Any],
) -> RehearsalReceipt:
    release = state["releases"][release_id]
    return RehearsalReceipt(
        action=action,
        release_id=release_id,
        previous_release_id=previous_release_id,
        actor=actor,
        occurred_at=datetime.now(UTC).isoformat(),
        row_count=int(release.get("row_count", 0)),
        crosswalk_count=int(release.get("crosswalk_count", 0)),
        historical_release_count=len(state["releases"]),
    )


def rehearse_promotion_and_rollback(
    initial_state: dict[str, Any],
    *,
    candidate_release_id: str,
    actor: str,
) -> RehearsalCertification:
    """Promote and rollback a release against an isolated in-memory state copy."""
    if not actor.strip():
        raise ValueError("actor is required")

    state = deepcopy(initial_state)
    baseline = deepcopy(initial_state)
    releases = state.setdefault("releases", {})
    if candidate_release_id not in releases:
        raise ValueError("candidate release not found")

    previous_release_id = state.get("canonical_release_id")
    state["canonical_release_id"] = candidate_release_id
    promotion_receipt = _receipt(
        action="promote",
        release_id=candidate_release_id,
        previous_release_id=previous_release_id,
        actor=actor,
        state=state,
    )

    state["canonical_release_id"] = previous_release_id
    rollback_target = previous_release_id or candidate_release_id
    rollback_receipt = _receipt(
        action="rollback",
        release_id=rollback_target,
        previous_release_id=candidate_release_id,
        actor=actor,
        state=state,
    )

    historical_releases_preserved = set(state["releases"]) == set(baseline["releases"])
    row_counts_restored = {
        key: value.get("row_count") for key, value in state["releases"].items()
    } == {
        key: value.get("row_count") for key, value in baseline["releases"].items()
    }
    crosswalk_counts_restored = {
        key: value.get("crosswalk_count") for key, value in state["releases"].items()
    } == {
        key: value.get("crosswalk_count") for key, value in baseline["releases"].items()
    }

    return RehearsalCertification(
        promoted_release_id=candidate_release_id,
        restored_release_id=previous_release_id,
        state_restored=state == baseline,
        historical_releases_preserved=historical_releases_preserved,
        row_counts_restored=row_counts_restored,
        crosswalk_counts_restored=crosswalk_counts_restored,
        receipts=(promotion_receipt, rollback_receipt),
    )
