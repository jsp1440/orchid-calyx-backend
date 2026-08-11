"""Owner-gated structured Calyx explanations for Matrix Identification sessions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security import verify_owner_or_api_key
from runtime.matrix_identification_explanation import explain_session


class ExplanationRequest(BaseModel):
    audience: Literal["beginner", "intermediate", "expert"] = "intermediate"
    focus: Literal["summary", "next_observation", "candidate_comparison"] = "summary"


router = APIRouter(
    prefix="/api/matrix-identification/sessions",
    tags=["matrix-identification-explanations"],
)


@router.post("/{session_id}/explain")
def explain(
    session_id: str,
    payload: ExplanationRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return explain_session(
            session_id,
            audience=payload.audience,
            focus=payload.focus,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
