from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.evidence_retrieval.routes import ENGINE
from app.security import verify_owner_or_api_key

from .service import BrainMissionService, MemoryMissionRepository, MissionComponents


class MissionStartIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    project_id: str = Field(min_length=1, max_length=200)
    max_sources: int = Field(default=20, ge=1, le=100)
    max_execution_steps: int = Field(default=10, ge=1, le=10)
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)


def _retrieve(context: dict[str, Any], engine: RetrievalEngine = ENGINE) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    remaining = context["limits"]["max_sources"]
    for query in context["plan"]["retrieval_queries"]:
        if remaining <= 0:
            break
        response = engine.search(RetrievalQuery(text=query, mode="HYBRID", limit=remaining))
        results.extend(response["results"])
        remaining = context["limits"]["max_sources"] - len(results)
    return {"results": results}


REPOSITORY = MemoryMissionRepository()
SERVICE = BrainMissionService(
    MissionComponents(retrieve=_retrieve),
    REPOSITORY,
)
router = APIRouter(
    prefix="/api/brain/missions",
    tags=["brain-scientific-missions"],
    dependencies=[Depends(verify_owner_or_api_key)],
)
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]


@router.post("", status_code=201)
def start_mission(payload: MissionStartIn, auth: Auth):
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return SERVICE.start(
        question=payload.question,
        tenant_id=actor,
        project_id=payload.project_id,
        actor=actor,
        max_sources=payload.max_sources,
        max_steps=payload.max_execution_steps,
        timeout_seconds=payload.timeout_seconds,
    )


@router.get("/{mission_id}")
def get_mission(mission_id: str):
    try:
        return SERVICE.status(mission_id)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"}) from exc
