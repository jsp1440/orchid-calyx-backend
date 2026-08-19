"""Owner-gated API for immutable Matrix Identification registry versions."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.lexicon.routes import _load_entry_by_concept_id
from app.security import verify_owner_or_api_key
from runtime.matrix_identification import Observation, rank_candidates
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    candidates_from_registry,
    create_registry_version,
    derive_registry_version_with_concept_mappings,
    get_registry_version,
    list_registry_versions,
)


class RegistryCharacterInput(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    value_type: Literal["categorical", "multi_state", "numeric", "numeric_range"] = "categorical"
    weight: float = Field(default=1.0, ge=0, le=100)
    provenance: dict[str, Any] | None = None
    concept_id: str | None = Field(default=None, max_length=36)


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


class RegistryConceptMappingInput(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    concept_id: str = Field(min_length=36, max_length=36)


class RegistryConceptMappingDerivationRequest(BaseModel):
    new_version: str = Field(min_length=1, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    mappings: list[RegistryConceptMappingInput] = Field(min_length=1, max_length=500)
    review_note: str | None = Field(default=None, max_length=2000)


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


router = APIRouter(prefix="/api/matrix-identification/registry", tags=["matrix-identification-registry"])


def _actor(auth: Any) -> str:
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    actor = str(auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    return actor


def _persistence_unavailable(exc: RuntimeError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "MATRIX_REGISTRY_PERSISTENCE_UNAVAILABLE", "message": str(exc)},
    )


@router.get("")
def list_versions(_: Any = Depends(verify_owner_or_api_key)) -> dict[str, Any]:  # noqa: B008
    try:
        return {"versions": list_registry_versions(), "read_only_listing": True}
    except RuntimeError as exc:
        raise _persistence_unavailable(exc) from exc


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
    except RuntimeError as exc:
        raise _persistence_unavailable(exc) from exc


@router.get("/{registry_id}/{version}/concept-mapping-status")
def concept_mapping_status(
    registry_id: str,
    version: str,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        record = get_registry_version(registry_id, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _persistence_unavailable(exc) from exc

    characters: list[dict[str, Any]] = []
    mapped_approved = 0
    mapped_unavailable = 0
    invalid_mapping = 0
    unmapped = 0

    for item in record.get("characters", []):
        character_id = str(item.get("character") or "")
        concept_id = item.get("concept_id")
        status = "unmapped"
        concept_summary: dict[str, Any] | None = None
        if not concept_id:
            unmapped += 1
        else:
            try:
                concept_uuid = UUID(str(concept_id))
            except ValueError:
                status = "invalid_concept_id"
                invalid_mapping += 1
            else:
                entry = _load_entry_by_concept_id(concept_uuid)
                if entry is None:
                    status = "mapped_concept_unavailable"
                    mapped_unavailable += 1
                else:
                    status = "mapped_approved"
                    mapped_approved += 1
                    concept_summary = {
                        "concept_id": str(concept_id),
                        "preferred_term": entry.get("preferred_term"),
                        "review_state": entry.get("review_state"),
                        "source_system": entry.get("source_system"),
                        "source_record_id": entry.get("source_record_id"),
                    }
        characters.append(
            {
                "character": character_id,
                "label": item.get("label"),
                "weight": item.get("weight"),
                "concept_id": concept_id,
                "mapping_status": status,
                "concept": concept_summary,
            }
        )

    total = len(characters)
    return {
        "registry": {
            "registry_id": record.get("registry_id"),
            "version": record.get("version"),
            "checksum_sha256": record.get("checksum_sha256"),
            "publication_state": record.get("publication_state"),
        },
        "character_count": total,
        "mapped_approved_count": mapped_approved,
        "mapped_unavailable_count": mapped_unavailable,
        "invalid_mapping_count": invalid_mapping,
        "unmapped_count": unmapped,
        "approved_mapping_coverage": (mapped_approved / total) if total else 0.0,
        "ready_for_reviewed_lexicon_guidance": total > 0 and mapped_approved == total,
        "characters": characters,
        "automatic_concept_matching": False,
        "meaning": {
            "mapped_approved": "Character is explicitly bound to a currently ACTIVE + APPROVED canonical concept.",
            "mapped_concept_unavailable": "Registry retains a concept UUID, but that concept is not currently available as ACTIVE + APPROVED.",
            "invalid_concept_id": "Registry contains a malformed concept identifier and requires review.",
            "unmapped": "No canonical concept binding has been reviewed for this character.",
        },
    }


@router.post("")
def create_version(
    payload: RegistryCreateRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
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
            actor=_actor(auth),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _persistence_unavailable(exc) from exc


@router.post("/{registry_id}/{version}/derive-concept-mappings")
def derive_concept_mappings(
    registry_id: str,
    version: str,
    payload: RegistryConceptMappingDerivationRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    actor = _actor(auth)

    # Validate deterministic request-shape errors before any Lexicon/database access.
    seen_characters: set[str] = set()
    for mapping in payload.mappings:
        if mapping.character in seen_characters:
            raise HTTPException(
                status_code=422,
                detail=f"duplicate concept mapping for character: {mapping.character}",
            )
        seen_characters.add(mapping.character)

    mapping_by_character: dict[str, str] = {}
    approved_concepts: list[dict[str, Any]] = []
    for mapping in payload.mappings:
        try:
            concept_uuid = UUID(mapping.concept_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid canonical concept UUID for {mapping.character}",
            ) from exc
        entry = _load_entry_by_concept_id(concept_uuid)
        if entry is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "MATRIX_CONCEPT_MAPPING_NOT_APPROVED",
                    "character": mapping.character,
                    "concept_id": mapping.concept_id,
                    "message": "Concept mapping requires an ACTIVE + APPROVED canonical Lexicon concept.",
                },
            )
        mapping_by_character[mapping.character] = mapping.concept_id
        approved_concepts.append(
            {
                "character": mapping.character,
                "concept_id": mapping.concept_id,
                "preferred_term": entry.get("preferred_term"),
                "source_system": entry.get("source_system"),
                "source_record_id": entry.get("source_record_id"),
                "review_state": entry.get("review_state"),
            }
        )

    try:
        result = derive_registry_version_with_concept_mappings(
            registry_id=registry_id,
            source_version=version,
            new_version=payload.new_version,
            concept_mappings=mapping_by_character,
            actor=actor,
            title=payload.title,
            mapping_provenance={
                "reviewer": actor,
                "review_note": payload.review_note,
                "approved_concepts": approved_concepts,
                "policy": "explicit mappings only; no fuzzy matching or automatic concept promotion",
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _persistence_unavailable(exc) from exc

    record = result["record"]
    return {
        **result,
        "source_registry": {
            "registry_id": registry_id,
            "version": version,
        },
        "new_registry": {
            "registry_id": record["registry_id"],
            "version": record["version"],
            "checksum_sha256": record["checksum_sha256"],
            "publication_state": record["publication_state"],
        },
        "mapping_count": len(mapping_by_character),
        "automatic_concept_matching": False,
        "automatic_publication": False,
    }


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
                weight=item.weight if item.weight is not None else character_weights.get(item.character, 1.0),
            )
            for item in payload.observations
        ]
        result = rank_candidates(observations, candidates_from_registry(record), limit=payload.limit)
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
    except RuntimeError as exc:
        raise _persistence_unavailable(exc) from exc
