from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .constitution import (
    BuildAdmissionDecision,
    BuildAdmissionRequest,
    evaluate_build_admission,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


QueueStatus = Literal["admitted", "blocked", "scheduled", "running", "completed", "cancelled"]


class BuildQueueItem(StrictModel):
    build_id: str = Field(min_length=3)
    architecture_id: str = Field(min_length=3)
    status: QueueStatus
    priority: int = Field(ge=1, le=100)
    admission: BuildAdmissionDecision
    submitted_at: datetime
    updated_at: datetime


class BuildQueueSnapshot(StrictModel):
    items: list[BuildQueueItem]
    admitted_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    runnable_count: int = Field(ge=0)


class GovernedBuildQueue:
    def __init__(self) -> None:
        self._items: dict[str, BuildQueueItem] = {}

    def submit(self, request: BuildAdmissionRequest, priority: int = 50) -> BuildQueueItem:
        decision = evaluate_build_admission(request)
        now = datetime.now(timezone.utc)
        candidate = BuildQueueItem(
            build_id=request.build_id,
            architecture_id=request.architecture_id,
            status=decision.status,
            priority=priority,
            admission=decision,
            submitted_at=now,
            updated_at=now,
        )
        existing = self._items.get(request.build_id)
        if existing:
            comparable_existing = existing.model_copy(update={"submitted_at": now, "updated_at": now})
            if comparable_existing != candidate:
                raise ValueError(f"conflicting build queue identity: {request.build_id}")
            return existing
        self._items[request.build_id] = candidate
        return candidate

    def transition(self, build_id: str, target: QueueStatus) -> BuildQueueItem:
        item = self._items.get(build_id)
        if item is None:
            raise KeyError(build_id)
        allowed: dict[QueueStatus, set[QueueStatus]] = {
            "admitted": {"scheduled", "cancelled"},
            "blocked": {"cancelled"},
            "scheduled": {"running", "cancelled"},
            "running": {"completed", "cancelled"},
            "completed": set(),
            "cancelled": set(),
        }
        if target not in allowed[item.status]:
            raise ValueError(f"invalid queue transition: {item.status} -> {target}")
        updated = item.model_copy(update={"status": target, "updated_at": datetime.now(timezone.utc)})
        self._items[build_id] = updated
        return updated

    def get(self, build_id: str) -> BuildQueueItem | None:
        return self._items.get(build_id)

    def snapshot(self) -> BuildQueueSnapshot:
        items = sorted(self._items.values(), key=lambda item: (item.priority, item.submitted_at, item.build_id))
        return BuildQueueSnapshot(
            items=items,
            admitted_count=sum(item.status == "admitted" for item in items),
            blocked_count=sum(item.status == "blocked" for item in items),
            runnable_count=sum(item.status in {"admitted", "scheduled", "running"} for item in items),
        )
