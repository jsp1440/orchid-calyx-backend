from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind, EvidenceInput, SourceAnchor
from runtime.knowledge_graph.causal_vocabulary import (
    CAUSAL_REASONING_NODE_TYPES,
    causal_relation_semantics,
)
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository
from runtime.knowledge_graph.validation import validate_graph


class MechanisticEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=500)
    stable_key: str | None = Field(default=None, min_length=1, max_length=500)
    attributes: dict[str, Any] = Field(default_factory=dict)


class MechanisticEvidenceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_id: int = Field(gt=0)
    ordered_span: int = Field(default=0, ge=0)
    page_number: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    block_id: str | None = None
    logical_unit: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)


class MechanisticCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning_id: str = Field(min_length=1, max_length=240)
    source: MechanisticEndpoint
    relationship: str = Field(min_length=1, max_length=120)
    target: MechanisticEndpoint
    confidence: float = Field(ge=0, le=1)
    evidence_text: str = Field(min_length=1, max_length=50000)
    source_object_type: str = Field(min_length=1, max_length=120)
    source_object_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    extraction_run_id: int = Field(gt=0)
    source_anchors: list[MechanisticEvidenceAnchor] = Field(min_length=1)
    experimental_context: dict[str, Any] = Field(default_factory=dict)
    quantitative_context: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"


def _stable_source_pk(endpoint: MechanisticEndpoint) -> str:
    if endpoint.stable_key:
        return endpoint.stable_key.strip()
    digest = hashlib.sha256(
        f"{endpoint.node_type.strip().lower()}:{endpoint.label.strip().casefold()}".encode()
    ).hexdigest()
    return f"candidate-{digest[:24]}"


def _candidate_graph(
    payload: MechanisticCandidateRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    relationship = payload.relationship.strip().lower()
    semantics = causal_relation_semantics(relationship)
    if semantics is None or not semantics["causal"]:
        raise ValueError("CONTROLLED_CAUSAL_RELATIONSHIP_REQUIRED")

    source_type = payload.source.node_type.strip().lower()
    target_type = payload.target.node_type.strip().lower()
    source_label = payload.source.label.strip()
    target_label = payload.target.label.strip()
    if not source_label:
        raise ValueError("MECHANISTIC_SOURCE_LABEL_REQUIRED")
    if not target_label:
        raise ValueError("MECHANISTIC_TARGET_LABEL_REQUIRED")
    if source_type not in CAUSAL_REASONING_NODE_TYPES:
        raise ValueError(f"UNAPPROVED_CAUSAL_SOURCE_TYPE:{source_type}")
    if target_type not in CAUSAL_REASONING_NODE_TYPES:
        raise ValueError(f"UNAPPROVED_CAUSAL_TARGET_TYPE:{target_type}")

    source_pk = _stable_source_pk(payload.source)
    target_pk = _stable_source_pk(payload.target)
    preview_source = "synthetic.mechanistic_candidate_preview"
    evidence_identity = {
        "source_object_type": payload.source_object_type,
        "source_object_id": payload.source_object_id,
        "revision_id": payload.revision_id,
        "extraction_run_id": payload.extraction_run_id,
        "anchor_ids": [anchor.anchor_id for anchor in payload.source_anchors],
    }
    source = Node(
        kg_node_id=1,
        node_type=source_type,
        canonical_key=f"{source_type}:{source_pk}",
        display_label=source_label,
        source_table=preview_source,
        source_pk=source_pk,
        evidence_class="candidate_mechanistic_claim",
        confidence_score=payload.confidence,
        confidence_label="candidate",
        payload={
            **payload.source.attributes,
            "candidate_only": True,
            "preview_provenance": evidence_identity,
        },
    )
    target = Node(
        kg_node_id=2,
        node_type=target_type,
        canonical_key=f"{target_type}:{target_pk}",
        display_label=target_label,
        source_table=preview_source,
        source_pk=target_pk,
        evidence_class="candidate_mechanistic_claim",
        confidence_score=payload.confidence,
        confidence_label="candidate",
        payload={
            **payload.target.attributes,
            "candidate_only": True,
            "preview_provenance": evidence_identity,
        },
    )
    edge = Edge(
        kg_edge_id=1,
        edge_type=relationship,
        from_node_id=1,
        to_node_id=2,
        source_table=preview_source,
        source_pk=payload.reasoning_id.strip(),
        evidence_class="candidate_mechanistic_claim",
        confidence_score=payload.confidence,
        confidence_label="candidate",
        rule_name="BUILD_615_MECHANISTIC_CANDIDATE_V1",
        payload={
            "reasoning_id": payload.reasoning_id,
            "candidate_only": True,
            "preview_provenance": evidence_identity,
            "experimental_context": payload.experimental_context,
            "quantitative_context": payload.quantitative_context,
            "provenance": payload.provenance,
            "anchor_ids": [anchor.anchor_id for anchor in payload.source_anchors],
        },
    )
    graph = InMemoryGraphRepository([source, target], [edge])
    validation = validate_graph(graph)
    if not validation["healthy"]:
        raise ValueError("MECHANISTIC_CANDIDATE_GRAPH_INVALID")

    preview = {
        "nodes": [source.to_dict(), target.to_dict()],
        "edges": [edge.to_dict()],
        "validation": validation,
        "semantics": dict(semantics),
        "governance": {
            "candidate_only": True,
            "review_required": True,
            "canonical_graph_mutated": False,
            "automatically_published": False,
        },
    }
    qualifiers = {
        "graph_contract": {
            "source_node_type": source_type,
            "source_key": source.canonical_key,
            "target_node_type": target_type,
            "target_key": target.canonical_key,
            "relationship": relationship,
            "role": semantics["role"],
            "polarity": semantics["polarity"],
            "causal": semantics["causal"],
        },
        "experimental_context": payload.experimental_context,
        "quantitative_context": payload.quantitative_context,
        "provenance": payload.provenance,
        "graph_validation": {
            "healthy": validation["healthy"],
            "total_problems": validation["total_problems"],
        },
    }
    return preview, qualifiers


def _candidate_ids_for_run(repository: Any, run_id: int) -> list[int]:
    candidate_ids = {
        item["candidate_id"] for item in repository.candidates_for_run(run_id)
    }
    candidate_ids.update(
        review["candidate_id"]
        for review in repository.reviews.values()
        if review.get("candidate_run_id") == run_id
        and review.get("candidate_id") is not None
    )
    return sorted(candidate_ids)


def handoff_mechanistic_candidate(
    payload: MechanisticCandidateRequest,
    components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    repository, service = components or get_candidate_components()

    def operation() -> dict[str, Any]:
        graph_preview, qualifiers = _candidate_graph(payload)
        evidence = EvidenceInput(
            source_object_type=payload.source_object_type,
            source_object_id=payload.source_object_id,
            revision_id=payload.revision_id,
            extraction_run_id=payload.extraction_run_id,
            text=payload.evidence_text,
            source_anchors=tuple(
                SourceAnchor(**anchor.model_dump()) for anchor in payload.source_anchors
            ),
            display_policy=payload.display_policy,
            internal_use_permission=payload.internal_use_permission,
            language=payload.language,
            metadata={
                "reasoning_id": payload.reasoning_id,
                "source_confidence": payload.confidence,
                "candidate_facts": [
                    {
                        "kind": CandidateKind.MECHANISTIC_RELATIONSHIP.value,
                        "subject": payload.source.label.strip(),
                        "predicate": payload.relationship.strip().lower(),
                        "object_value": payload.target.label.strip(),
                        "qualifiers": qualifiers,
                        "confidence": payload.confidence,
                        "method": "BUILD_615_MECHANISTIC_CANDIDATE_V1",
                    }
                ],
            },
        )
        run = service.preview(
            [evidence],
            {
                "adapter": "build-615-mechanistic-candidate-graph",
                "reasoning_id": payload.reasoning_id,
            },
        )
        result = service.execute(run["candidate_run_id"])
        return {
            "reasoning_id": payload.reasoning_id,
            "candidate_run_id": run["candidate_run_id"],
            "state": result["state"],
            "candidate_ids": _candidate_ids_for_run(
                repository, run["candidate_run_id"]
            ),
            "graph_preview": graph_preview,
            "review_required": True,
            "published": False,
            "canonical_graph_mutation": False,
            "scientific_publication_authority": False,
        }

    if hasattr(repository, "atomic"):
        return repository.atomic(operation)
    return operation()
