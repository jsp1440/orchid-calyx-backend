"""Structured Calyx explanations for Matrix Identification sessions.

Owner/API key, plus a signed-in member for a session they created (Release 1 journey
4). A member explanation is built from the member-shaped evaluation and always uses
the deterministic governed narrative: a member request never reaches a configured
generative provider (no provider spend on member traffic).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.calyx_conversation.provider import DeterministicGovernedReplyProvider
from app.matrix_member_access import (
    is_member,
    matrix_member_route,
    owner_or_matrix_member,
)
from app.matrix_member_views import member_evaluation
from runtime.matrix_identification_explanation import explain_session


class ExplanationRequest(BaseModel):
    audience: Literal["beginner", "intermediate", "expert"] = "intermediate"
    focus: Literal["summary", "next_observation", "candidate_comparison"] = "summary"


router = APIRouter(
    prefix="/api/matrix-identification/sessions",
    tags=["matrix-identification-explanations"],
    dependencies=[Depends(owner_or_matrix_member)],
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
@matrix_member_route("session_write")
def explain(
    session_id: str,
    payload: ExplanationRequest,
    auth: Any = Depends(owner_or_matrix_member),  # noqa: B008
) -> dict[str, Any]:
    if not is_member(auth):
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
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail=f"identification session not found: {session_id}"
        ) from exc
    try:
        return explain_session(
            session_id,
            audience=payload.audience,
            focus=payload.focus,
            provider=DeterministicGovernedReplyProvider(),
            access_actor=_access_actor(auth),
            evaluation_view=member_evaluation,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "MATRIX_SESSION_PERSISTENCE_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc
