from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.mission_control_access import AccessPrincipal, CapabilityService
from app.review_api.dependencies import authenticated_principal

from .service import build_executive_state

router = APIRouter(prefix="/api/executive", tags=["MISSION-CONTROL-TELEMETRY-001A"])


@router.get("/state")
def executive_state(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    capabilities = set(CapabilityService().effective_capabilities(principal))
    include_operations = "mission_control.view.operations" in capabilities
    payload = build_executive_state(include_operations=include_operations)
    payload["principal"] = {
        "id": principal.principal_id,
        "authenticated": principal.authenticated,
        "roles": [role.value for role in principal.roles],
    }
    return payload
