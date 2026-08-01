from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .service import CalyxAgentService
from .tools import default_tool_registry

router = APIRouter(
    prefix="/agent",
    tags=["calyx-agent"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
)


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=12000)


def get_agent_service() -> CalyxAgentService:
    return CalyxAgentService()


ServiceDependency = Annotated[CalyxAgentService, Depends(get_agent_service)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


def _actor(auth: dict[str, Any]) -> str:
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_ACTOR_REQUIRED"})
    return actor


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    service = CalyxAgentService()
    return {
        "status": "foundation",
        "provider_status": service.provider_status(),
        "tools": default_tool_registry().describe(),
        "governance": {
            "automatic": ["read_only_inspection", "audit_planning", "bounded_diagnostics"],
            "prepare_only": ["build_specifications", "monitoring_specs", "draft_work_plans"],
            "owner_approval": ["repository_mutation", "merge", "deploy", "migration", "schedule_change"],
            "scientific_approval": ["canonical_scientific_publication"],
            "private_reasoning_stored": False,
        },
    }


@router.post("/requests")
def submit_request(
    payload: AgentRequest,
    auth: AuthDependency,
    service: ServiceDependency,
) -> dict[str, Any]:
    try:
        return service.handle(actor=_actor(auth), request_text=payload.request).to_dict()
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
