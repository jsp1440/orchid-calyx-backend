from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryCandidateRepository:
    def __init__(self) -> None:
        self.runs: dict[int, dict[str, Any]] = {}
        self.items: dict[int, list[dict[str, Any]]] = {}
        self.candidates: list[dict[str, Any]] = []
        self.evidence_links: list[dict[str, Any]] = []
        self.reviews: dict[int, dict[str, Any]] = {}
        self.conflicts: dict[int, dict[str, Any]] = {}
        self.duplicate_groups: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.cancelled: set[int] = set()
        self._id = 1

    def next_id(self) -> int:
        value = self._id
        self._id += 1
        return value

    def create_run(self, configuration_hash: str, extractor_version: str, ruleset_version: str) -> int:
        run_id = self.next_id()
        self.runs[run_id] = {"candidate_run_id": run_id, "configuration_hash": configuration_hash, "extractor_version": extractor_version, "ruleset_version": ruleset_version, "state": "PLANNING", "last_completed_item_id": None, "metrics": {"planned": 0, "created": 0, "reused": 0, "duplicates": 0, "conflicts": 0, "review_required": 0, "failed": 0}, "created_at": now()}
        self.items[run_id] = []
        return run_id

    def add_item(self, run_id: int, evidence: Any, fingerprint: str, action: str) -> None:
        item_id = self.next_id()
        self.items[run_id].append({"item_id": item_id, "run_id": run_id, "evidence": evidence, "fingerprint": fingerprint, "action": action, "state": "PLANNED", "failure": None})
        self.runs[run_id]["metrics"]["planned"] += 1

    def transition(self, run_id: int, state: str) -> dict[str, Any]:
        self.runs[run_id]["state"] = state
        if state in {"COMPLETED", "PARTIAL", "CANCELLED"}:
            self.runs[run_id]["completed_at"] = now()
        return self.status(run_id)

    def status(self, run_id: int) -> dict[str, Any]:
        return deepcopy(self.runs[run_id])

    def pending(self, run_id: int) -> list[dict[str, Any]]:
        return [item for item in self.items[run_id] if item["state"] in {"PLANNED", "FAILED"}]

    def request_cancel(self, run_id: int) -> dict[str, Any]:
        self.cancelled.add(run_id)
        return self.transition(run_id, "CANCELLING")

    def clear_cancel(self, run_id: int) -> None:
        self.cancelled.discard(run_id)

    def candidate_for_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return next((candidate for candidate in reversed(self.candidates) if candidate["evidence_fingerprint"] == fingerprint), None)

    def active_identity(self, kind: str, subject: str, predicate: str) -> list[dict[str, Any]]:
        return [candidate for candidate in self.candidates if candidate["active"] and candidate["kind"] == kind and candidate["normalized_subject"] == subject and candidate["predicate"] == predicate]

    def open_review(self, run_id: int, candidate_id: int | None, category: str, severity: str, evidence: dict[str, Any]) -> dict[str, Any]:
        review_id = self.next_id()
        review = {"review_id": review_id, "candidate_run_id": run_id, "candidate_id": candidate_id, "category": category, "severity": severity, "evidence": deepcopy(evidence), "state": "OPEN", "created_at": now()}
        self.reviews[review_id] = review
        self.runs[run_id]["metrics"]["review_required"] += 1
        return review

    def resolve_review(self, review_id: int, decision: str, rationale: str, actor: str) -> dict[str, Any]:
        if decision not in {"APPROVE_CANDIDATE", "REJECT_CANDIDATE", "REQUEST_CHANGES", "MARK_DUPLICATE", "RESOLVE_CONFLICT"}:
            raise ValueError("INVALID_REVIEW_DECISION")
        if not rationale.strip():
            raise ValueError("DECISION_RATIONALE_REQUIRED")
        review = self.reviews[review_id]
        review.update(state="RESOLVED", decision=decision, rationale=rationale, actor=actor, resolved_at=now())
        candidate = next((x for x in self.candidates if x["candidate_id"] == review.get("candidate_id")), None)
        if candidate:
            candidate["review_state"] = "APPROVED" if decision == "APPROVE_CANDIDATE" else ("REJECTED" if decision == "REJECT_CANDIDATE" else "CHANGES_REQUESTED")
            candidate["published"] = False
        self.events.append({"event_id": self.next_id(), "event_type": "REVIEW_RESOLVED", "review_id": review_id, "actor": actor, "created_at": now()})
        return deepcopy(review)
