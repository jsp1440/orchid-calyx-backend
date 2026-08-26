"""Owner-gated API for governed relationship matrices."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.matrix_relationship import (
    RelationshipAssertion,
    build_relationship_matrix,
    compare_subjects,
)
from runtime.matrix_relationship_sources import (
    governed_source_dimensions,
    load_governed_assertions,
)


class AssertionInput(BaseModel):
    subject_id: str = Field(min_length=1, max_length=200)
    subject_label: str = Field(min_length=1, max_length=300)
    dimension: str = Field(min_length=1, max_length=120)
    object_id: str = Field(min_length=1, max_length=200)
    object_label: str = Field(min_length=1, max_length=300)
    state: Literal[
        "present",
        "absent",
        "unknown",
        "not_recorded",
        "conflicting",
    ]
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: dict[str, Any] | None = None


class MatrixRequest(BaseModel):
    dimension: str = Field(min_length=1, max_length=120)
    assertions: list[AssertionInput] = Field(default_factory=list, max_length=10000)
    subject_ids: list[str] | None = Field(default=None, max_length=1000)
    object_ids: list[str] | None = Field(default=None, max_length=5000)


class CompareRequest(MatrixRequest):
    left_subject_id: str = Field(min_length=1, max_length=200)
    right_subject_id: str = Field(min_length=1, max_length=200)


class CanonicalSourceMatrixRequest(BaseModel):
    dimension: Literal[
        "pollinator",
        "mycorrhizal_partner",
        "literature",
        "trait",
        "conservation_status",
    ]
    subject_ids: list[str] | None = Field(default=None, max_length=1000)
    limit: int = Field(default=5000, ge=1, le=5000)


router = APIRouter(prefix="/api/matrix-relationship", tags=["matrix-relationship"])


@router.get("/contract")
def contract(_: Any = Depends(verify_owner_or_api_key)) -> dict[str, Any]:  # noqa: B008
    return {
        "states": [
            "present",
            "absent",
            "unknown",
            "not_recorded",
            "conflicting",
        ],
        "supported_dimensions": [
            "parentage",
            "morphology",
            "trait",
            "pollinator",
            "mycorrhizal_partner",
            "habitat",
            "climate",
            "geography",
            "literature",
            "conservation_status",
            "collection_taxon",
        ],
        "governed_source_dimensions": governed_source_dimensions(),
        "rules": [
            "not_recorded is not biological absence",
            "unknown is distinct from not_recorded",
            "present and absent assertions collapse to conflicting",
            "provenance is preserved at cell level",
            "canonical source retrieval is read-only and bounded",
            "all operations are read-only",
        ],
        "canonical_graph_mutation": False,
    }


def _assertions(payload: MatrixRequest) -> list[RelationshipAssertion]:
    return [RelationshipAssertion(**item.model_dump()) for item in payload.assertions]


@router.post("/build")
def build(
    payload: MatrixRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return build_relationship_matrix(
            _assertions(payload),
            dimension=payload.dimension,
            subject_ids=payload.subject_ids,
            object_ids=payload.object_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/build-from-canonical-source")
def build_from_canonical_source(
    payload: CanonicalSourceMatrixRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Build directly from verified canonical source-registry evidence."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=503,
            detail="canonical matrix source unavailable: DATABASE_URL is not configured",
        )
    try:
        assertions = load_governed_assertions(
            database_url,
            dimension=payload.dimension,
            subject_ids=payload.subject_ids,
            limit=payload.limit,
        )
        matrix = build_relationship_matrix(
            assertions,
            dimension=payload.dimension,
            subject_ids=payload.subject_ids,
        )
        matrix["source_mode"] = "canonical_governed_source"
        matrix["source_domain"] = {
            "pollinator": "pollinators",
            "mycorrhizal_partner": "mycorrhiza",
            "literature": "literature",
            "trait": "traits",
            "conservation_status": "conservation",
        }[payload.dimension]
        return matrix
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="canonical matrix source could not be read",
        ) from exc


@router.post("/compare")
def compare(
    payload: CompareRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        matrix = build_relationship_matrix(
            _assertions(payload),
            dimension=payload.dimension,
            subject_ids=payload.subject_ids,
            object_ids=payload.object_ids,
        )
        return {
            "matrix": matrix,
            "comparison": compare_subjects(
                matrix,
                payload.left_subject_id,
                payload.right_subject_id,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc