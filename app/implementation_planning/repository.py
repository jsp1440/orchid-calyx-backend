from __future__ import annotations

from collections import defaultdict
from threading import RLock

from .models import AuditEvent, ImplementationSpecificationSet, SpecificationReview


class SpecificationConflictError(RuntimeError):
    pass


class MemoryImplementationPlanningRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._by_id: dict[str, ImplementationSpecificationSet] = {}
        self._history: dict[str, list[ImplementationSpecificationSet]] = defaultdict(
            list
        )
        self._fingerprints: dict[str, ImplementationSpecificationSet] = {}
        self._reviews: list[SpecificationReview] = []
        self._audits: list[AuditEvent] = []

    def append(self, artifact: ImplementationSpecificationSet):
        with self._lock:
            if existing := self._fingerprints.get(artifact.integrity_hash):
                return existing
            history = self._history[artifact.logical_key]
            if artifact.version != len(history) + 1:
                raise SpecificationConflictError("SPECIFICATION_VERSION_CONFLICT")
            if artifact.specification_id in self._by_id:
                raise SpecificationConflictError("SPECIFICATION_IDENTITY_CONFLICT")
            self._by_id[artifact.specification_id] = artifact
            history.append(artifact)
            self._fingerprints[artifact.integrity_hash] = artifact
            return artifact

    def get(self, specification_id: str):
        return self._by_id.get(specification_id)

    def history(self, logical_key: str):
        return tuple(self._history.get(logical_key, ()))

    def append_review(self, review: SpecificationReview):
        with self._lock:
            if existing := next(
                (x for x in self._reviews if x.integrity_hash == review.integrity_hash),
                None,
            ):
                return existing
            self._reviews.append(review)
            return review

    def reviews(self, specification_id: str):
        return tuple(x for x in self._reviews if x.specification_id == specification_id)

    def append_audit(self, event: AuditEvent):
        with self._lock:
            if existing := next(
                (x for x in self._audits if x.integrity_hash == event.integrity_hash),
                None,
            ):
                return existing
            self._audits.append(event)
            return event

    def audits(self, specification_id: str | None = None):
        if specification_id is None:
            return tuple(self._audits)
        return tuple(x for x in self._audits if x.specification_id == specification_id)
