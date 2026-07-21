from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any

from .models import AuditEvent, ReviewRecord


class ImmutableConflictError(RuntimeError):
    pass


class MemoryDesignPlanningRepository:
    """Thread-safe append-only repository used for deterministic tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._artifacts: dict[str, dict[str, Any]] = defaultdict(dict)
        self._logical: dict[str, dict[str, list[Any]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._fingerprints: dict[str, dict[str, Any]] = defaultdict(dict)
        self._reviews: list[ReviewRecord] = []
        self._audits: list[AuditEvent] = []

    def append(self, kind: str, artifact: Any, logical_key: str, digest: str) -> Any:
        with self._lock:
            if existing := self._fingerprints[kind].get(digest):
                return existing
            identity = self._identity(artifact)
            if identity in self._artifacts[kind]:
                raise ImmutableConflictError(f"{kind.upper()}_IDENTITY_CONFLICT")
            versions = self._logical[kind][logical_key]
            if versions and artifact.version != versions[-1].version + 1:
                raise ImmutableConflictError(f"{kind.upper()}_VERSION_CONFLICT")
            if not versions and artifact.version != 1:
                raise ImmutableConflictError(
                    f"{kind.upper()}_VERSION_MUST_START_AT_ONE"
                )
            self._artifacts[kind][identity] = artifact
            versions.append(artifact)
            self._fingerprints[kind][digest] = artifact
            return artifact

    def get(self, kind: str, identity: str) -> Any | None:
        return self._artifacts[kind].get(identity)

    def history(self, kind: str, logical_key: str) -> tuple[Any, ...]:
        return tuple(self._logical[kind].get(logical_key, ()))

    def append_review(self, review: ReviewRecord) -> ReviewRecord:
        with self._lock:
            for existing in self._reviews:
                if existing.integrity_hash == review.integrity_hash:
                    return existing
                if (
                    existing.artifact_hash == review.artifact_hash
                    and existing.reviewer_role == review.reviewer_role
                    and existing.decision != review.decision
                ):
                    raise ImmutableConflictError("CONFLICTING_FINAL_REVIEW_DECISION")
            self._reviews.append(review)
            return review

    def reviews(self, artifact_id: str) -> tuple[ReviewRecord, ...]:
        return tuple(r for r in self._reviews if r.artifact_id == artifact_id)

    def append_audit(self, event: AuditEvent) -> AuditEvent:
        with self._lock:
            if any(
                item.integrity_hash == event.integrity_hash for item in self._audits
            ):
                return next(
                    item
                    for item in self._audits
                    if item.integrity_hash == event.integrity_hash
                )
            self._audits.append(event)
            return event

    def audits(self, artifact_id: str | None = None) -> tuple[AuditEvent, ...]:
        if artifact_id is None:
            return tuple(self._audits)
        return tuple(a for a in self._audits if a.artifact_id == artifact_id)

    @staticmethod
    def _identity(artifact: Any) -> str:
        for name in (
            "request_id",
            "snapshot_id",
            "evidence_package_id",
            "reasoning_record_id",
            "conflict_id",
            "interface_plan_id",
        ):
            if hasattr(artifact, name):
                return getattr(artifact, name)
        raise TypeError("UNSUPPORTED_ARTIFACT")
