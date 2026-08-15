"""Review-gated bridge from governed Vision observations into Matrix sessions.

Vision records remain machine evidence until a reviewer explicitly accepts or
revises a suggestion for use in a Matrix Identification session. Rejection and
ambiguous mappings are retained as provenance and never scored as observations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from app.vision_lexicon.activation import build_vision_lexicon_service
from app.vision_lexicon.contracts import MeasurementBasis
from runtime.matrix_identification_registry import get_registry_version
from runtime.matrix_identification_session import _write, add_observation, get_session

VisionDecision = Literal["accept", "revise", "reject"]
VisionSuggestionState = Literal[
    "pending_review",
    "needs_mapping",
    "cannot_determine",
    "accepted",
    "revised",
    "rejected",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _registry_character_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["character"]): item
        for item in registry.get("characters", [])
        if item.get("character")
    }


def _unit_is_unambiguous(character: str, unit: str | None) -> bool:
    if not unit:
        return True
    normalized = unit.strip().casefold()
    suffixes = {
        "mm": "_mm",
        "cm": "_cm",
        "m": "_m",
        "deg": "_deg",
        "degree": "_deg",
        "degrees": "_deg",
        "ratio": "_ratio",
        "proportion": "_proportion",
    }
    suffix = suffixes.get(normalized)
    if suffix is None:
        return False
    return character.casefold().endswith(suffix)


def _proposed_value(observation: Any, character_meta: dict[str, Any]) -> tuple[Any, str]:
    """Return an unambiguous proposed Matrix value and mapping state."""
    if str(observation.measurement_basis) == str(MeasurementBasis.CANNOT_DETERMINE):
        return None, "cannot_determine"

    value_type = str(character_meta.get("value_type") or "categorical")
    if observation.numeric_value is not None:
        if value_type not in {"numeric", "numeric_range"}:
            return None, "needs_mapping"
        if not _unit_is_unambiguous(observation.character_id, observation.unit):
            return None, "needs_mapping"
        return observation.numeric_value, "pending_review"

    if observation.relative_value is not None:
        if value_type not in {"numeric", "numeric_range"}:
            return None, "needs_mapping"
        if observation.unit and not _unit_is_unambiguous(
            observation.character_id, observation.unit
        ):
            return None, "needs_mapping"
        return observation.relative_value, "pending_review"

    if observation.character_state_id:
        if value_type not in {"categorical", "multi_state"}:
            return None, "needs_mapping"
        return observation.character_state_id, "pending_review"

    return None, "needs_mapping"


def _suggestion_id(session_id: str, observation_id: UUID) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orchid-continuum:matrix-vision:{session_id}:{observation_id}",
        )
    )


def attach_vision_analysis(
    session_id: str,
    analysis_id: str,
    *,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
    vision_service=None,
) -> dict[str, Any]:
    """Attach governed Vision observations as review-required Matrix suggestions."""
    session = get_session(session_id, root=root, access_actor=access_actor)
    registry_ref = session["registry"]
    registry = get_registry_version(
        registry_ref["registry_id"],
        registry_ref["version"],
        root=registry_root,
    )
    if registry.get("checksum_sha256") != registry_ref.get("checksum_sha256"):
        raise ValueError("registry checksum drift detected for identification session")

    service = vision_service or build_vision_lexicon_service()
    analysis_uuid = UUID(analysis_id)
    analysis = service.get_analysis(analysis_uuid)
    if analysis is None:
        raise FileNotFoundError(f"vision analysis not found: {analysis_id}")

    character_map = _registry_character_map(registry)
    existing = {
        item.get("suggestion_id"): item
        for item in session.get("vision_suggestions", [])
        if item.get("suggestion_id")
    }
    added = 0
    for observation in service.list_observations_for_analysis(analysis_uuid):
        suggestion_id = _suggestion_id(session_id, observation.observation_id)
        if suggestion_id in existing:
            continue
        character_meta = character_map.get(observation.character_id)
        if character_meta is None:
            proposed_value = None
            state: VisionSuggestionState = "needs_mapping"
        else:
            proposed_value, state = _proposed_value(observation, character_meta)

        existing[suggestion_id] = {
            "suggestion_id": suggestion_id,
            "session_id": session_id,
            "analysis_id": str(observation.analysis_id),
            "vision_observation_id": str(observation.observation_id),
            "image_id": analysis.image_id,
            "region_id": str(observation.region_id) if observation.region_id else None,
            "concept_id": str(observation.concept_id) if observation.concept_id else None,
            "character": observation.character_id,
            "registry_character_found": character_meta is not None,
            "proposed_value": proposed_value,
            "character_state_id": observation.character_state_id,
            "numeric_value": observation.numeric_value,
            "relative_value": observation.relative_value,
            "unit": observation.unit,
            "measurement_basis": str(observation.measurement_basis),
            "machine_confidence": observation.confidence,
            "method": observation.method,
            "evidence_region": observation.evidence_region,
            "vision_review_state": str(observation.review_state),
            "limitations": list(observation.limitations),
            "vision_provenance": observation.provenance,
            "state": state,
            "created_at": _now(),
            "review": None,
            "matrix_observation_id": None,
        }
        added += 1

    session["vision_suggestions"] = list(existing.values())
    session.setdefault("vision_analyses", {})[analysis_id] = {
        "analysis_id": analysis_id,
        "image_id": analysis.image_id,
        "vision_model": analysis.vision_model,
        "vision_model_version": analysis.vision_model_version,
        "analysis_status": str(analysis.analysis_status),
        "review_state": str(analysis.review_state),
        "calibration_state": str(analysis.calibration_state),
        "warnings": list(analysis.warnings),
        "limitations": list(analysis.limitations),
        "attached_at": _now(),
    }
    session["updated_at"] = _now()
    _write(session, root=root)
    return {
        "session_id": session_id,
        "analysis_id": analysis_id,
        "added": added,
        "suggestions": session["vision_suggestions"],
        "rule": "Vision suggestions require explicit Matrix review before scoring.",
    }


def list_vision_suggestions(
    session_id: str,
    *,
    access_actor: str | None = None,
    root=None,
) -> dict[str, Any]:
    session = get_session(session_id, root=root, access_actor=access_actor)
    return {
        "session_id": session_id,
        "suggestions": session.get("vision_suggestions", []),
        "vision_analyses": session.get("vision_analyses", {}),
    }


def get_vision_region_for_suggestion(
    session_id: str,
    suggestion_id: str,
    *,
    access_actor: str | None = None,
    root=None,
    vision_service=None,
) -> dict[str, Any]:
    """Return governed region geometry for one attached Vision suggestion.

    Only returns a region already referenced by a suggestion attached to this
    session — this is a read within the same governed boundary as the
    suggestion review queue, not a general-purpose region lookup. Absence of
    geometry is returned as an explicit ``region: None`` rather than an
    error, since most suggestions today carry no region reference and that
    is a truthful state, not a failure.
    """
    session = get_session(session_id, root=root, access_actor=access_actor)
    suggestion = next(
        (
            item
            for item in session.get("vision_suggestions", [])
            if item.get("suggestion_id") == suggestion_id
        ),
        None,
    )
    if suggestion is None:
        raise FileNotFoundError(f"vision suggestion not found: {suggestion_id}")

    region_id = suggestion.get("region_id")
    if not region_id:
        return {"session_id": session_id, "suggestion_id": suggestion_id, "region": None}

    service = vision_service or build_vision_lexicon_service()
    region = service.get_region(UUID(region_id))
    if region is None or str(region.analysis_id) != str(suggestion.get("analysis_id")):
        return {"session_id": session_id, "suggestion_id": suggestion_id, "region": None}

    return {
        "session_id": session_id,
        "suggestion_id": suggestion_id,
        "region": {
            "region_id": str(region.region_id),
            "analysis_id": str(region.analysis_id),
            "concept_id": str(region.concept_id) if region.concept_id else None,
            "label": region.label,
            "bounding_box": region.bounding_box,
            "segmentation_ref": region.segmentation_ref,
            "landmarks": region.landmarks,
            "confidence": region.confidence,
            "review_state": str(region.review_state),
        },
    }


def review_vision_suggestion(
    session_id: str,
    suggestion_id: str,
    *,
    decision: VisionDecision,
    reviewer: str,
    certainty: str | None = None,
    revised_value: Any = None,
    comments: str | None = None,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Review one suggestion; only accepted/revised output enters Matrix evidence."""
    session = get_session(session_id, root=root, access_actor=access_actor)
    suggestions = session.get("vision_suggestions", [])
    suggestion = next(
        (item for item in suggestions if item.get("suggestion_id") == suggestion_id),
        None,
    )
    if suggestion is None:
        raise FileNotFoundError(f"vision suggestion not found: {suggestion_id}")
    if suggestion.get("state") in {"accepted", "revised", "rejected"}:
        raise ValueError("vision suggestion already has a final Matrix review decision")
    if not reviewer.strip():
        raise ValueError("reviewer identity is required")

    review = {
        "decision": decision,
        "reviewer": reviewer,
        "certainty": certainty,
        "comments": comments,
        "reviewed_at": _now(),
        "machine_value_preserved": suggestion.get("proposed_value"),
    }

    if decision == "reject":
        suggestion["state"] = "rejected"
        suggestion["review"] = review
        session["updated_at"] = _now()
        _write(session, root=root)
        return {"session": session, "suggestion": suggestion, "observation_added": False}

    if certainty not in {"certain", "probable", "uncertain", "unknown"}:
        raise ValueError("certainty is required for accepted or revised suggestions")

    if decision == "accept":
        if suggestion.get("state") != "pending_review":
            raise ValueError("suggestion cannot be accepted without an unambiguous Matrix mapping")
        value = suggestion.get("proposed_value")
        final_state: VisionSuggestionState = "accepted"
    elif decision == "revise":
        if revised_value is None:
            raise ValueError("revised_value is required when revising a Vision suggestion")
        value = revised_value
        final_state = "revised"
    else:
        raise ValueError(f"unsupported Vision review decision: {decision}")

    updated = add_observation(
        session_id,
        character=suggestion["character"],
        value=value,
        certainty=certainty,
        source={
            "kind": "vision_reviewed_observation",
            "decision": decision,
            "reviewer": reviewer,
            "analysis_id": suggestion["analysis_id"],
            "vision_observation_id": suggestion["vision_observation_id"],
            "image_id": suggestion.get("image_id"),
            "region_id": suggestion.get("region_id"),
            "concept_id": suggestion.get("concept_id"),
            "machine_confidence": suggestion.get("machine_confidence"),
            "vision_review_state": suggestion.get("vision_review_state"),
            "measurement_basis": suggestion.get("measurement_basis"),
            "unit": suggestion.get("unit"),
            "limitations": suggestion.get("limitations", []),
            "comments": comments,
        },
        actor=reviewer,
        access_actor=access_actor,
        root=root,
        registry_root=registry_root,
    )
    matrix_observation = updated["observations"][-1]

    session = get_session(session_id, root=root, access_actor=access_actor)
    suggestion = next(
        item
        for item in session.get("vision_suggestions", [])
        if item.get("suggestion_id") == suggestion_id
    )
    suggestion["state"] = final_state
    suggestion["review"] = review
    suggestion["matrix_observation_id"] = matrix_observation["observation_id"]
    suggestion["accepted_value"] = value
    session["updated_at"] = _now()
    _write(session, root=root)
    return {"session": session, "suggestion": suggestion, "observation_added": True}
