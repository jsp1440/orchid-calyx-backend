from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class PublicationStatus(StrEnum):
    PREPARED = "prepared"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    PUBLISHED = "published"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


@dataclass(frozen=True)
class PublicationArtifact:
    publication_artifact_id: str
    artifact_hash: str
    ledger_id: str
    ledger_version: int
    review_content_hash: str
    approval_id: str
    approval_decision: str
    approval_timestamp: datetime
    reviewer_identity: str
    submitting_actor: str
    owner_identity: str
    project_id: str
    subject_canonical_node_id: int
    subject_canonical_key: str
    object_canonical_node_id: int | None
    object_canonical_key: str | None
    canonical_literal_value: Any | None
    predicate: str
    graph_operation_type: str
    supporting_evidence_references: tuple[str, ...]
    counterevidence_references: tuple[str, ...]
    literature_evidence_ids: tuple[str, ...]
    source_document_hashes: tuple[str, ...]
    inference_family: str
    inference_rule_id: str
    inference_rule_version: str
    confidence: float
    rationale: str
    provenance_chain: tuple[dict[str, Any], ...]
    originating_candidate_ids: tuple[str, ...]
    originating_inference_hash: str
    canonical_assertion_id: int
    canonical_assertion_version: int
    policy_id: str
    policy_version: int
    created_at: datetime
    publication_status: PublicationStatus = PublicationStatus.PREPARED
    publication_gate_result: dict[str, Any] | None = None
    canonical_graph_ids: tuple[str, ...] = ()
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["publication_status"] = self.publication_status.value
        result["approval_timestamp"] = self.approval_timestamp.isoformat()
        result["created_at"] = self.created_at.isoformat()
        return result
