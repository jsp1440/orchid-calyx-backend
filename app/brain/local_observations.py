from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.brain.causal_scope import CausalScope, causal_scope_id, normalize_causal_scope
from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind, EvidenceInput, SourceAnchor
from runtime.knowledge_graph.causal_vocabulary import causal_relation_semantics
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository
from runtime.knowledge_graph.validation import validate_graph


class LocalObservationAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_id: int = Field(gt=0)
    ordered_span: int = Field(default=0, ge=0)
    block_id: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)


class LocalObservationRequest(BaseModel):
    """A single-plant observation that is evidence, not a general causal claim."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, max_length=240)
    plant_record_key: str = Field(min_length=1, max_length=240)
    taxon: str | None = Field(default=None, max_length=500)
    observed_at: datetime
    location_key: str | None = Field(default=None, max_length=240)
    response_type: Literal[
        "phenotype",
        "symptom",
        "physiology",
        "trait",
        "developmental_process",
    ] = "phenotype"
    response_label: str = Field(min_length=1, max_length=1000)
    observation_text: str = Field(min_length=1, max_length=50000)
    confidence: float = Field(default=0.75, ge=0, le=1)
    environmental_context: dict[str, Any] = Field(default_factory=dict)
    cultivation_context: dict[str, Any] = Field(default_factory=dict)
    treatment_context: dict[str, Any] = Field(default_factory=dict)
    matrix_context: dict[str, Any] = Field(default_factory=dict)
    source_object_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    extraction_run_id: int = Field(gt=0)
    source_anchors: list[LocalObservationAnchor] = Field(min_length=1)
    display_policy: str = "INTERNAL_RESEARCH_ONLY"
    internal_use_permission: bool = True

    @field_validator("observation_id", "plant_record_key")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("LOCAL_OBSERVATION_IDENTITY_REQUIRED")
        return normalized


def _scope(payload: LocalObservationRequest) -> dict[str, Any]:
    cultivation = {
        **payload.cultivation_context,
        "plant_record_key": payload.plant_record_key,
        "observed_at": payload.observed_at.isoformat(),
    }
    if payload.location_key:
        cultivation["location_key"] = payload.location_key
    scope = CausalScope(
        scope_class="bounded",
        taxa=[payload.taxon] if payload.taxon else [],
        environments=payload.environmental_context,
        treatments=payload.treatment_context,
        cultivation_context=cultivation,
        population_context={"plant_record_key": payload.plant_record_key, "n": 1},
        applicability_notes=(
            "Single-plant cultivation observation; not generalizable without "
            "independent evidence."
        ),
    )
    normalized_scope = normalize_causal_scope(scope)
    normalized_scope["cultivation_context"]["observed_at"] = (
        payload.observed_at.isoformat()
    )
    normalized_scope["scope_id"] = causal_scope_id(normalized_scope)
    return normalized_scope


def _graph_preview(
    payload: LocalObservationRequest, scope: dict[str, Any]
) -> dict[str, Any]:
    relationship = "observed_as"
    semantics = causal_relation_semantics(relationship)
    if semantics is None or semantics["causal"]:
        raise RuntimeError("LOCAL_OBSERVATION_RELATIONSHIP_MUST_BE_NONCAUSAL_EVIDENCE")
    plant = Node(
        kg_node_id=1,
        node_type="plant",
        canonical_key=f"plant:{payload.plant_record_key}",
        display_label=payload.plant_record_key,
        source_table="oc_candidate_knowledge.candidates",
        source_pk=payload.plant_record_key,
        evidence_class="local_cultivation_observation",
        confidence_score=payload.confidence,
        confidence_label="local_observation",
        payload={
            "candidate_only": True,
            "local_only": True,
            "plant_record_key": payload.plant_record_key,
            "taxon": payload.taxon,
        },
    )
    response_pk = f"local:{payload.observation_id}"
    response = Node(
        kg_node_id=2,
        node_type=payload.response_type,
        canonical_key=f"{payload.response_type}:{response_pk}",
        display_label=payload.response_label,
        source_table="oc_candidate_knowledge.candidates",
        source_pk=response_pk,
        evidence_class="local_cultivation_observation",
        confidence_score=payload.confidence,
        confidence_label="local_observation",
        payload={"candidate_only": True, "local_only": True},
    )
    edge = Edge(
        kg_edge_id=1,
        edge_type=relationship,
        from_node_id=1,
        to_node_id=2,
        source_table="oc_candidate_knowledge.candidates",
        source_pk=payload.observation_id,
        evidence_class="local_cultivation_observation",
        confidence_score=payload.confidence,
        confidence_label="local_observation",
        rule_name="BUILD_620_LOCAL_OBSERVATION_V1",
        payload={
            "candidate_only": True,
            "local_only": True,
            "observation_id": payload.observation_id,
            "causal_scope": scope,
            "matrix_context": payload.matrix_context,
            "environmental_context": payload.environmental_context,
            "cultivation_context": payload.cultivation_context,
            "treatment_context": payload.treatment_context,
        },
    )
    validation = validate_graph(InMemoryGraphRepository([plant, response], [edge]))
    if not validation["healthy"]:
        raise ValueError("LOCAL_OBSERVATION_GRAPH_INVALID")
    return {
        "nodes": [plant.to_dict(), response.to_dict()],
        "edges": [edge.to_dict()],
        "validation": validation,
        "semantics": dict(semantics),
        "governance": {
            "local_only": True,
            "candidate_only": True,
            "causal_claim": False,
            "species_level_generalization": False,
            "canonical_graph_mutated": False,
        },
    }


def handoff_local_observation(
    payload: LocalObservationRequest,
    components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    scope = _scope(payload)
    graph_preview = _graph_preview(payload, scope)
    repository, service = components or get_candidate_components()
    subject = f"plant:{payload.plant_record_key}:observation:{payload.observation_id}"
    evidence = EvidenceInput(
        source_object_type="conservatory_observation",
        source_object_id=payload.source_object_id,
        revision_id=payload.revision_id,
        extraction_run_id=payload.extraction_run_id,
        text=payload.observation_text,
        source_anchors=tuple(
            SourceAnchor(**anchor.model_dump()) for anchor in payload.source_anchors
        ),
        display_policy=payload.display_policy,
        internal_use_permission=payload.internal_use_permission,
        metadata={
            "source_confidence": payload.confidence,
            "candidate_facts": [
                {
                    "kind": CandidateKind.CULTIVATION_OBSERVATION.value,
                    "subject": subject,
                    "predicate": "observed_as",
                    "object_value": payload.response_label,
                    "qualifiers": {
                        "observation_id": payload.observation_id,
                        "plant_record_key": payload.plant_record_key,
                        "taxon": payload.taxon,
                        "observed_at": payload.observed_at.isoformat(),
                        "location_key": payload.location_key,
                        "response_type": payload.response_type,
                        "causal_scope": scope,
                        "matrix_context": payload.matrix_context,
                        "environmental_context": payload.environmental_context,
                        "cultivation_context": payload.cultivation_context,
                        "treatment_context": payload.treatment_context,
                        "local_observation": True,
                        "generalizable": False,
                    },
                    "confidence": payload.confidence,
                    "method": "BUILD_620_LOCAL_OBSERVATION_V1",
                }
            ],
        },
    )
    run = service.preview(
        [evidence],
        {
            "adapter": "build-620-local-observation-bridge",
            "observation_id": payload.observation_id,
            "plant_record_key": payload.plant_record_key,
        },
    )
    result = service.execute(run["candidate_run_id"])
    candidates = repository.candidates_for_run(run["candidate_run_id"])
    return {
        "contract": "calyx-local-observation-v1",
        "observation_id": payload.observation_id,
        "candidate_run_id": run["candidate_run_id"],
        "state": result["state"],
        "candidate_ids": sorted(item["candidate_id"] for item in candidates),
        "causal_scope": scope,
        "graph_preview": graph_preview,
        "local_only": True,
        "generalizable": False,
        "causal_claim": False,
        "review_required": True,
        "published": False,
        "canonical_graph_mutation": False,
        "scientific_publication_authority": False,
    }
