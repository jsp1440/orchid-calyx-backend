from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryReviewTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.decisions: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def get(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        return deepcopy(task) if task else None

    def save(self, task: dict[str, Any]) -> dict[str, Any]:
        self.tasks[task["task_id"]] = deepcopy(task)
        return deepcopy(task)

    def list_tasks(self) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self.tasks.values()]

    def append_event(self, task_id: str, event_type: str, details: dict[str, Any]) -> None:
        self.events.append(
            {
                "event_id": len(self.events) + 1,
                "task_id": task_id,
                "event_type": event_type,
                "details": deepcopy(details),
                "created_at": _now(),
            }
        )

    def history(self, task_id: str) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self.events if item["task_id"] == task_id]

    def append_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        stored = {**deepcopy(decision), "decision_id": len(self.decisions) + 1, "created_at": _now()}
        self.decisions.append(stored)
        return deepcopy(stored)

    def decisions_for(self, task_id: str) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self.decisions if item["task_id"] == task_id]
