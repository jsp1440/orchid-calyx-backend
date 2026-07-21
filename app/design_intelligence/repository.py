from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import (
    DesignDocument,
    DesignReviewDecision,
    PublicationStatus,
    ReviewState,
    utcnow,
)


class MemoryDesignCorpusRepository:
    """Append-only reference implementation mirroring the PostgreSQL schema."""

    def __init__(self) -> None:
        self.documents: list[DesignDocument] = []
        self.reviews: list[dict[str, Any]] = []
        self.publication_events: list[dict[str, Any]] = []
        self.audit_events: list[dict[str, Any]] = []

    def append_document(self, document: DesignDocument) -> DesignDocument:
        if any(item.document_id == document.document_id for item in self.documents):
            raise ValueError("DESIGN_DOCUMENT_ID_ALREADY_EXISTS")
        expected = 1 + max(
            (
                item.version
                for item in self.documents
                if item.logical_key == document.logical_key
            ),
            default=0,
        )
        if document.version != expected:
            raise ValueError("DESIGN_DOCUMENT_VERSION_NOT_MONOTONIC")
        self.documents.append(document)
        self._audit(
            "DOCUMENT_VERSION_APPENDED",
            document.document_id,
            {"version": document.version},
        )
        return document

    def latest(self, logical_key: str) -> DesignDocument | None:
        matches = [item for item in self.documents if item.logical_key == logical_key]
        return max(matches, key=lambda item: item.version) if matches else None

    def document(self, document_id: int) -> DesignDocument | None:
        return next(
            (item for item in self.documents if item.document_id == document_id), None
        )

    def add_review(
        self, document_id: int, decision: DesignReviewDecision
    ) -> dict[str, Any]:
        if not self.document(document_id):
            raise KeyError(document_id)
        record = {
            "review_id": len(self.reviews) + 1,
            "document_id": document_id,
            **asdict(decision),
            "created_at": utcnow(),
        }
        self.reviews.append(record)
        self._audit("REVIEW_DECISION_APPENDED", document_id, {"state": decision.state})
        return record

    def review_state(self, document_id: int) -> ReviewState:
        matches = [item for item in self.reviews if item["document_id"] == document_id]
        return matches[-1]["state"] if matches else ReviewState.PENDING

    def publish(
        self, document_id: int, status: PublicationStatus, actor: str, rationale: str
    ) -> dict[str, Any]:
        document = self.document(document_id)
        if not document:
            raise KeyError(document_id)
        current = self.publication_status(document_id)
        allowed = {
            PublicationStatus.DRAFT: {PublicationStatus.PUBLISHED},
            PublicationStatus.PUBLISHED: {
                PublicationStatus.RETIRED,
                PublicationStatus.RETRACTED,
            },
        }
        if status not in allowed.get(current, set()):
            raise ValueError("INVALID_DESIGN_PUBLICATION_TRANSITION")
        if (
            status is PublicationStatus.PUBLISHED
            and self.review_state(document_id) is not ReviewState.APPROVED
        ):
            raise ValueError("DESIGN_REVIEW_APPROVAL_REQUIRED")
        if not actor.strip() or not rationale.strip():
            raise ValueError("DESIGN_PUBLICATION_AUDIT_REQUIRED")
        event = {
            "publication_event_id": len(self.publication_events) + 1,
            "document_id": document_id,
            "status": status,
            "actor": actor,
            "rationale": rationale,
            "created_at": utcnow(),
        }
        self.publication_events.append(event)
        self._audit("PUBLICATION_STATUS_APPENDED", document_id, {"status": status})
        return event

    def publication_status(self, document_id: int) -> PublicationStatus:
        matches = [
            item
            for item in self.publication_events
            if item["document_id"] == document_id
        ]
        return matches[-1]["status"] if matches else PublicationStatus.DRAFT

    def published_latest(self) -> list[DesignDocument]:
        latest = {
            item.logical_key: self.latest(item.logical_key) for item in self.documents
        }
        return [
            item
            for item in latest.values()
            if item
            and self.publication_status(item.document_id) is PublicationStatus.PUBLISHED
        ]

    def _audit(
        self, event_type: str, document_id: int, details: dict[str, Any]
    ) -> None:
        self.audit_events.append(
            {
                "audit_id": len(self.audit_events) + 1,
                "document_id": document_id,
                "event_type": event_type,
                "details": details,
                "created_at": utcnow(),
            }
        )
