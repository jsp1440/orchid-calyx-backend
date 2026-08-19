"""Read-only discovery of governed Calyx Vision analyses for Matrix sessions."""

from __future__ import annotations

from typing import Any

from app.vision_lexicon.activation import build_vision_lexicon_service
from runtime.matrix_identification_session import get_session


def list_vision_analyses_for_image(
    session_id: str,
    image_id: str,
    *,
    access_actor: str | None = None,
    root=None,
    vision_service=None,
) -> dict[str, Any]:
    """List existing governed analyses after proving access to the Matrix session.

    This is intentionally read-only. It never requests provider inference, creates an
    analysis, promotes machine evidence, or changes Matrix scoring state.
    """
    get_session(session_id, root=root, access_actor=access_actor)
    image_id = str(image_id).strip()
    if not image_id:
        raise ValueError("image_id is required")

    service = vision_service or build_vision_lexicon_service()
    analyses = service.list_analyses_for_image(image_id)
    records = [
        {
            "analysis_id": str(item.analysis_id),
            "image_id": item.image_id,
            "reference_set_id": (
                str(item.reference_set_id) if item.reference_set_id else None
            ),
            "vision_model": item.vision_model,
            "vision_model_version": item.vision_model_version,
            "analysis_version": item.analysis_version,
            "taxon_context": item.taxon_context,
            "taxon_confidence": item.taxon_confidence,
            "calibration_state": str(item.calibration_state),
            "image_quality": str(item.image_quality),
            "analysis_status": str(item.analysis_status),
            "review_state": str(item.review_state),
            "warnings": list(item.warnings),
            "limitations": list(item.limitations),
        }
        for item in analyses
    ]
    records.sort(key=lambda item: (item["analysis_id"], item["vision_model"], item["vision_model_version"]))
    return {
        "session_id": session_id,
        "image_id": image_id,
        "analyses": records,
        "analysis_count": len(records),
        "provider_inference_requested": False,
        "matrix_state_mutated": False,
        "rule": "Discovery returns existing governed Vision analyses only.",
    }
