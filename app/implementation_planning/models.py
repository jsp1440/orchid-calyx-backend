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
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, StrEnum):
            return item.value
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)
        raise TypeError(type(item).__name__)

    encoded = json.dumps(value, default=default, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class ReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class SpecificationLifecycle(StrEnum):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    IMPLEMENTATION_AUTHORIZED = "IMPLEMENTATION_AUTHORIZED"


@dataclass(frozen=True)
class ArtifactReference:
    artifact_type: str
    artifact_id: str
    version: int
    integrity_hash: str


@dataclass(frozen=True)
class PageSpecification:
    page_id: str
    page_name: str
    route: str
    route_parameters: tuple[str, ...]
    purpose: str
    permitted_roles: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    source_planning_references: tuple[str, ...]
    layout_regions: tuple[str, ...]
    primary_sections: tuple[str, ...]
    secondary_sections: tuple[str, ...]
    required_components: tuple[str, ...]
    required_data: tuple[str, ...]
    backend_capabilities: tuple[str, ...]
    api_contract_ids: tuple[str, ...]
    request_models: tuple[str, ...]
    response_models: tuple[str, ...]
    behaviors: dict[str, Any]
    telemetry_events: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    unresolved_dependencies: tuple[str, ...]
    readiness_status: ReadinessStatus


@dataclass(frozen=True)
class ComponentSpecification:
    component_id: str
    component_name: str
    purpose: str
    reuse_locations: tuple[str, ...]
    inputs: dict[str, str]
    outputs: dict[str, str]
    properties: dict[str, str]
    emitted_events: tuple[str, ...]
    internal_state: tuple[str, ...]
    behaviors: dict[str, Any]
    dependencies: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    readiness_status: ReadinessStatus


@dataclass(frozen=True)
class NavigationSpecification:
    navigation_id: str
    route_registry: tuple[dict[str, Any], ...]
    graph: dict[str, tuple[str, ...]]
    rules: dict[str, Any]


@dataclass(frozen=True)
class StateSpecification:
    state_id: str
    domain: str
    ownership: str
    scope: str
    source_of_truth: str
    initialization: str
    transitions: tuple[str, ...]
    persistence: str
    invalidation: str
    synchronization: str
    optimistic_updates: str
    rollback_behavior: str
    conflict_behavior: str
    offline_behavior: str
    privacy_restrictions: tuple[str, ...]


@dataclass(frozen=True)
class ApiContractSpecification:
    contract_id: str
    capability: str
    status: str
    existing_endpoint: str | None
    existing_service: str | None
    existing_model: str | None
    source_planning_artifact: str
    proposed_contract: dict[str, Any] | None
    authorization_requirement: str
    readiness_status: ReadinessStatus
    exact_dependency: str | None


@dataclass(frozen=True)
class DataContractSpecification:
    contract_id: str
    name: str
    fields: dict[str, str]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    validation_rules: tuple[str, ...]
    units: dict[str, str]
    uncertainty_representation: str
    provenance_requirements: tuple[str, ...]
    privacy_classification: str
    serialization: str
    versioning: str
    readiness_status: ReadinessStatus


@dataclass(frozen=True)
class CrossCuttingContract:
    contract_id: str
    contract_type: str
    rules: tuple[str, ...]
    page_mappings: dict[str, tuple[str, ...]]
    component_mappings: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ConflictImpact:
    conflict_id: str
    title: str
    status: str
    affected_pages: tuple[str, ...]
    affected_components: tuple[str, ...]
    affected_api_contracts: tuple[str, ...]
    affected_acceptance_criteria: tuple[str, ...]
    decision_owner: str
    blocked_work: tuple[str, ...]


@dataclass(frozen=True)
class ImplementationPhase:
    phase_id: str
    name: str
    prerequisites: tuple[str, ...]
    deliverables: tuple[str, ...]
    dependencies: tuple[str, ...]
    blockers: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    recommended_build: str
    readiness_status: ReadinessStatus


@dataclass(frozen=True)
class ReadinessRecord:
    readiness_id: str
    artifact_type: str
    artifact_id: str
    status: ReadinessStatus
    exact_dependency: str | None
    source_artifact: str
    responsible_role: str
    recommended_next_build: str


@dataclass(frozen=True)
class ImplementationSpecificationSet:
    specification_id: str
    logical_key: str
    version: int
    supersedes_specification_id: str | None
    source_artifacts: tuple[ArtifactReference, ...]
    source_plan_lifecycle: str
    evidence_package_ids: tuple[str, ...]
    reasoning_record_ids: tuple[str, ...]
    conflict_record_ids: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...]
    corpus_gaps: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    rights_restrictions: tuple[str, ...]
    review_requirements: tuple[str, ...]
    pages: tuple[PageSpecification, ...]
    components: tuple[ComponentSpecification, ...]
    navigation: NavigationSpecification
    states: tuple[StateSpecification, ...]
    api_contracts: tuple[ApiContractSpecification, ...]
    data_contracts: tuple[DataContractSpecification, ...]
    cross_cutting_contracts: tuple[CrossCuttingContract, ...]
    conflict_impacts: tuple[ConflictImpact, ...]
    sequence: tuple[ImplementationPhase, ...]
    readiness: tuple[ReadinessRecord, ...]
    lifecycle_state: SpecificationLifecycle
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class SpecificationReview:
    review_id: str
    specification_id: str
    specification_hash: str
    reviewer: str
    reviewer_role: str
    decision: str
    rationale: str
    corrections: tuple[dict[str, Any], ...]
    created_at: datetime
    integrity_hash: str


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    specification_id: str
    actor: str
    action: str
    source_artifact_ids: tuple[str, ...]
    rationale: str
    created_at: datetime
    integrity_hash: str
