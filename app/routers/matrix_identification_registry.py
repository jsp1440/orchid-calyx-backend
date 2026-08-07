"""Owner-gated API for immutable Matrix Identification registry versions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.matrix_identification import Observation, rank_candidates
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    candidates_from_registry,
    create_registry_version,
    get_registry_version,
    list_registry_versions,
)


class RegistryCharacterInput(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    value_type: Literal["categorical", "multi_state", "numeric", "numeric_range"] = (
        "categorical"
    )
    weight: float = Field(default=1.0, ge=0, le=100)
    provenance: dict[str, Any] | None = None


class RegistryCandidateInput(BaseModel):
    taxon_id: str = Field(min_length=1, max_length=200)
    scientific_name: str = Field(min_length=2, max_length=300)
    states: dict[str, Any]
    provenance: dict[str, Any] | None = None


class RegistryCreateRequest(BaseModel):
    registry_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    scope: dict[str, Any]
    characters: list[RegistryCharacterInput] = Field(min_length=1, max_length=500)
    candidates: list[RegistryCandidateInput] = Field(min_length=1, max_length=5000)
    provenance: dict[str, Any]
    actor: str = Field(min_length=1, max_length=200)


class RegistryObservationInput(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    value: Any
    certainty: Literal["certain", "probable", "uncertain", "unknown"] = "certain"
    weight: float | None = Field(default=None, ge=0, le=100)


class RegistryEvaluateRequest(BaseModel):
    registry_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    observations: list[RegistryObservationInput] = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=200)


router = APIRouter(
    prefix="/api/matrix-identification/registry",
    tags=["matrix-identification-registry"],
)


@router.get("")
def list_versions(_: Any = Depends(verify_owner_or_api_key)) -> dict[str, Any]:  # noqa: B008
    return {"versions": list_registry_versions(), "read_only_listing": True}


@router.get("/{registry_id}/{version}")
def get_version(
    registry_id: str,
    version: str,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return get_registry_version(registry_id, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("")
def create_version(
    payload: RegistryCreateRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        from runtime.matrix_identification import Candidate

        return create_registry_version(
            registry_id=payload.registry_id,
            version=payload.version,
            title=payload.title,
            scope=payload.scope,
            characters=[RegistryCharacter(**item.model_dump()) for item in payload.characters],
            candidates=[Candidate(**item.model_dump()) for item in payload.candidates],
            provenance=payload.provenance,
            actor=payload.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evaluate")
def evaluate_version(
    payload: RegistryEvaluateRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        record = get_registry_version(payload.registry_id, payload.version)
        character_weights = {
            item["character"]: float(item.get("weight", 1.0))
            for item in record.get("characters", [])
        }
        observations = [
            Observation(
                character=item.character,
                value=item.value,
                certainty=item.certainty,
                weight=(
                    item.weight
                    if item.weight is not None
                    else character_weights.get(item.character, 1.0)
                ),
            )
            for item in payload.observations
        ]
        result = rank_candidates(
            observations,
            candidates_from_registry(record),
            limit=payload.limit,
        )
        result["registry"] = {
            "registry_id": record["registry_id"],
            "version": record["version"],
            "checksum_sha256": record["checksum_sha256"],
            "publication_state": record["publication_state"],
        }
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
