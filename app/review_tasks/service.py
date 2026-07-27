from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .models import ReviewDecisionInput, ReviewDecisionType, ReviewTaskInput, ReviewTaskState
from .repository import MemoryReviewTaskRepository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


class ReviewTaskError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class GovernedReviewTaskService:
    """Authoritative, auditable review task engine for Mission Control."""

    ROUTING_CAPABILITIES = {
        "HUMAN_REVIEW_REQUIRED": "review.science",
        "EXPERT_REVIEW_REQUIRED": "review.expert",
        "PUBLICATION_REVIEW_REQUIRED": "review.publish",
    }

    def __init__(self, repository: MemoryReviewTaskRepository | None = None) -> None:
        self.repository = repository or MemoryReviewTaskRepository()

    def create(self, item: ReviewTaskInput) -> dict[str, Any]:
        identity = {
            "orchestration_id": item.orchestration_id,
            "review_type": item.review_type,
            "risk_class": item.risk_class,
            "routing_outcome": item.routing_outcome,
            "candidate_ids": sorted(item.candidate_ids),
            "aggregate_version_ids": sorted(item.aggregate_version_ids),
            "batch_key": item.batch_key,
        }
        task_id = _fingerprint(identity)
        existing = self.repository.get(task_id)
        if existing:
            existing["reused"] = True
            existing["history"] = self.repository.history(task_id)
            return existing
        if item.routing_outcome not in self.ROUTING_CAPABILITIES:
            raise ReviewTaskError("ROUTING_NOT_REVIEWABLE")
        expected_capability = self.ROUTING_CAPABILITIES[item.routing_outcome]
        if item.required_capability != expected_capability:
            raise ReviewTaskError(
                "INVALID_REQUIRED_CAPABILITY",
                {
                    "expected": expected_capability,
                    "received": item.required_capability,
                },
            )
        if item.priority < 0 or item.priority > 100:
            raise ReviewTaskError("INVALID_PRIORITY")
        if item.consensus_required < 1:
            raise ReviewTaskError("INVALID_CONSENSUS_REQUIREMENT")
        task = {
            "task_id": task_id,
            "orchestration_id": item.orchestration_id,
            "review_type": item.review_type,
            "risk_class": item.risk_class,
            "routing_outcome": item.routing_outcome,
            "required_capability": item.required_capability,
            "candidate_ids": sorted(item.candidate_ids),
            "aggregate_version_ids": sorted(item.aggregate_version_ids),
            "priority": item.priority,
            "scientific_impact_score": item.scientific_impact_score,
            "consensus_required": item.consensus_required,
            "batch_key": item.batch_key,
            "display_policy": item.display_policy,
            "embargoed": item.embargoed,
            "metadata": deepcopy(item.metadata),
            "state": ReviewTaskState.OPEN.value,
            "assigned_to": None,
            "reservation_expires_at": None,
            "authoritative_decision": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.repository.save(task)
        self.repository.append_event(task_id, "TASK_CREATED", identity)
        task["history"] = self.repository.history(task_id)
        return task

    def create_from_orchestration(self, orchestration: dict[str, Any]) -> dict[str, Any] | None:
        routing = orchestration.get("routing_outcome")
        if routing == "PROVISIONAL_KNOWLEDGE":
            return None
        capability = self.ROUTING_CAPABILITIES.get(str(routing))
        if not capability:
            raise ReviewTaskError("ORCHESTRATION_NOT_REVIEWABLE")
        return self.create(
            ReviewTaskInput(
                orchestration_id=str(orchestration["orchestration_id"]),
                review_type=str(routing),
                risk_class=str(orchestration["risk_class"]),
                routing_outcome=str(routing),
                required_capability=capability,
                candidate_ids=tuple(orchestration.get("candidate_ids", ())),
                aggregate_version_ids=tuple(
                    orchestration.get("downstream", {}).get("aggregate_version_ids", ())
                ),
                priority=90 if routing != "HUMAN_REVIEW_REQUIRED" else 60,
                scientific_impact_score=0.9 if routing == "EXPERT_REVIEW_REQUIRED" else 0.6,
                metadata={"policy_version": orchestration.get("policy_version")},
            )
        )

    def reserve(
        self,
        task_id: str,
        reviewer_id: str,
        capabilities: tuple[str, ...],
    ) -> dict[str, Any]:
        task = self._authorized_task(task_id, capabilities)
        if task["state"] not in {
            ReviewTaskState.OPEN.value,
            ReviewTaskState.EXPIRED.value,
        }:
            raise ReviewTaskError("TASK_NOT_AVAILABLE")
        task["state"] = ReviewTaskState.RESERVED.value
        task["assigned_to"] = reviewer_id
        task["updated_at"] = _now()
        self.repository.save(task)
        self.repository.append_event(task_id, "TASK_RESERVED", {"reviewer_id": reviewer_id})
        return task

    def decide(self, task_id: str, decision: ReviewDecisionInput) -> dict[str, Any]:
        task = self._authorized_task(task_id, decision.reviewer_capabilities)
        if task.get("authoritative_decision") in {"REJECT", "ESCALATE"}:
            raise ReviewTaskError("AUTHORITATIVE_DECISION_LOCKED")
        stored = self.repository.append_decision(
            {
                "task_id": task_id,
                "decision": decision.decision.value,
                "reviewer_id": decision.reviewer_id,
                "comment": decision.comment,
                "modified_value": deepcopy(decision.modified_value),
                "provenance": deepcopy(decision.provenance),
            }
        )
        decisions = self.repository.decisions_for(task_id)
        terminal = decision.decision in {
            ReviewDecisionType.ACCEPT,
            ReviewDecisionType.MODIFY,
            ReviewDecisionType.REJECT,
        }
        if decision.decision is ReviewDecisionType.ESCALATE:
            task["state"] = ReviewTaskState.ESCALATED.value
            task["authoritative_decision"] = ReviewDecisionType.ESCALATE.value
        elif terminal and len(decisions) >= task["consensus_required"]:
            task["state"] = ReviewTaskState.DECIDED.value
            task["authoritative_decision"] = decision.decision.value
        else:
            task["state"] = ReviewTaskState.IN_REVIEW.value
        task["updated_at"] = _now()
        self.repository.save(task)
        self.repository.append_event(
            task_id,
            "DECISION_RECORDED",
            {"decision_id": stored["decision_id"], "decision": decision.decision.value},
        )
        task["decisions"] = decisions
        task["history"] = self.repository.history(task_id)
        return task

    def queue(self, capabilities: tuple[str, ...]) -> list[dict[str, Any]]:
        allowed = set(capabilities)
        tasks = [
            item
            for item in self.repository.list_tasks()
            if item["required_capability"] in allowed
            and item["state"]
            in {
                ReviewTaskState.OPEN.value,
                ReviewTaskState.RESERVED.value,
                ReviewTaskState.IN_REVIEW.value,
            }
        ]
        return sorted(
            tasks,
            key=lambda item: (
                -item["priority"],
                -item["scientific_impact_score"],
                item["task_id"],
            ),
        )

    def _authorized_task(
        self,
        task_id: str,
        capabilities: tuple[str, ...],
    ) -> dict[str, Any]:
        task = self.repository.get(task_id)
        if not task:
            raise ReviewTaskError("TASK_NOT_FOUND")
        if task["required_capability"] not in set(capabilities):
            raise ReviewTaskError(
                "CAPABILITY_REQUIRED",
                {"capability": task["required_capability"]},
            )
        return task
