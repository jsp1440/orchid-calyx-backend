"""Owner-gated Vision-to-Matrix review bridge routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security import verify_owner_or_api_key
from runtime.matrix_identification_vision import (
    attach_vision_analysis,
    list_vision_suggestions,
    review_vision_suggestion,
)

router = APIRouter(
    prefix="/api/matrix-identification/sessions",
    tags=["matrix-identification-vision"],
)


class VisionSuggestionReviewRequest(BaseModel):
    decision: Literal["accept", "revise", "reject"]
    certainty: Literal["certain", "probable", "uncertain", "unknown"] | None = None
    revised_value: Any = None
    comments: str | None = None


def _actor(auth: dict[str, Any]) -> str:
    actor = str(auth.get("actor") or auth.get("subject") or auth.get("owner") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authenticated reviewer identity required")
    return actor


@router.post("/{session_id}/vision/analyses/{analysis_id}/suggestions")
def attach_analysis(
    session_id: str,
    analysis_id: str,
    _: dict[str, Any] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return attach_vision_analysis(session_id, analysis_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{session_id}/vision/suggestions")
def get_suggestions(
    session_id: str,
    _: dict[str, Any] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return list_vision_suggestions(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{session_id}/vision/suggestions/{suggestion_id}/review")
def review_suggestion(
    session_id: str,
    suggestion_id: str,
    payload: VisionSuggestionReviewRequest,
    auth: dict[str, Any] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return review_vision_suggestion(
            session_id,
            suggestion_id,
            decision=payload.decision,
            reviewer=_actor(auth),
            certainty=payload.certainty,
            revised_value=payload.revised_value,
            comments=payload.comments,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
