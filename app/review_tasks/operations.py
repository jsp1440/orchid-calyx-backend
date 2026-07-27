from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.mission_control_access import AccessPrincipal, CapabilityService

from .models import ReviewTaskState
from .service import GovernedReviewTaskService


class ReviewQueueOperations:
    """Operational controls for reservations, metrics, and workforce exchange."""

    def __init__(
        self,
        service: GovernedReviewTaskService,
        capability_service: CapabilityService | None = None,
    ) -> None:
        self.service = service
        self.capability_service = capability_service or CapabilityService()

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def expire_reservations(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or datetime.now(timezone.utc)
        expired: list[dict[str, Any]] = []
        for task in self.service.repository.list_tasks():
            if task.get("state") != ReviewTaskState.RESERVED.value:
                continue
            expires_at = self._parse_time(task.get("reservation_expires_at"))
            if not expires_at or expires_at > current:
                continue
            former_assignee = task.get("assigned_to")
            task["state"] = ReviewTaskState.EXPIRED.value
            task["assigned_to"] = None
            task["reservation_expires_at"] = None
            task["updated_at"] = current.isoformat()
            self.service.repository.save(task)
            self.service.repository.append_event(
                task["task_id"],
                "RESERVATION_EXPIRED",
                {"former_assignee": former_assignee, "expired_at": current.isoformat()},
            )
            expired.append(task)
        return expired

    def metrics(self) -> dict[str, Any]:
        tasks = self.service.repository.list_tasks()
        by_state = Counter(str(task.get("state") or "UNKNOWN") for task in tasks)
        by_capability = Counter(str(task.get("required_capability") or "UNKNOWN") for task in tasks)
        reserved = [task for task in tasks if task.get("state") == ReviewTaskState.RESERVED.value]
        return {
            "total": len(tasks),
            "by_state": dict(sorted(by_state.items())),
            "by_required_capability": dict(sorted(by_capability.items())),
            "reserved": len(reserved),
            "unassigned": sum(1 for task in tasks if not task.get("assigned_to")),
            "high_priority_open": sum(
                1
                for task in tasks
                if task.get("state") in {ReviewTaskState.OPEN.value, ReviewTaskState.EXPIRED.value}
                and int(task.get("priority") or 0) >= 75
            ),
        }

    def export_for_principal(self, principal: AccessPrincipal) -> dict[str, Any]:
        decision = self.capability_service.evaluate(principal, "review.external.export")
        if not decision.allowed:
            return {
                "allowed": False,
                "authorization": self.capability_service.audit_payload(decision),
                "tasks": [],
            }
        tasks = self.service.queue_for_principal(principal)
        return {
            "allowed": True,
            "authorization": self.capability_service.audit_payload(decision),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [
                {
                    "task_id": task["task_id"],
                    "review_type": task["review_type"],
                    "required_capability": task["required_capability"],
                    "priority": task["priority"],
                    "scientific_impact_score": task["scientific_impact_score"],
                    "candidate_ids": task.get("candidate_ids", []),
                    "aggregate_version_ids": task.get("aggregate_version_ids", []),
                    "display_policy": task.get("display_policy"),
                    "metadata": task.get("metadata", {}),
                }
                for task in tasks
                if not task.get("embargoed")
            ],
        }

    def default_reservation_expiration(self, *, hours: int = 24) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
