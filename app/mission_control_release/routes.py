from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.mission_control_access import AccessPrincipal
from app.review_api.dependencies import authenticated_principal, review_service_dependency
from app.review_tasks.service import GovernedReviewTaskService

from .service import MissionControlReleaseReadiness

router = APIRouter(
    prefix="/api/mission-control/release-readiness",
    tags=["MISSION-CONTROL-ROLE-001J"],
)


@router.get("")
def release_readiness(
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    return MissionControlReleaseReadiness(service).evaluate(principal)
