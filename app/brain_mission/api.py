from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .routes import SERVICE


class MissionStartRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    project_id: str = Field(min_length=1, max_length=200)
    max_sources: int = Field(default=20, ge=1, le=100)
    max_execution_steps: int = Field(default=10, ge=1, le=10)
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)


AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
router = APIRouter(prefix="/missions", tags=["brain-scientific-missions"])


def _subject(auth: dict[str, Any]) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


@router.post("", status_code=201)
def start_mission(
    payload: MissionStartRequest,
    auth: AuthDependency,
) -> dict[str, Any]:
    subject = _subject(auth)
    try:
        return SERVICE.start(
            question=payload.question,
            tenant_id=subject,
            project_id=payload.project_id,
            actor=subject,
            max_sources=payload.max_sources,
            max_steps=payload.max_execution_steps,
            timeout_seconds=payload.timeout_seconds,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.get("/{mission_id}")
def get_mission(mission_id: str, auth: AuthDependency) -> dict[str, Any]:
    subject = _subject(auth)
    try:
        mission = SERVICE.status(mission_id)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"}) from exc
    if mission.get("tenant_id") != subject:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"})
    return mission
