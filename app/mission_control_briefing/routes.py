from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.mission_control_access import AccessPrincipal
from app.review_api.dependencies import authenticated_principal
from app.routers.mission_control import completeness_rows, harvester_rows, metric_snapshot

from .service import MissionControlBriefingService


router = APIRouter(prefix="/api/mission-control/briefing", tags=["MISSION-CONTROL-ROLE-001G"])


def briefing_service_dependency() -> MissionControlBriefingService:
    return MissionControlBriefingService(
        completeness_provider=completeness_rows,
        harvester_provider=harvester_rows,
        metric_provider=metric_snapshot,
    )


@router.get("/modules")
def module_feed(
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: MissionControlBriefingService = Depends(briefing_service_dependency),
) -> dict[str, Any]:
    modules = service.module_feed()
    return {
        "principal_id": principal.principal_id,
        "count": len(modules),
        "modules": modules,
    }


@router.get("/harvesters")
def harvester_feed(
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: MissionControlBriefingService = Depends(briefing_service_dependency),
) -> dict[str, Any]:
    harvesters = service.harvester_feed()
    return {
        "principal_id": principal.principal_id,
        "count": len(harvesters),
        "harvesters": harvesters,
    }


@router.get("")
def role_aware_briefing(
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: MissionControlBriefingService = Depends(briefing_service_dependency),
) -> dict[str, Any]:
    return service.briefing_for_principal(principal)
