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


def _access_actor(auth: Any) -> str | None:
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    if auth.get("auth_type") == "api_key":
        return None
    actor = str(auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    return actor


@router.post("/{session_id}/explain")
def explain(
    session_id: str,
    payload: ExplanationRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return explain_session(
            session_id,
            audience=payload.audience,
            focus=payload.focus,
            access_actor=_access_actor(auth),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
