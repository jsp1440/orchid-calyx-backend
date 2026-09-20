"""Canonical, version-bound evidence feedback records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FeedbackClass(str, Enum):
    REPORT_PROBLEM = "report_problem"
    SUGGEST_CORRECTION = "suggest_correction"
    CHALLENGE = "challenge"
    ADD_EVIDENCE = "add_evidence"
    CONFIRM = "confirm"
    SOURCE_PROBLEM = "source_problem"
    IMAGE_IDENTIFICATION_PROBLEM = "image_identification_problem"


class ObjectType(str, Enum):
    LEXICON = "lexicon"
    MATRIX_IDENTIFICATION = "matrix_identification"
    TAXONOMY = "taxonomy"
    IMAGE_ANNOTATION = "image_annotation"
    LITERATURE_CLAIM = "literature_claim"
    STRUCTURED_CHARACTER = "structured_character"
    DISTRIBUTION_RECORD = "distribution_record"
    OTHER = "other"


class Disposition(str, Enum):
    AUTO_CORRECTABLE = "auto_correctable"
    NEEDS_SCIENTIFIC_REVIEW = "needs_scientific_review"
    NEEDS_TAXONOMIC_REVIEW = "needs_taxonomic_review"
    NEEDS_RIGHTS_REVIEW = "needs_rights_review"
    NEEDS_SOURCE_PARTNER_REVIEW = "needs_source_partner_review"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DUPLICATE = "duplicate"
    VALID_BUT_NO_CHANGE = "valid_but_no_change"
    CORRECTION_ACCEPTED = "correction_accepted"
    CORRECTION_REJECTED = "correction_rejected"


class CaseStatus(str, Enum):
    SUBMITTED = "submitted"
    PENDING_REVIEW = "pending_review"
    RESOLVED = "resolved"


class ReviewLane(str, Enum):
    DETERMINISTIC = "deterministic"
    SCIENTIFIC = "scientific"
    TAXONOMIC = "taxonomic"
    RIGHTS = "rights"
    SOURCE_PARTNER = "source_partner"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def feedback_fingerprint(
    *,
    object_id: str,
    object_version_hash: str,
    feedback_class: FeedbackClass,
    statement: str,
    proposed_replacement: str | None,
    citation: str | None,
) -> str:
    payload = {
        "object_id": object_id.strip(),
        "object_version_hash": object_version_hash.strip().casefold(),
        "feedback_class": feedback_class.value,
        "statement": " ".join(statement.split()).casefold(),
        "proposed_replacement": (
            " ".join(proposed_replacement.split()).casefold()
            if proposed_replacement
            else None
        ),
        "citation": citation.strip() if citation else None,
    }
    return content_hash(payload)


@dataclass(frozen=True, slots=True)
class EvidenceObjectVersion:
    object_id: str
    object_type: ObjectType
    version_hash: str
    payload: dict[str, Any]
    created_at: str
    previous_version_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "version_hash": self.version_hash,
            "payload": self.payload,
            "created_at": self.created_at,
            "previous_version_hash": self.previous_version_hash,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceObjectVersion:
        return cls(
            object_id=str(value["object_id"]),
            object_type=ObjectType(value["object_type"]),
            version_hash=str(value["version_hash"]),
            payload=dict(value["payload"]),
            created_at=str(value["created_at"]),
            previous_version_hash=value.get("previous_version_hash"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceFeedbackCase:
    case_id: str
    fingerprint: str
    object_id: str
    object_version_hash: str
    object_type: ObjectType
    page_context: str
    feedback_class: FeedbackClass
    statement: str
    disposition: Disposition
    status: CaseStatus
    review_lane: ReviewLane
    created_at: str
    updated_at: str
    proposed_replacement: str | None = None
    citation: str | None = None
    submitter_id: str | None = None
    source_partner_id: str | None = None
    defect_kind: str | None = None
    severity: str = "normal"
    related_case_ids: tuple[str, ...] = field(default_factory=tuple)
    resolution: str | None = None
    resulting_version_hash: str | None = None
    reviewer_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "fingerprint": self.fingerprint,
            "object_id": self.object_id,
            "object_version_hash": self.object_version_hash,
            "object_type": self.object_type.value,
            "page_context": self.page_context,
            "feedback_class": self.feedback_class.value,
            "statement": self.statement,
            "disposition": self.disposition.value,
            "status": self.status.value,
            "review_lane": self.review_lane.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "proposed_replacement": self.proposed_replacement,
            "citation": self.citation,
            "submitter_id": self.submitter_id,
            "source_partner_id": self.source_partner_id,
            "defect_kind": self.defect_kind,
            "severity": self.severity,
            "related_case_ids": list(self.related_case_ids),
            "resolution": self.resolution,
            "resulting_version_hash": self.resulting_version_hash,
            "reviewer_id": self.reviewer_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceFeedbackCase:
        return cls(
            case_id=str(value["case_id"]),
            fingerprint=str(value["fingerprint"]),
            object_id=str(value["object_id"]),
            object_version_hash=str(value["object_version_hash"]),
            object_type=ObjectType(value["object_type"]),
            page_context=str(value["page_context"]),
            feedback_class=FeedbackClass(value["feedback_class"]),
            statement=str(value["statement"]),
            disposition=Disposition(value["disposition"]),
            status=CaseStatus(value["status"]),
            review_lane=ReviewLane(value["review_lane"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            proposed_replacement=value.get("proposed_replacement"),
            citation=value.get("citation"),
            submitter_id=value.get("submitter_id"),
            source_partner_id=value.get("source_partner_id"),
            defect_kind=value.get("defect_kind"),
            severity=str(value.get("severity") or "normal"),
            related_case_ids=tuple(value.get("related_case_ids") or ()),
            resolution=value.get("resolution"),
            resulting_version_hash=value.get("resulting_version_hash"),
            reviewer_id=value.get("reviewer_id"),
        )
