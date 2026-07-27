from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.mission_control_access import AccessPrincipal, CapabilityService
from app.review_api.dependencies import authenticated_principal

from .frontend_contract import build_frontend_contract
from .harvesters import normalized_harvesters
from .intelligence import build_dependency_intelligence
from .service import build_executive_state

router = APIRouter(prefix="/api/executive", tags=["MISSION-CONTROL-TELEMETRY"])


def _include_operations(principal: AccessPrincipal) -> bool:
    capabilities = set(CapabilityService().effective_capabilities(principal))
    return "mission_control.view.operations" in capabilities


@router.get("/state")
def executive_state(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    include_operations = _include_operations(principal)
    payload = build_executive_state(include_operations=include_operations)
    payload["principal"] = {
        "id": principal.principal_id,
        "authenticated": principal.authenticated,
        "roles": [role.value for role in principal.roles],
    }
    return payload


@router.get("/harvesters")
def executive_harvesters(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    include_operations = _include_operations(principal)
    return {
        "contract_version": "MISSION-CONTROL-TELEMETRY-001B",
        "harvesters": normalized_harvesters(include_operations=include_operations),
        "governance": {
            "operational_details_included": include_operations,
            "does_not_grant_scientific_authority": True,
            "does_not_publish": True,
        },
    }


@router.get("/harvesters/{source_id}")
def executive_harvester_detail(
    source_id: str,
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    include_operations = _include_operations(principal)
    for item in normalized_harvesters(include_operations=include_operations):
        if item.get("source_id") == source_id:
            return {
                "contract_version": "MISSION-CONTROL-TELEMETRY-001B",
                "harvester": item,
                "governance": {
                    "operational_details_included": include_operations,
                    "does_not_grant_scientific_authority": True,
                    "does_not_publish": True,
                },
            }
    raise HTTPException(status_code=404, detail="Harvester telemetry source not found")


@router.get("/intelligence")
def executive_intelligence(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    include_operations = _include_operations(principal)
    state = build_executive_state(include_operations=include_operations)
    harvesters = normalized_harvesters(include_operations=include_operations)
    intelligence = build_dependency_intelligence(state.get("subsystems") or [], harvesters)
    return {
        "contract_version": "MISSION-CONTROL-TELEMETRY-001D",
        "generated_at": state.get("generated_at"),
        **intelligence,
        "principal": {
            "id": principal.principal_id,
            "authenticated": principal.authenticated,
            "roles": [role.value for role in principal.roles],
        },
    }


@router.get("/frontend-contract")
def executive_frontend_contract(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    include_operations = _include_operations(principal)
    state = build_executive_state(include_operations=include_operations)
    harvesters = normalized_harvesters(include_operations=include_operations)
    intelligence = build_dependency_intelligence(state.get("subsystems") or [], harvesters)
    payload = build_frontend_contract(state, harvesters, intelligence)
    payload["principal"] = {
        "id": principal.principal_id,
        "authenticated": principal.authenticated,
        "roles": [role.value for role in principal.roles],
    }
    payload["governance"]["operational_details_included"] = include_operations
    return payload
