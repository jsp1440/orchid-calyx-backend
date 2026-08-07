"""Owner-gated API for governed relationship matrices."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.matrix_relationship import (
    RelationshipAssertion,
    build_relationship_matrix,
    compare_subjects,
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
            "pollinator",
            "mycorrhizal_partner",
            "habitat",
            "climate",
            "geography",
            "literature",
            "collection_taxon",
        ],
        "rules": [
            "not_recorded is not biological absence",
            "unknown is distinct from not_recorded",
            "present and absent assertions collapse to conflicting",
            "provenance is preserved at cell level",
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
