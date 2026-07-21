from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    def default(item: Any):
        if isinstance(item, (datetime, StrEnum)):
            return item.isoformat() if isinstance(item, datetime) else item.value
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)
        raise TypeError(type(item).__name__)

    payload = json.dumps(value, default=default, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class RequirementStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"
    PROPOSED = "PROPOSED"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"


class CoverageOutcome(StrEnum):
    COVERED = "COVERED"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    NOT_PRESENT_IN_SOURCE_CORPUS = "NOT_PRESENT_IN_SOURCE_CORPUS"
    RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"


class LifecycleState(StrEnum):
    REQUEST_DRAFT = "REQUEST_DRAFT"
    REQUEST_VALIDATED = "REQUEST_VALIDATED"
    CONTEXT_RESOLVED = "CONTEXT_RESOLVED"
    EVIDENCE_RETRIEVED = "EVIDENCE_RETRIEVED"
    REASONING_IN_PROGRESS = "REASONING_IN_PROGRESS"
    PLAN_DRAFTED = "PLAN_DRAFTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    ESCALATED = "ESCALATED"
    SUPERSEDED = "SUPERSEDED"
    IMPLEMENTATION_AUTHORIZED = "IMPLEMENTATION_AUTHORIZED"
    IMPLEMENTED = "IMPLEMENTED"
    VALIDATED = "VALIDATED"


class ReviewRole(StrEnum):
    PRODUCT_OWNER = "PRODUCT_OWNER"
    UX = "UX"
    ACCESSIBILITY = "ACCESSIBILITY"
    SCIENTIFIC = "SCIENTIFIC"
    EDUCATIONAL = "EDUCATIONAL"
    TECHNICAL_FEASIBILITY = "TECHNICAL_FEASIBILITY"
    PRIVACY_SECURITY = "PRIVACY_SECURITY"
    BRANDING = "BRANDING"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CORRECTIONS = "APPROVE_WITH_CORRECTIONS"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"
    DEFER = "DEFER"
    ESCALATE = "ESCALATE"


class ConflictType(StrEnum):
    REQUIREMENT_VS_REQUIREMENT = "REQUIREMENT_VS_REQUIREMENT"
    REQUIREMENT_VS_ACCESSIBILITY = "REQUIREMENT_VS_ACCESSIBILITY"
    REQUIREMENT_VS_SCIENTIFIC_INTEGRITY = "REQUIREMENT_VS_SCIENTIFIC_INTEGRITY"
    REQUIREMENT_VS_SECURITY = "REQUIREMENT_VS_SECURITY"
    REQUIREMENT_VS_PRIVACY = "REQUIREMENT_VS_PRIVACY"
    REQUIREMENT_VS_RIGHTS = "REQUIREMENT_VS_RIGHTS"
    REQUIREMENT_VS_TECHNICAL_CONSTRAINT = "REQUIREMENT_VS_TECHNICAL_CONSTRAINT"
    REQUIREMENT_VS_DESIGN_GUIDANCE = "REQUIREMENT_VS_DESIGN_GUIDANCE"
    DESIGN_GUIDANCE_VS_DESIGN_GUIDANCE = "DESIGN_GUIDANCE_VS_DESIGN_GUIDANCE"
    BRANDING_VS_ACCESSIBILITY = "BRANDING_VS_ACCESSIBILITY"
    PERFORMANCE_VS_USABILITY = "PERFORMANCE_VS_USABILITY"
    EDUCATIONAL_VS_COGNITIVE_LOAD = "EDUCATIONAL_VS_COGNITIVE_LOAD"
    OTHER = "OTHER"


@dataclass(frozen=True)
class ProvenanceRef:
    source_type: str
    source_id: str
    version: str
    content_hash: str


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    category: str
    statement: str
    status: RequirementStatus
    source: str
    rationale: str
    priority: str
    hard_constraint: bool
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True)
class ProductRequest:
    request_id: str
    logical_key: str
    version: int
    supersedes_request_id: str | None
    product_name: str
    product_family: str
    requesting_actor: str
    business_objective: str
    scientific_objective: str
    educational_objective: str
    intended_users: tuple[str, ...]
    user_roles: tuple[str, ...]
    primary_tasks: tuple[str, ...]
    secondary_tasks: tuple[str, ...]
    required_data: tuple[str, ...]
    required_workflows: tuple[str, ...]
    platform_targets: tuple[str, ...]
    device_targets: tuple[str, ...]
    accessibility_requirements: tuple[str, ...]
    privacy_requirements: tuple[str, ...]
    security_requirements: tuple[str, ...]
    rights_and_licensing_constraints: tuple[str, ...]
    integration_dependencies: tuple[str, ...]
    performance_expectations: tuple[str, ...]
    branding_constraints: tuple[str, ...]
    known_design_decisions: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    excluded_scope: tuple[str, ...]
    priority: str
    requested_delivery_phase: str
    requirements: tuple[Requirement, ...]
    lifecycle_state: LifecycleState
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    item_type: str
    source_reference: str
    authority_level: int
    content_hash: str
    provenance: tuple[ProvenanceRef, ...]
    rights_classification: str
    effective_version: str
    status: str
    hard_constraint: bool = False


@dataclass(frozen=True)
class ProjectContextSnapshot:
    snapshot_id: str
    logical_key: str
    version: int
    product_request_id: str
    product_request_version: int
    items: tuple[ContextItem, ...]
    inaccessible_sources: tuple[str, ...]
    freshness_deadline: datetime
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class EvidenceResult:
    semantic_unit_id: str
    document_id: int
    source_location: dict[str, Any]
    citation: str
    score: float
    explanation: dict[str, float]
    provenance: dict[str, Any]
    rights_status: str
    bounded_excerpt: str | None = None


@dataclass(frozen=True)
class DesignEvidencePackage:
    evidence_package_id: str
    logical_key: str
    version: int
    supersedes_package_id: str | None
    product_request_id: str
    product_request_version: int
    project_context_snapshot_id: str
    affected_requirement_ids: tuple[str, ...]
    retrieval_queries: tuple[str, ...]
    normalized_queries: tuple[str, ...]
    corpus_version: str
    retrieval_provider_version: str
    embedding_provider_version: str
    filters: dict[str, tuple[str, ...]]
    ranked_results: tuple[EvidenceResult, ...]
    supporting_guidance: tuple[str, ...]
    conflicting_guidance: tuple[str, ...]
    related_concepts: tuple[str, ...]
    coverage: dict[str, CoverageOutcome]
    known_corpus_gaps: tuple[str, ...]
    confidence_factors: dict[str, float]
    rights_restrictions: tuple[str, ...]
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class DesignReasoningRecord:
    reasoning_record_id: str
    logical_key: str
    version: int
    supersedes_record_id: str | None
    product_request_id: str
    context_snapshot_id: str
    evidence_package_ids: tuple[str, ...]
    affected_product_area: str
    affected_user_roles: tuple[str, ...]
    affected_requirements: tuple[str, ...]
    recommendation: str
    considered_alternatives: tuple[str, ...]
    selected_approach: str
    rejected_alternatives: tuple[str, ...]
    concise_decision_rationale: str
    supporting_evidence_references: tuple[str, ...]
    conflicting_evidence_references: tuple[str, ...]
    assumptions: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    risks: tuple[str, ...]
    effects: dict[str, tuple[str, ...]]
    implementation_implications: tuple[str, ...]
    confidence_factors: dict[str, float]
    corpus_gaps: tuple[str, ...]
    reviewer_status: str
    lifecycle_state: LifecycleState
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class MaterialConflictRecord:
    conflict_id: str
    product_request_id: str
    context_snapshot_id: str
    evidence_package_ids: tuple[str, ...]
    conflict_type: ConflictType
    conflicting_references: tuple[str, ...]
    authority_levels: tuple[int, ...]
    severity: str
    affected_users: tuple[str, ...]
    affected_workflows: tuple[str, ...]
    hard_constraint: bool
    alternatives: tuple[str, ...]
    recommended_resolution: str
    evidence: tuple[str, ...]
    required_decision_owner_role: ReviewRole
    review_status: str
    disposition: str | None
    rationale: str
    supersession_reference: str | None
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class InterfacePlan:
    interface_plan_id: str
    logical_key: str
    version: int
    supersedes_plan_id: str | None
    product_request_id: str
    context_snapshot_id: str
    evidence_package_ids: tuple[str, ...]
    reasoning_record_ids: tuple[str, ...]
    conflict_record_ids: tuple[str, ...]
    sections: dict[str, Any]
    acceptance_criteria: tuple[dict[str, Any], ...]
    unresolved_questions: tuple[str, ...]
    corpus_gaps: tuple[str, ...]
    required_review_roles: tuple[ReviewRole, ...]
    lifecycle_state: LifecycleState
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    artifact_type: str
    artifact_id: str
    artifact_version: int
    artifact_hash: str
    reviewer_identity: str
    reviewer_role: ReviewRole
    decision: ReviewDecision
    structured_corrections: tuple[dict[str, Any], ...]
    rationale: str
    before_state: str
    after_state: str
    audit_context: dict[str, str]
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    artifact_type: str
    artifact_id: str
    artifact_version: int
    actor: str
    action: str
    rationale: str
    input_artifact_versions: dict[str, str]
    correlation_id: str
    created_at: datetime
    integrity_hash: str
