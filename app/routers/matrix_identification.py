"""Owner-gated API for governed character-matrix candidate ranking."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.matrix_identification import Candidate, Observation, rank_candidates


class ObservationInput(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    value: Any
    certainty: Literal["certain", "probable", "uncertain", "unknown"] = "certain"
    weight: float = Field(default=1.0, ge=0, le=100)


class CandidateInput(BaseModel):
    taxon_id: str = Field(min_length=1, max_length=200)
    scientific_name: str = Field(min_length=2, max_length=300)
    states: dict[str, Any]
    provenance: dict[str, Any] | None = None


class IdentificationRequest(BaseModel):
    observations: list[ObservationInput] = Field(min_length=1, max_length=200)
    candidates: list[CandidateInput] = Field(min_length=1, max_length=5000)
    limit: int = Field(default=20, ge=1, le=200)


router = APIRouter(prefix="/api/matrix-identification", tags=["matrix-identification"])


@router.get("/contract")
def contract(_: Any = Depends(verify_owner_or_api_key)) -> dict[str, Any]:  # noqa: B008
    return {
        "certainty_states": ["certain", "probable", "uncertain", "unknown"],
        "candidate_state_forms": [
            "scalar categorical value",
            "list of categorical values",
            "numeric value",
            {"min": "number", "max": "number"},
        ],
        "rules": [
            "unknown observations contribute no score",
            "missing candidate states reduce coverage but are not scored as absence",
            "uncertainty reduces effective character weight",
            "every score includes character-level explanations",
            "results rank candidates and do not assert an identification",
        ],
        "canonical_taxonomy_mutation": False,
        "collection_record_mutation": False,
    }


@router.post("/evaluate")
def evaluate(
    payload: IdentificationRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        observations = [Observation(**item.model_dump()) for item in payload.observations]
        candidates = [Candidate(**item.model_dump()) for item in payload.candidates]
        return rank_candidates(observations, candidates, limit=payload.limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
