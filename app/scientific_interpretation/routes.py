from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .models import (
    AssertionRequest,
    CompletenessState,
    ContextForm,
    InterpretationRequest,
    RoutingPolicy,
    SourceAnchorReference,
    SourceEvidenceReference,
)
from .repository import MemoryInterpretationRepository
from .service import ScientificInterpretationService


def _repository():
    database_url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if database_url:
        from .postgres_repository import PostgresInterpretationRepository

        return PostgresInterpretationRepository(database_url)
    return MemoryInterpretationRepository()


REPOSITORY = _repository()
SERVICE = ScientificInterpretationService(REPOSITORY)
router = APIRouter(
    prefix="/api/scientific-interpretation",
    tags=["scientific-interpretation"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class AnchorIn(BaseModel):
    anchor_id: int = Field(gt=0)
    order: int = Field(ge=0)
    anchor_type: str = Field(min_length=1)
    locator: dict[str, Any]
    content_hash: str = Field(min_length=1)
    relationship: str = "CONTEXT"


class SourceIn(BaseModel):
    source_object_type: str = Field(min_length=1)
    source_object_id: int = Field(gt=0)
    source_revision_id: int = Field(gt=0)
    publication_metadata: dict[str, Any]
    copyright_policy: str = Field(min_length=1)
    provenance: dict[str, Any]
    anchors: list[AnchorIn] = Field(min_length=1)


class PacketIn(BaseModel):
    packet_key: str = Field(min_length=1)
    context_form: ContextForm
    sources: list[SourceIn] = Field(min_length=1)
    context_dimensions: dict[str, CompletenessState]
    material_dimensions: list[str]
    structural_relationships: list[dict[str, Any]] = []
    construction_policy_version: str = Field(min_length=1)
    boundary_analyzer_version: str = Field(min_length=1)
    construction_rationale: str = Field(min_length=1)


class InterpretationIn(BaseModel):
    packet_ids: list[int] = Field(min_length=1)
    interpretation_key: str = Field(min_length=1)
    statement: dict[str, Any]
    reasoning: dict[str, Any]
    confidence_factors: dict[str, float]
    ambiguities: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    model_version: str = "deterministic-1"
    ruleset_version: str = "build-087b-1"
    vocabulary_versions: dict[str, str] = {}
    configuration: dict[str, Any] = {}


class RoutingIn(BaseModel):
    interpretation_id: int = Field(gt=0)
    policy: dict[str, Any]
    independent_source_count: int = Field(ge=0)
    taxon_unambiguous: bool
    measurement_compatible: bool
    unresolved_contradiction: bool
    impact_class: str
    copyright_eligible: bool
    provenance_complete: bool


class AssertionIn(BaseModel):
    assertion_key: str = Field(min_length=1)
    normalized_statement: dict[str, Any]
    scientific_scope: dict[str, Any]
    supporting_interpretation_ids: list[int] = Field(min_length=1)
    conflicting_interpretation_ids: list[int] = []
    routing_decision_id: int = Field(gt=0)


class CorrectionIn(BaseModel):
    interpretation_id: int = Field(gt=0)
    correction_key: str = Field(min_length=1)
    error_category: str = Field(min_length=1)
    affected_field: str = Field(min_length=1)
    corrected_value: Any
    rationale: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reviewer_specialty: str = Field(min_length=1)
    applicability: dict[str, Any]
    permitted_use: str = Field(min_length=1)


def _domain_error(operation):
    try:
        return operation()
    except ValueError as exc:
        message = str(exc)
        status = 404 if message.endswith("NOT_FOUND") else 422
        raise HTTPException(status, detail={"code": message}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, detail={"code": "SCIENTIFIC_INTERPRETATION_UNAVAILABLE"}) from exc


@router.post("/evidence-packets", status_code=201)
def create_packet(payload: PacketIn):
    sources = tuple(
        SourceEvidenceReference(
            source_object_type=source.source_object_type,
            source_object_id=source.source_object_id,
            source_revision_id=source.source_revision_id,
            publication_metadata=source.publication_metadata,
            copyright_policy=source.copyright_policy,
            provenance=source.provenance,
            anchors=tuple(SourceAnchorReference(**anchor.model_dump()) for anchor in source.anchors),
        )
        for source in payload.sources
    )
    return _domain_error(lambda: SERVICE.construct_packet(
        packet_key=payload.packet_key,
        context_form=payload.context_form,
        sources=sources,
        context_dimensions=payload.context_dimensions,
        material_dimensions=tuple(payload.material_dimensions),
        structural_relationships=tuple(payload.structural_relationships),
        construction_policy_version=payload.construction_policy_version,
        boundary_analyzer_version=payload.boundary_analyzer_version,
        construction_rationale=payload.construction_rationale,
    ))


@router.post("/interpretations", status_code=201)
def create_interpretation(payload: InterpretationIn):
    request = InterpretationRequest(
        packet_ids=tuple(payload.packet_ids),
        interpretation_key=payload.interpretation_key,
        statement=payload.statement,
        reasoning=payload.reasoning,
        confidence_factors=payload.confidence_factors,
        ambiguities=tuple(payload.ambiguities),
        alternatives=tuple(payload.alternatives),
        model_version=payload.model_version,
        ruleset_version=payload.ruleset_version,
        vocabulary_versions=payload.vocabulary_versions,
        configuration=payload.configuration,
    )
    return _domain_error(lambda: SERVICE.interpret(request))


@router.post("/routing-decisions", status_code=201)
def evaluate_routing(payload: RoutingIn):
    policy = RoutingPolicy(**payload.policy)
    values = payload.model_dump(exclude={"policy"})
    return _domain_error(lambda: SERVICE.evaluate_routing(policy=policy, **values))


@router.post("/canonical-assertions", status_code=201)
def create_assertion(payload: AssertionIn):
    request = AssertionRequest(
        assertion_key=payload.assertion_key,
        normalized_statement=payload.normalized_statement,
        scientific_scope=payload.scientific_scope,
        supporting_interpretation_ids=tuple(payload.supporting_interpretation_ids),
        conflicting_interpretation_ids=tuple(payload.conflicting_interpretation_ids),
    )
    return _domain_error(lambda: SERVICE.create_assertion(request, payload.routing_decision_id))


@router.post("/corrections", status_code=201)
def create_correction(payload: CorrectionIn):
    return _domain_error(lambda: SERVICE.correct_interpretation(**payload.model_dump()))


@router.get("/audit/{artifact_type}/{artifact_id}")
def audit_history(artifact_type: str, artifact_id: int):
    return {"items": REPOSITORY.history(artifact_type.upper(), artifact_id)}


@router.get("/health")
def health():
    return {"status": "ok", "three_layers_separate": True, "publishes_graph": False, "immutable_evidence": True}


from app.scientific_synthesis.routes import router as scientific_synthesis_router

router.include_router(scientific_synthesis_router)
